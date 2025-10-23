import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from app.db.session import SessionLocal
from app.models.ohlcv import OHLCV

def ingest_df(df: pd.DataFrame, exchange: str, symbol: str, timeframe: str) -> int:
    # 期望 df 列: ts/open/high/low/close/volume
    records = [{
        "exchange": exchange, 
        "symbol": symbol, 
        "timeframe": timeframe, 
        **r
    } for r in df.to_dict(orient="records")]
    if not records:
        return 0
    with SessionLocal() as s:
        stmt = insert(OHLCV).values(records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["exchange","symbol","timeframe","ts"])
        s.execute(stmt)
        s.commit()
    return len(records)
