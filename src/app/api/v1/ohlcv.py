from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from app.api.deps import get_db
from app.models.ohlcv import OHLCV
from app.services.ccxt import download_direct_to_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ohlcv", tags=["ohlcv"])

Timeframe = Literal["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d", "1w", "1M"]

class OHLCVBody(BaseModel):
    pairs: list[str] = Field(..., min_length=1, description="如 ['BTCUSDT','ETHUSDT']")
    timeframe: Timeframe = "1d"
    timerange: str = Field(
        ..., 
        description="下载数据的日期范围, 格式如: '20220101-' 或 '20220101-20230101'"
    )

class DownloadResult(BaseModel):
    ok: bool
    detail: str | None = None


@router.post("/")
def download_data(body: OHLCVBody, db: Session = Depends(get_db)):
    print(f"Type of injected db: {type(db)}")
    download_direct_to_db(body.pairs, body.timeframe, body.timerange, db_session=db)
    return {"ok": True}

@router.get("")
def list_ohlcv(symbol: str, tf: str="1h", limit: int=500, exchange: str="binance", db: Session = Depends(get_db)):
    q = (db.query(OHLCV)
           .filter(OHLCV.exchange==exchange, OHLCV.symbol==symbol, OHLCV.timeframe==tf)
           .order_by(OHLCV.ts.desc())
           .limit(limit))
    rows = q.all()
    return [dict(ts=r.ts, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
            for r in reversed(rows)]
