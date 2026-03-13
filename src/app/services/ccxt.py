from typing import List

from sqlalchemy.orm import Session
from src.app.api.v1 import ohlcv
from src.app.models.ohlcv import OHLCV
import ccxt
from datetime import datetime, timedelta
import time
import re

def normalize_pair_for_binance(pair: str) -> str:
    """
    Normalize pair strings like 'BTCUSDT' or 'btc/usdt' to ccxt/Binance style 'BTC/USDT'.
    If already valid, returns as-is.
    """
    pair = pair.strip().upper()

    # If it already has a slash, assume it's fine.
    if "/" in pair:
        return pair

    # Handle common quote currencies
    for quote in ("USDT", "BUSD", "USDC", "BTC", "ETH"):
        if pair.endswith(quote):
            base = pair[: -len(quote)]
            return f"{base}/{quote}"

    # Fallback: return unchanged (will likely fail, but you'll see it in logs)
    return pair

def download_direct_to_db(pairs: List[str], timeframe: str, timerange: str, db_session: Session):
    """Directly download data using CCXT and save to the database, supports timerange format"""
    
    exchange = ccxt.binance()
    
    for pair in pairs:
        print(f"Download {pair} {timeframe} data...")
            
        since = None
        til = None
        if timerange:
            match = re.match(r'(\d{8})(?:-(\d{8}))?', timerange)
            if match:
                start_date = match.group(1)
                end_date = match.group(2)
                start_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}T00:00:00Z"
                end_str  = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}T00:00:00Z"
                since = exchange.parse8601(start_str)
                til = exchange.parse8601(end_str)
            if til is None:
                til = exchange.milliseconds()
        
        data_len = 0
        while True:
            if since is not None and til is not None and since >= til:
                print("✅ All data fetched.")
                break
            # Download in chunks of max 1000 candles
            ohlcv = exchange.fetch_ohlcv(pair, timeframe, since=since, limit=1000)
            for candle in ohlcv:
                if til is not None and candle[0] >= til:
                    ohlcv_limited = ohlcv[:ohlcv.index(candle)]
                    break
            else:
                ohlcv_limited = ohlcv
            normalized_pair = normalize_pair_for_binance(pair)
            for candle in ohlcv_limited:
                ohlcv_record = OHLCV(
                    symbol=normalized_pair,
                    timeframe=timeframe,
                    ts=datetime.fromtimestamp(candle[0] / 1000),
                    open=candle[1],
                    high=candle[2],
                    low=candle[3],
                    close=candle[4],
                    volume=candle[5]
                )
                db_session.merge(ohlcv_record) 
            data_len += len(ohlcv_limited)
            if ohlcv_limited:
                last_timestamp = ohlcv_limited[-1][0]
                since = last_timestamp + 1
            elif ohlcv:
                print("✅ All data within timerange fetched.")
                break
            else:
                print("⚠️ No new candles returned. Ending loop.")
                break
            time.sleep(2)
            
        print(f"{pair} downloaded, total {data_len} records")
        
    print("All data downloaded and saved")