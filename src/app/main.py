# src/app/main/run.py
import logging
from fastapi import FastAPI
from app.settings import settings
from app.services.ft import FT
from app.api.v1 import ohlcv, backtest, ping  # 路由模块
from app.core.exceptions import register_exception_handlers
from app.core.middleware.log import access_log
from app.core.middleware.response import unify_response

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ft = FT(userdir=str(settings.freqtrade_userdir),
                      config=str(settings.freqtrade_config_path))
    yield

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

app = FastAPI(title="Freqtrade API", lifespan=lifespan)
register_exception_handlers(app)       # 1) 统一异常
app.middleware("http")(access_log)     # 2) 访问日志
app.middleware("http")(unify_response) # 3) 统一响应

# 注册路由
app.include_router(ohlcv.router, prefix="/api/v1")
app.include_router(backtest.router, prefix="/api/v1")


app.include_router(ping.router, prefix="/api/v1")