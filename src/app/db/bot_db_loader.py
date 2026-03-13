import glob
import os
from pathlib import Path
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import math

# ---------- DB discovery / basic loader ----------

SCRIPT_DIR = Path(__file__).resolve().parent
# Walk upwards until we find a folder that has "shared_db"
PROJECT_ROOT = SCRIPT_DIR
while not (PROJECT_ROOT / "shared_db").exists() and PROJECT_ROOT != PROJECT_ROOT.parent:
    PROJECT_ROOT = PROJECT_ROOT.parent

DB_PATH = PROJECT_ROOT / "shared_db"

# Load all *.sqlite files inside shared_db/
db_engines = {}

for db_path in glob.glob(os.path.join(DB_PATH, "*.sqlite")):
    # Extract filename without extension: "bot1"
    name = os.path.splitext(os.path.basename(db_path))[0]

    # Create SQLAlchemy engine
    engine = create_engine(
        f"sqlite:///{db_path}?mode=ro", connect_args={"check_same_thread": False}
    )

    db_engines[name] = engine

print(f"[BOT DB Loader] Loaded databases: {list(db_engines.keys())}")


def get_bot_list():
    """Return list of bot names (based on database filenames)."""
    return list(db_engines.keys())


def run_query(bot_name: str, query: str):
    """
    Run SQL query on a specific bot database.
    Returns list of dicts.
    """

    if bot_name not in db_engines:
        raise ValueError(
            f"Bot '{bot_name}' does not exist. Available: {get_bot_list()}"
        )

    engine = db_engines[bot_name]

    with engine.connect() as conn:
        results = conn.execute(text(query))
        return [dict(row._mapping) for row in results]


def get_recent_trades(bot_name: str, limit: int = 20):
    """Quick helper to fetch last N trades."""
    query = f"""
        SELECT *
        FROM trades
        ORDER BY open_date DESC
        LIMIT {limit}
    """
    return run_query(bot_name, query)


# ---------- Small datetime helpers ----------

def _parse_dt(v):
    """Handle datetime coming back as str or datetime."""
    if isinstance(v, datetime):
        return v
    # freqtrade uses 'YYYY-MM-DD HH:MM:SS'
    return datetime.fromisoformat(str(v))


def _days_ago(n: int) -> str:
    """Cutoff as string for SQL."""
    dt = datetime.utcnow() - timedelta(days=n)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ======================================================================
#  A) Equity + Drawdown (portfolio daily series)
# ======================================================================

def get_daily_pnl_per_bot(bot_name: str, days: int = 30):
    """
    Returns list of {'day': 'YYYY-MM-DD', 'pnl': float} for a single bot.
    Uses closed trades in last N days and close_profit_abs.
    """
    cutoff = _days_ago(days)
    q = f"""
        SELECT
            DATE(close_date) AS day,
            SUM(close_profit_abs) AS pnl
        FROM trades
        WHERE is_open = 0
          AND close_date >= '{cutoff}'
        GROUP BY DATE(close_date)
        ORDER BY DATE(close_date)
    """
    rows = run_query(bot_name, q)
    return [{"day": r["day"], "pnl": float(r["pnl"] or 0.0)} for r in rows]


def get_portfolio_daily_series(days: int = 30, starting_equity_per_bot: float = 10_000.0):
    """
    Aggregate all bots into a single portfolio series.
    Returns:
      {
        'daily': [
          {'day': 'YYYY-MM-DD', 'pnl': float, 'equity': float,
           'drawdown': float, 'drawdown_pct': float}
        ]
      }
    """
    bots = get_bot_list()
    if not bots:
        return {"daily": []}

    # 1) aggregate daily pnl across bots
    agg = {}  # day -> pnl
    for bot in bots:
        for row in get_daily_pnl_per_bot(bot, days):
            agg.setdefault(row["day"], 0.0)
            agg[row["day"]] += row["pnl"]

    if not agg:
        return {"daily": []}

    days_sorted = sorted(agg.keys())

    # 2) build equity + drawdown
    starting_equity = starting_equity_per_bot * len(bots)
    equity = starting_equity
    max_equity = starting_equity

    series = []
    for d in days_sorted:
        pnl = agg[d]
        equity += pnl
        max_equity = max(max_equity, equity)
        dd = equity - max_equity
        dd_pct = (dd / max_equity) if max_equity > 0 else 0.0

        series.append(
            {
                "day": d,
                "pnl": pnl,
                "equity": equity,
                "drawdown": dd,
                "drawdown_pct": dd_pct,
            }
        )

    return {"daily": series}


# ======================================================================
#  B) Per-strategy metrics (30d, incl. fees)
# ======================================================================

def get_closed_trades_30d(bot_name: str, days: int = 30):
    """
    Closed trades in last N days with PnL + fee info.
    """
    cutoff = _days_ago(days)
    q = f"""
        SELECT
            id,
            pair,
            open_date,
            close_date,
            close_profit_abs,
            close_profit              AS profit_ratio,
            stake_amount,
            amount,
            COALESCE(fee_open_cost, 0)   AS fee_open_cost,
            COALESCE(fee_close_cost, 0)  AS fee_close_cost,
            COALESCE(funding_fees, 0)    AS funding_fees
        FROM trades
        WHERE is_open = 0
          AND close_date >= '{cutoff}'
        ORDER BY close_date ASC
    """
    rows = run_query(bot_name, q)
    trades = []
    for r in rows:
        fee_open = float(r["fee_open_cost"] or 0.0)
        fee_close = float(r["fee_close_cost"] or 0.0)
        funding = float(r["funding_fees"] or 0.0)
        total_fees = fee_open + fee_close + funding

        trades.append(
            {
                "open_date": _parse_dt(r["open_date"]),
                "close_date": _parse_dt(r["close_date"]),
                "pnl": float(r["close_profit_abs"] or 0.0),
                "profit_ratio": float(r["profit_ratio"] or 0.0),
                "stake_amount": float(r["stake_amount"] or 0.0),
                "amount": float(r["amount"] or 0.0),
                "fees": total_fees,
            }
        )
    return trades


def compute_strategy_metrics(
    bot_name: str, days: int = 30, starting_equity: float = 10_000.0
):
    """
    30d return / vol / Sharpe, time-in-market, profit factor,
    win rate, avg duration, and total fees (for one bot).
    """
    trades = get_closed_trades_30d(bot_name, days)
    window_days = days

    if not trades:
        return {
            "bot": bot_name,
            "pnl_30d": 0.0,
            "return_30d": 0.0,
            "vol_30d": 0.0,
            "sharpe_30d": 0.0,
            "time_in_market_pct": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "avg_duration_minutes": 0.0,
            "fees_30d": 0.0,
        }

    total_pnl = sum(t["pnl"] for t in trades)
    total_return = total_pnl / starting_equity  # simple 30d return
    fees_30d = sum(t["fees"] for t in trades)

    # --- daily returns for vol / Sharpe (simple approximation) ---
    daily = {}
    for t in trades:
        d = t["close_date"].date()
        daily.setdefault(d, 0.0)
        daily[d] += t["pnl"]

    equity = starting_equity
    daily_returns = []
    for d in sorted(daily.keys()):
        pnl = daily[d]
        r = pnl / equity if equity > 0 else 0.0
        daily_returns.append(r)
        equity += pnl

    if len(daily_returns) > 1:
        avg_r = sum(daily_returns) / len(daily_returns)
        var_r = sum((x - avg_r) ** 2 for x in daily_returns) / (len(daily_returns) - 1)
        std_r = math.sqrt(var_r)
        vol_30d = std_r * math.sqrt(len(daily_returns))  # rough 30d vol
        sharpe = (avg_r / std_r) * math.sqrt(365) if std_r > 0 else 0.0
    else:
        vol_30d = 0.0
        sharpe = 0.0

    # --- time in market (percentage of time capital is in a trade) ---
    end = datetime.utcnow()
    start = end - timedelta(days=window_days)
    window_seconds = window_days * 24 * 3600

    total_held_seconds = 0.0
    for t in trades:
        open_dt = max(t["open_date"], start)
        close_dt = min(t["close_date"], end)
        if close_dt > open_dt:
            total_held_seconds += (close_dt - open_dt).total_seconds()

    time_in_market_pct = (
        total_held_seconds / window_seconds if window_seconds > 0 else 0.0
    )

    # --- profit factor, win rate, avg duration ---
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = sum(t["pnl"] for t in trades if t["pnl"] < 0)
    profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else 0.0

    wins = [t for t in trades if t["pnl"] > 0]
    win_rate = len(wins) / len(trades)

    avg_duration_minutes = (
        sum((t["close_date"] - t["open_date"]).total_seconds() for t in trades)
        / len(trades)
        / 60.0
    )

    return {
        "bot": bot_name,
        # absolute PnL in this window (USD/quote)
        "pnl_30d": total_pnl,
        # percentage return on starting_equity
        "return_30d": total_return,
        "vol_30d": vol_30d,
        "sharpe_30d": sharpe,
        "time_in_market_pct": time_in_market_pct,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "avg_duration_minutes": avg_duration_minutes,
        "fees_30d": fees_30d,
    }


def get_all_strategy_metrics(days: int = 30, starting_equity_per_bot: float = 10_000.0):
    bots = get_bot_list()
    strategies = []

    # Initialize summary accumulator
    summary_acc = {
        "bot": "SUMMARY",
        "pnl_30d": 0.0,
        "return_30d": 0.0,
        "sharpe_30d": 0.0,
        "vol_30d": 0.0,
        "profit_factor": 0.0,
        "win_rate": 0.0,
        "time_in_market_pct": 0.0,
        "avg_duration_minutes": 0.0,

        "max_dd": float("inf"),
        "max_dd_pct": float("inf"),
        "open_positions_count": 0,

        "fees_total": 0.0,
        "fees_total_30d": 0.0,

        "realized_equity": 0.0,
        "exposure": 0.0,
        "free_cash": 0.0,
    }

    if not bots:
        return {"summary": summary_acc, "strategies": []}

    for bot in bots:
        # ---- Base strategy metrics ----
        m = compute_strategy_metrics(bot, days, starting_equity_per_bot)

        # ---- Max DD (strategy level) ----
        closed_trades = get_closed_trades_30d(bot, days)
        equity = starting_equity_per_bot
        equity_curve = []
        for t in closed_trades:
            equity += t["pnl"]
            equity_curve.append(equity)
        max_dd, max_dd_pct = compute_max_drawdown(equity_curve)
        m["max_dd"] = max_dd
        m["max_dd_pct"] = max_dd_pct

        # ---- Open position count ----
        m["open_positions_count"] = get_open_position_count(bot)

        # ---- Section D numbers ----
        m["fees_total"] = get_total_fees(bot)
        m["fees_total_30d"] = get_total_fees(bot, days)
        m["realized_equity"] = get_realized_equity(bot, starting_equity_per_bot)
        m["exposure"] = get_exposure(bot)
        m["free_cash"] = get_free_cash(bot, starting_equity_per_bot, price_map=None)

        strategies.append(m)

        # ==============================
        # Aggregate into summary
        # ==============================
        summary_acc["pnl_30d"] += m["pnl_30d"]
        summary_acc["return_30d"] += m["return_30d"]
        summary_acc["sharpe_30d"] += m["sharpe_30d"]
        summary_acc["vol_30d"] += m["vol_30d"]
        summary_acc["profit_factor"] += m["profit_factor"]
        summary_acc["win_rate"] += m["win_rate"]
        summary_acc["time_in_market_pct"] += m["time_in_market_pct"]
        summary_acc["avg_duration_minutes"] += m["avg_duration_minutes"]

        summary_acc["open_positions_count"] += m["open_positions_count"]

        summary_acc["fees_total"] += m["fees_total"]
        summary_acc["fees_total_30d"] += m["fees_total_30d"]
        summary_acc["realized_equity"] += m["realized_equity"]
        summary_acc["exposure"] += m["exposure"]
        summary_acc["free_cash"] += m["free_cash"]

        # Worst DD (lowest)
        summary_acc["max_dd"] = min(summary_acc["max_dd"], m["max_dd"])
        summary_acc["max_dd_pct"] = min(summary_acc["max_dd_pct"], m["max_dd_pct"])

    # Average metrics (all % and ratios)
    n = len(strategies)
    for key in [
        "return_30d",
        "sharpe_30d",
        "vol_30d",
        "profit_factor",
        "win_rate",
        "time_in_market_pct",
        "avg_duration_minutes",
    ]:
        summary_acc[key] /= n

    return {
        "summary": summary_acc,
        "strategies": strategies,
    }


# ======================================================================
#  C) Open trades / exposure
# ======================================================================

def get_open_positions(bot_name: str):
    """
    Return open trades for a single bot.
    Uses only columns we know exist in your schema.
    """
    q = """
        SELECT
            pair,
            open_date,
            open_rate,
            amount,
            stake_amount,
            COALESCE(stop_loss, 0) AS stop_loss,
            COALESCE(funding_fee_running, 0) AS funding_fee_running
        FROM trades
        WHERE is_open = 1
    """
    rows = run_query(bot_name, q)
    now = datetime.utcnow()
    positions = []

    for r in rows:
        open_dt = _parse_dt(r["open_date"])
        age_minutes = (now - open_dt).total_seconds() / 60.0

        positions.append(
            {
                "bot": bot_name,
                "pair": r["pair"],
                "open_date": open_dt.isoformat(),
                "open_rate": float(r["open_rate"]),
                "amount": float(r["amount"]),
                "stake_amount": float(r["stake_amount"]),
                "stop_loss": float(r["stop_loss"]),
                "funding_fee_running": float(r["funding_fee_running"]),
                "age_minutes": age_minutes,
            }
        )

    return positions


def get_all_open_positions(portfolio_equity: float = 100_000.0):
    """
    Returns list of all open positions across bots, including allocation% per position.
    Allocation = stake_amount / portfolio_equity
    """
    all_pos = []
    for bot in get_bot_list():
        all_pos.extend(get_open_positions(bot))

    if portfolio_equity <= 0:
        for p in all_pos:
            p["allocation_pct"] = 0.0
        return all_pos

    for p in all_pos:
        exposure = p["stake_amount"]
        p["allocation_pct"] = exposure / portfolio_equity

    return all_pos


# ======================================================================
#  D) Fees & balances (per strategy)
# ======================================================================

def get_total_fees(bot_name: str, days: int | None = None) -> float:
    """
    Total fees (open + close + funding) for this bot.
    If days is provided, limit to recent window.
    """
    where_clause = ""
    if days is not None:
        cutoff = _days_ago(days)
        where_clause = f"WHERE close_date >= '{cutoff}'"

    q = f"""
        SELECT
            COALESCE(SUM(fee_open_cost + fee_close_cost + funding_fees), 0)
                AS total_fees
        FROM trades
        {where_clause}
    """
    rows = run_query(bot_name, q)
    return float(rows[0]["total_fees"] or 0.0)


def get_realized_equity(bot_name: str, starting_balance: float) -> float:
    """
    Equity considering only closed trades.
    """
    q = """
        SELECT COALESCE(SUM(close_profit_abs), 0) AS pnl
        FROM trades
        WHERE is_open = 0
    """
    rows = run_query(bot_name, q)
    realized_pnl = float(rows[0]["pnl"] or 0.0)
    return starting_balance + realized_pnl


def get_exposure(bot_name: str) -> float:
    """
    Capital currently deployed in open trades (stake sum).
    """
    q = """
        SELECT COALESCE(SUM(stake_amount), 0) AS exposure
        FROM trades
        WHERE is_open = 1
    """
    rows = run_query(bot_name, q)
    return float(rows[0]["exposure"] or 0.0)


def get_unrealized_pnl(bot_name: str, price_map: dict[str, float]) -> float:
    """
    Unrealized PnL for open trades.
    Requires a mapping { 'BTC/USDT': last_price, ... }.
    Includes funding_fee_running.
    """
    q = """
        SELECT
            pair,
            open_rate,
            amount,
            COALESCE(funding_fee_running, 0) AS funding_fee_running
        FROM trades
        WHERE is_open = 1
    """
    rows = run_query(bot_name, q)
    total = 0.0

    for r in rows:
        pair = r["pair"]
        price = price_map.get(pair)
        if price is None:
            continue

        open_rate = float(r["open_rate"])
        amount = float(r["amount"])
        ff = float(r["funding_fee_running"] or 0.0)

        pnl = (price - open_rate) * amount + ff
        total += pnl

    return total


def get_current_balance(
    bot_name: str,
    starting_balance: float,
    price_map: dict[str, float] | None = None,
) -> float:
    """
    Current account value for a strategy:
    starting_balance + realized_pnl + unrealized_pnl.
    If price_map is None, unrealized_pnl is treated as 0.
    """
    realized_equity = get_realized_equity(bot_name, starting_balance)
    if not price_map:
        return realized_equity

    unrealized = get_unrealized_pnl(bot_name, price_map)
    return realized_equity + unrealized


def get_free_cash(
    bot_name: str,
    starting_balance: float,
    price_map: dict[str, float] | None = None,
) -> float:
    """
    Free cash = current balance - exposure.
    """
    balance = get_current_balance(bot_name, starting_balance, price_map)
    exposure = get_exposure(bot_name)
    return balance - exposure

def compute_portfolio_sharpe(days: int = 30, starting_equity_per_bot: float = 10_000.0) -> float:
    """
    Sharpe for the whole portfolio (all bots combined) over last N days.
    Uses the same aggregated daily PnL as get_portfolio_daily_series.
    """
    bots = get_bot_list()
    if not bots:
        return 0.0

    daily = get_portfolio_daily_series(days, starting_equity_per_bot)["daily"]
    if len(daily) < 2:
        return 0.0

    total_start_equity = starting_equity_per_bot * len(bots)
    equity = total_start_equity
    rets = []

    for d in daily:
        pnl = d["pnl"]
        r = pnl / equity if equity > 0 else 0.0
        rets.append(r)
        equity += pnl

    if len(rets) < 2:
        return 0.0

    avg_r = sum(rets) / len(rets)
    var_r = sum((x - avg_r) ** 2 for x in rets) / (len(rets) - 1)
    std_r = math.sqrt(var_r)
    return (avg_r / std_r) * math.sqrt(365) if std_r > 0 else 0.0

def compute_max_drawdown(equity_points: list[float]):
    if not equity_points:
        return 0.0, 0.0
    peak = equity_points[0]
    max_dd = 0.0
    for e in equity_points:
        if e > peak:
            peak = e
        dd = e - peak
        if dd < max_dd:
            max_dd = dd
    max_dd_pct = max_dd / peak if peak > 0 else 0.0
    return max_dd, max_dd_pct

def get_open_position_count(bot_name: str):
    q = "SELECT COUNT(*) AS cnt FROM trades WHERE is_open = 1"
    rows = run_query(bot_name, q)
    return int(rows[0]["cnt"])
