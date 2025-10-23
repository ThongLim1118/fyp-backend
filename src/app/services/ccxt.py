from typing import List

from sqlalchemy.orm import Session
from app.models.ohlcv import OHLCV
import ccxt
from datetime import datetime, timedelta
import re

def download_direct_to_db(pairs: List[str], timeframe: str, timerange: str, db_session: Session):
    """直接使用CCXT下载数据并存入数据库，支持timerange格式"""
    
    exchange = ccxt.binance()
    
    for pair in pairs:
        print(f"下载 {pair} {timeframe} 数据...")
            
        # 解析 timerange 逻辑保持不变...
        since = None
        if timerange:
            match = re.match(r'(\d{8})(?:-(\d{8}))?', timerange)
            if match:
                start_date = match.group(1)
                start_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}T00:00:00Z"
                since = exchange.parse8601(start_str)
        
        # 下载数据
        ohlcv = exchange.fetch_ohlcv(pair, timeframe, since=since, limit=1000)
            
        for candle in ohlcv:
            ohlcv_record = OHLCV(
                symbol=pair,
                timeframe=timeframe,
                ts=datetime.fromtimestamp(candle[0] / 1000),
                open=candle[1],
                high=candle[2],
                low=candle[3],
                close=candle[4],
                volume=candle[5]
            )
            db_session.merge(ohlcv_record) 
            
        print(f"{pair} 下载完成，共 {len(ohlcv)} 条记录")
        
    print("所有数据下载并保存完成")