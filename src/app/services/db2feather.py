# app/services/backtest/db2feather.py
from __future__ import annotations
from typing import Optional, Tuple, Iterable
from pathlib import Path
import tempfile
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text


def parse_timerange(timerange: Optional[str]) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """
    Support 'YYYYMMDD-YYYYMMDD' / 'YYYYMMDD-' / '-YYYYMMDD' / None
    Return UTC pandas Timestamp or None
    """
    if not timerange:
        return None, None
    s, e = None, None
    parts = timerange.split("-")
    if len(parts) == 2:
        if parts[0]:
            s = pd.to_datetime(parts[0], format="%Y%m%d").tz_localize("UTC")
        if parts[1]:
            # 结束日一般含该日全体，取到日末 23:59:59
            e = (pd.to_datetime(parts[1], format="%Y%m%d") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).tz_localize("UTC")
    else:
        # 兼容单一日期
        s = pd.to_datetime(timerange, format="%Y%m%d").tz_localize("UTC")
    return s, e

def load_ohlcv_df_from_db(db: Session, symbol: str, timeframe: str,
                          timerange: Optional[str]) -> pd.DataFrame:
    """
    Direct SQL query.
    - symbol: 'BTC/USDT'
    - timeframe: '1h'
    """
    # db_symbol = pair_to_db_symbol(symbol)
    start_ts, end_ts = parse_timerange(timerange)
    sql = """
        SELECT ts AS date, open, high, low, close, volume
        FROM ohlcv
        WHERE symbol = :symbol AND timeframe = :timeframe
        {extra_where}
        ORDER BY ts ASC
    """
    extra_where = []
    params = {"symbol": symbol, "timeframe": timeframe}
    if start_ts is not None:
        extra_where.append("AND ts >= :start_ts")
        params["start_ts"] = start_ts.to_pydatetime().isoformat()
    if end_ts is not None:
        extra_where.append("AND ts <= :end_ts")
        params["end_ts"] = end_ts.to_pydatetime().isoformat()

    sql = sql.format(extra_where=" ".join(extra_where))
    df = pd.read_sql(text(sql), db.get_bind(), params=params)

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.sort_values("date").drop_duplicates(subset=["date"])
        df = df[["date", "open", "high", "low", "close", "volume"]]
    return df

# def pair_to_db_symbol(pair: str) -> str:
#     """
#     'BTC/USDT' -> 'BTCUSDT'
#     'ETH/USDT:USDT' -> 'ETHUSDT'  # 如果你合约表里也用这个命名可自行调整
#     """
#     # 去掉 / 和 :
#     return pair.replace("/", "").split(":")[0]

def pair_to_filename(pair: str) -> str:
    # 把 'ETH/USDT:USDT' → 'ETH_USDT_USDT'，'BTC/USDT' → 'BTC_USDT'
    return pair.replace("/", "_").replace(":", "_")

def dump_pairs_to_feather(db: Session,
                          exchange: str,
                          pairs: Iterable[str],
                          timeframe: str,
                          timerange: Optional[str],
                          trading_mode: str = "spot",  # "spot" | "futures"
                          datadir: Optional[str] = None,
                          base_dir: Optional[str] = None) -> str:
    """
    Return a temporary datadir, with internal structure: {datadir}/{exchange}/*.feather
    Pass --datadir pointing to this directory when backtesting with Freqtrade.
    """
    if base_dir:
        base = Path(base_dir)
    else:
        base = Path(datadir) if datadir else Path(tempfile.mkdtemp(prefix="ft_datadir_"))
    exdir = base / "data" /exchange
    exdir.mkdir(parents=True, exist_ok=True)

    suffix = "-futures" if trading_mode == "futures" else ""
    missing = []
    for pair in pairs:
        df = load_ohlcv_df_from_db(db, pair, timeframe, timerange)
        if df.empty:
            # Write empty file, avoid Freqtrade reporting "missing file" and failing the whole backtest (can be changed as needed)
            # (exdir / f"{pair_to_filename(pair)}-{timeframe}{suffix}.feather").touch()
            missing.append(pair)
            continue

        outp = exdir / f"{pair_to_filename(pair)}-{timeframe}{suffix}.feather"
        df.reset_index(drop=True).to_feather(outp)
        print(f"[WRITE] {outp} rows={len(df)}")
    if missing:
        # List pair/timeframe/timerange，for debugging
        raise ValueError(
            f"No OHLCV found for {missing} at timeframe={timeframe} "
            f"within timerange={timerange or '(all)'}; "
            f"check symbol naming and timeframe in DB."
        )

    return str(base)
