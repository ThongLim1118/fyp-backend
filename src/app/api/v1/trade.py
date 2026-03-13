from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from datetime import datetime
import asyncio

router = APIRouter(prefix="/trade", tags=["trade"])

from src.app.db.bot_db_loader import (
    get_bot_list,
    get_recent_trades,
    get_portfolio_daily_series,
    get_all_strategy_metrics,
    get_all_open_positions,
)


@router.get("/bots")
def list_bots():
    return {"bots": get_bot_list()}

# 组合的权益曲线 + 回撤数据
@router.get("/portfolio/daily")
def portfolio_daily(days: int = 30):
    return get_portfolio_daily_series(days)

# 所有 bot 的绩效指标
@router.get("/metrics")
def metrics(days: int = 30, starting_equity_per_bot: float = 10_000.0):
    return get_all_strategy_metrics(days, starting_equity_per_bot)

@router.get("/bots/{bot_name}/trades")
def recent_trades(bot_name: str, limit: int = 50):
    try:
        trades = get_recent_trades(bot_name, limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "bot": bot_name,
        "trades": trades,
    }

# 当前所有持仓
@router.get("/open-positions")
def open_positions(portfolio_equity: float = 100_000.0):
    return get_all_open_positions(portfolio_equity)


@router.websocket("/ws/portfolio")
async def ws_portfolio(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            metrics = get_all_strategy_metrics(days=30, starting_equity_per_bot=10_000.0)
            payload = {
                "type": "snapshot",
                "timestamp": datetime.utcnow().isoformat(),
                "equity": get_portfolio_daily_series(days=30),
                "metrics": metrics,
                "open_positions": get_all_open_positions(portfolio_equity=100_000.0),
            }
            await ws.send_json(payload)
            await asyncio.sleep(5)  # 每 5 秒推一次
    except WebSocketDisconnect:
        print("Client disconnected from /ws/portfolio")
    except RuntimeError as e:
        print("WS runtime error on /ws/portfolio:", repr(e))
    except Exception as e:
        print("Unexpected WS error on /ws/portfolio:", repr(e))
