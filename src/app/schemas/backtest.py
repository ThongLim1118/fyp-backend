# from datetime import datetime
# from pydantic import BaseModel
# from typing import Optional, List, Any

# class BacktestRunOut(BaseModel):
#     id: int
#     strategy: str
#     timeframe: Optional[str]
#     timerange: Optional[str]
#     run_started_at: Optional[datetime]
#     run_finished_at: Optional[datetime]
#     total_trades: Optional[int]
#     winrate: Optional[float]
#     total_return: Optional[float]
#     max_drawdown: Optional[float]
#     sharpe: Optional[float]
#     sortino: Optional[float]

#     class Config:
#         from_attributes = True

# class BacktestPairOut(BaseModel):
#     id: int
#     pair: str
#     trades: Optional[int]
#     profit_abs: Optional[float]
#     profit_pct: Optional[float]
#     drawdown_pct: Optional[float]
#     sharpe: Optional[float]
#     sortino: Optional[float]

#     class Config:
#         from_attributes = True

# class BacktestTradeOut(BaseModel):
#     id: int
#     pair: str
#     open_time: Optional[datetime]
#     close_time: Optional[datetime]
#     duration_sec: Optional[int]
#     side: Optional[str]
#     open_rate: Optional[float]
#     close_rate: Optional[float]
#     profit_abs: Optional[float]
#     profit_pct: Optional[float]
#     exit_reason: Optional[str]

#     class Config:
#         from_attributes = True
