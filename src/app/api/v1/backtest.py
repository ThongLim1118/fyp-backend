from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.api.deps import get_ft
from app.services.ft import FT

router = APIRouter(prefix="/backtest", tags=["backtest"])

class BacktestBody(BaseModel):
    strategy: str
    pairs: list[str]
    timeframe: str = "1h"
    timerange: str | None = None
    strategy_path: str | None = None

@router.post("/")
def run_backtest(body: BacktestBody, ft: FT = Depends(get_ft)):
    return ft.backtest(body.strategy, body.pairs, body.timeframe, body.timerange, export="trades", strategy_path=body.strategy_path)
