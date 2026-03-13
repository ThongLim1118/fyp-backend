# src/app/main/run.py
import logging
from fastapi import FastAPI
from src.app.settings import settings
from src.app.services.ft import FT
from src.app.api.v1 import ohlcv, backtest, ping, trade  # 路由模块
from src.app.core.exceptions import register_exception_handlers
from src.app.core.middleware.log import access_log
from src.app.core.middleware.response import unify_response
from fastapi.middleware.cors import CORSMiddleware


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
register_exception_handlers(app)      
app.middleware("http")(access_log)    
# app.middleware("http")(unify_response) 
origins = [
    "http://localhost:3000",  #Frontend development server (e.g., React/Vue)
    "http://localhost:5173",  # Another common dev server port (e.g., Vite)
    "http://127.0.0.1:3000",
    # Add deployed frontend domain here later (e.g., "https://your-app.com")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,                   # List of origins that are allowed to make requests
    allow_credentials=True,                  # Allow cookies/authorization headers
    allow_methods=["*"],                     # Allow all standard methods (GET, POST, PUT, DELETE, and OPTIONS)
    allow_headers=["*"],                     # Allow all headers
)

# Register routers
app.include_router(ohlcv.router, prefix="/api/v1")
app.include_router(backtest.router, prefix="/api/v1")
app.include_router(trade.router, prefix="/api/v1")


app.include_router(ping.router, prefix="/api/v1")