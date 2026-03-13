import os
import glob
import json
import zipfile
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, List

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import InvalidRequestError

from src.app.db.config import SessionLocal

# === 配置区域 ===
DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres.zgvzascfyfvtpmdetrwg:afubo1234@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres")
RESULTS_DIR = os.getenv("FREQTRADE_BACKTEST_RESULTS_DIR", "user_data/backtest_results")  # Freqtrade 默认回测输出目录

engine = create_engine(DB_URL, future=True)

def get_db_session() -> Session:
    """优先复用 FastAPI SessionLocal，否则创建临时引擎"""
    try:
        db = SessionLocal()
    except Exception:
        from sqlalchemy import create_engine
        engine = create_engine(DB_URL)
        db = Session(bind=engine)
    return db

def find_latest_zip(results_dir: str) -> str:
    zips = sorted(glob.glob(os.path.join(results_dir, "*.zip")), key=os.path.getmtime, reverse=True)
    if not zips:
        raise FileNotFoundError(f"No backtest zip under {results_dir}")
    return zips[0]

def read_backtest_json_from_zip(zippath: str) -> Dict[str, Any]:
    with zipfile.ZipFile(zippath) as z:
        # 经验规则：报告 JSON 通常就 1 个；若多个，取包含 "report" 或 ".json" 的最合适那个
        names = [n for n in z.namelist() if n.endswith(".json")]
        if not names:
            raise ValueError(f"No JSON report inside {zippath}")
        # 优先 report 命名
        names_sorted = sorted(names, key=lambda n: ("report" not in n, len(n)))
        data = json.loads(z.read(names_sorted[0]).decode("utf-8"))
        return data

def parse_ts(s: str):
    """把 '2025-01-01 00:00:00' 或 '2025-01-01 00:00:00+00:00' 变成 datetime"""
    if s is None:
        return None
    # 有可能已经是 datetime，就直接返回
    if isinstance(s, datetime):
        return s
    # Freqtrade 给的是 'YYYY-MM-DD HH:MM:SS' 或带 +00:00
    return datetime.fromisoformat(s)

def ts_from_ms(ms: int):
    """Freqtrade 里的 open_timestamp/close_timestamp 是毫秒"""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

import re
from datetime import datetime, date

WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

def parse_period_date(s: str):
    """
    尝试解析 periodic_breakdown 的 date 字段：
    支持：
    - '08/01/2025' (DD/MM/YYYY)
    - '2025-01-08' (ISO)
    - 'Monday'（返回固定日期，如 1970-01-05）
    - 'January'（返回该年的 1 月 1 日 → 1970-01-01）
    - '2025'（返回 2025-01-01）
    """
    if s is None:
        return None
    
    s_strip = s.strip()

    # 1) 纯数字（年份）
    if re.fullmatch(r"\d{4}", s_strip):
        return date(int(s_strip), 1, 1)

    # 2) DD/MM/YYYY
    try:
        return datetime.strptime(s_strip, "%d/%m/%Y").date()
    except ValueError:
        pass

    # 3) YYYY-MM-DD
    try:
        return datetime.strptime(s_strip, "%Y-%m-%d").date()
    except ValueError:
        pass

    # 4) 星期名（如 Monday）
    w = s_strip.lower()
    if w in WEEKDAY_MAP:
        # 固定一个星期对应日期：1970-01-05 是 Monday
        base = date(1970, 1, 5)
        return date(1970, 1, 5 + WEEKDAY_MAP[w])

    # 5) 月份名
    if w in MONTH_MAP:
        return date(1970, MONTH_MAP[w], 1)

    # 6) fallback：强制返回一个可接受的值
    #    比如任何无法解析的字符串，用 epoch date
    return date(1970, 1, 1)


def parse_iso_date(s: str):
    """daily_profit 里的日期是 '2025-01-08' 这种 ISO"""
    if s is None:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()

def insert_backtest_report(conn, report: Dict[str, Any]) -> int:
    """
    把 Freqtrade backtest json (report) 写入数据库。
    接受的是 SQLAlchemy Connection（engine.begin() 里那个 conn）。
    返回 strategy_run.id
    """
    strategy_dict = report["strategy"]
    (strategy_name, sdata), = strategy_dict.items()

    # ---------- 1) strategy_run ----------
    run_sql = text("""
        INSERT INTO strategy_run (
          strategy_name,
          timeframe,
          timerange,
          trading_mode,
          stake_currency,
          starting_balance,
          final_balance,
          backtest_start,
          backtest_end,
          backtest_days,
          total_trades,
          trades_per_day,
          market_change
        )
        VALUES (
          :strategy_name,
          :timeframe,
          :timerange,
          :trading_mode,
          :stake_currency,
          :starting_balance,
          :final_balance,
          :backtest_start,
          :backtest_end,
          :backtest_days,
          :total_trades,
          :trades_per_day,
          :market_change
        )
        RETURNING id;
    """)

    run_result = conn.execute(
        run_sql,
        {
            "strategy_name": sdata.get("strategy_name", strategy_name),
            "timeframe": sdata.get("timeframe"),
            "timerange": sdata.get("timerange"),
            "trading_mode": sdata.get("trading_mode"),
            "stake_currency": sdata.get("stake_currency"),
            "starting_balance": sdata.get("starting_balance"),
            "final_balance": sdata.get("final_balance"),
            "backtest_start": parse_ts(sdata.get("backtest_start")),
            "backtest_end": parse_ts(sdata.get("backtest_end")),
            "backtest_days": sdata.get("backtest_days"),
            "total_trades": sdata.get("total_trades"),
            "trades_per_day": sdata.get("trades_per_day"),
            "market_change": sdata.get("market_change"),
        },
    )
    run_id = run_result.scalar_one()   # 等价于 cur.fetchone()[0]

    # ---------- 2) pair_summary ----------
    pair_sql = text("""
        INSERT INTO pair_summary (
            run_id, pair_key, trades,
            profit_mean, profit_total_abs, profit_total_pct,
            winrate, cagr, sharpe, sortino, calmar,
            profit_factor, max_dd_abs
        )
        VALUES (
            :run_id, :pair_key, :trades,
            :profit_mean, :profit_total_abs, :profit_total_pct,
            :winrate, :cagr, :sharpe, :sortino, :calmar,
            :profit_factor, :max_dd_abs
        )
        ON CONFLICT (run_id, pair_key) DO NOTHING;
    """)

    for p in sdata.get("results_per_pair", []):
        conn.execute(
            pair_sql,
            {
                "run_id": run_id,
                "pair_key": p.get("key"),
                "trades": p.get("trades"),
                "profit_mean": p.get("profit_mean"),
                "profit_total_abs": p.get("profit_total_abs"),
                "profit_total_pct": p.get("profit_total_pct"),
                "winrate": p.get("winrate"),
                "cagr": p.get("cagr"),
                "sharpe": p.get("sharpe"),
                "sortino": p.get("sortino"),
                "calmar": p.get("calmar"),
                "profit_factor": p.get("profit_factor"),
                "max_dd_abs": p.get("max_drawdown_abs"),
            },
        )

    # ---------- 3) trades ----------
    trade_sql = text("""
        INSERT INTO trade (
          run_id,
          pair,
          stake_amount,
          amount,
          open_ts,
          close_ts,
          open_rate,
          close_rate,
          fee_open,
          fee_close,
          trade_duration_min,
          profit_ratio,
          profit_abs,
          exit_reason,
          initial_sl_abs,
          initial_sl_ratio,
          stop_loss_abs,
          stop_loss_ratio,
          min_rate,
          max_rate,
          leverage,
          is_short,
          enter_tag
        )
        VALUES (
          :run_id,
          :pair,
          :stake_amount,
          :amount,
          :open_ts,
          :close_ts,
          :open_rate,
          :close_rate,
          :fee_open,
          :fee_close,
          :trade_duration_min,
          :profit_ratio,
          :profit_abs,
          :exit_reason,
          :initial_sl_abs,
          :initial_sl_ratio,
          :stop_loss_abs,
          :stop_loss_ratio,
          :min_rate,
          :max_rate,
          :leverage,
          :is_short,
          :enter_tag
        )
        RETURNING id;
    """)

    order_sql = text("""
        INSERT INTO trade_order (
          trade_id,
          amount,
          price,
          side,
          filled_ts,
          is_entry,
          order_tag,
          cost
        )
        VALUES (
          :trade_id,
          :amount,
          :price,
          :side,
          :filled_ts,
          :is_entry,
          :order_tag,
          :cost
        );
    """)

    for t in sdata.get("trades", []):
        trade_result = conn.execute(
            trade_sql,
            {
                "run_id": run_id,
                "pair": t.get("pair"),
                "stake_amount": t.get("stake_amount"),
                "amount": t.get("amount"),
                "open_ts": parse_ts(t.get("open_date")),
                "close_ts": parse_ts(t.get("close_date")),
                "open_rate": t.get("open_rate"),
                "close_rate": t.get("close_rate"),
                "fee_open": t.get("fee_open"),
                "fee_close": t.get("fee_close"),
                "trade_duration_min": t.get("trade_duration"),
                "profit_ratio": t.get("profit_ratio"),
                "profit_abs": t.get("profit_abs"),
                "exit_reason": t.get("exit_reason"),
                "initial_sl_abs": t.get("initial_stop_loss_abs"),
                "initial_sl_ratio": t.get("initial_stop_loss_ratio"),
                "stop_loss_abs": t.get("stop_loss_abs"),
                "stop_loss_ratio": t.get("stop_loss_ratio"),
                "min_rate": t.get("min_rate"),
                "max_rate": t.get("max_rate"),
                "leverage": t.get("leverage"),
                "is_short": t.get("is_short"),
                "enter_tag": t.get("enter_tag"),
            },
        )
        trade_id = trade_result.scalar_one()

        for o in t.get("orders", []):
            conn.execute(
                order_sql,
                {
                    "trade_id": trade_id,
                    "amount": o.get("amount"),
                    "price": o.get("safe_price"),
                    "side": o.get("ft_order_side"),
                    "filled_ts": ts_from_ms(o.get("order_filled_timestamp")),
                    "is_entry": o.get("ft_is_entry"),
                    "order_tag": o.get("ft_order_tag"),
                    "cost": o.get("cost"),
                },
            )

    # ---------- 4) exit_reason_summary ----------
    exit_sql = text("""
        INSERT INTO exit_reason_summary (
          run_id,
          reason_key,
          trades,
          profit_mean,
          profit_total_abs,
          duration_avg_text,
          winrate,
          profit_factor
        )
        VALUES (
          :run_id,
          :reason_key,
          :trades,
          :profit_mean,
          :profit_total_abs,
          :duration_avg_text,
          :winrate,
          :profit_factor
        )
        ON CONFLICT (run_id, reason_key) DO NOTHING;
    """)

    for r in sdata.get("exit_reason_summary", []):
        conn.execute(
            exit_sql,
            {
                "run_id": run_id,
                "reason_key": r.get("key"),
                "trades": r.get("trades"),
                "profit_mean": r.get("profit_mean"),
                "profit_total_abs": r.get("profit_total_abs"),
                "duration_avg_text": r.get("duration_avg"),
                "winrate": r.get("winrate"),
                "profit_factor": r.get("profit_factor"),
            },
        )

    # ---------- 5) periodic_profit ----------
    periodic_sql = text("""
        INSERT INTO periodic_profit (
          run_id,
          period_type,
          period_date,
          profit_abs,
          wins,
          losses,
          trades,
          profit_factor
        )
        VALUES (
          :run_id,
          :period_type,
          :period_date,
          :profit_abs,
          :wins,
          :losses,
          :trades,
          :profit_factor
        );
    """)

    for period_type, rows in sdata.get("periodic_breakdown", {}).items():
        for row in rows:
            conn.execute(
                periodic_sql,
                {
                    "run_id": run_id,
                    "period_type": period_type,
                    "period_date": parse_period_date(row.get("date")),
                    "profit_abs": row.get("profit_abs"),
                    "wins": row.get("wins"),
                    "losses": row.get("losses"),
                    "trades": row.get("trades"),
                    "profit_factor": row.get("profit_factor"),
                },
            )

    # ---------- 6) daily_profit ----------
    daily_sql = text("""
        INSERT INTO daily_profit (
          run_id,
          day,
          profit_abs
        )
        VALUES (
          :run_id,
          :day,
          :profit_abs
        );
    """)

    for day_str, profit_abs in sdata.get("daily_profit", []):
        conn.execute(
            daily_sql,
            {
                "run_id": run_id,
                "day": parse_iso_date(day_str),
                "profit_abs": profit_abs,
            },
        )

    # 注意：这里不要 conn.commit()
    # engine.begin() 上下文退出时会自动 commit
    return run_id


def etl_one_zip(zippath: str) -> int:
    report = read_backtest_json_from_zip(zippath)
    # run_row = extract_run_header(report, zippath)
    # df_pairs = normalize_pairs_df(report)
    # df_trades = normalize_trades_df(report)

    # with engine.begin() as conn:
    #     run_id = insert_run(conn, run_row)
    #     upsert_pairs(conn, run_id, df_pairs)
    #     insert_trades(conn, run_id, df_trades)
    with engine.begin() as conn:
        run_id = insert_backtest_report(conn, report)
        print("Inserted strategy_run id:", run_id)
    return run_id

def etl_one_json(json_path: str) -> int:
    """兼容直接读取回测导出 JSON 文件"""
    import tempfile, zipfile, os, json

    # 将 JSON 打包成临时 ZIP，复用 etl_one_zip 逻辑
    tmp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(json_path, arcname=os.path.basename(json_path))
    tmp_zip.close()
    run_id = etl_one_zip(tmp_zip.name)
    os.remove(tmp_zip.name)
    return run_id

if __name__ == "__main__":
    db = get_db_session()
    zp = find_latest_zip(RESULTS_DIR)
    run_id = etl_one_zip(zp)
    print(f"[OK] Imported backtest run #{run_id} from {zp}")
