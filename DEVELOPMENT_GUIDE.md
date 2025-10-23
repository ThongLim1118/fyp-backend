下面是一份《DEVELOPMENT_GUIDE》，内容针对「路线B：Python + FastAPI + Freqtrade + PostgreSQL + Docker + 插件化（Entry Points）」项目。

---

# DEVELOPMENT_GUIDE — Freqtrade + FastAPI + PostgreSQL + Docker（路线 B）

## Overview

本指南教你如何在**可插拔策略**与**前后端分离**的架构下，快速搭建并迭代后端系统：

* 以 **FastAPI** 提供 REST API（OHLCV/回测/超参/实盘状态）；
* 以 **Freqtrade** 驱动回测/超参/实盘（策略放在独立插件包，通过 **entry points** 发现）；
* 以 **PostgreSQL** 为数据底座（K线、交易、实验结果等全部入库，不落 CSV）；
* 以 **Docker Compose** 统一本地与部署环境；
* 支持**多资产/多参数**并发实验（可选：队列/Worker）。

---

## Architecture Components

### 1. Core Services（`src/app/services/*`）

* `data_sync.py`：下载并入库 OHLCV（幂等，冲突忽略/更新可选）
* `backtest.py`：回测编排（可调用 Freqtrade CLI 或 SDK），聚合指标写入 `runs`
* `hyperopt.py`：超参优化编排，结果落库
* `freqtrade_runner.py`：实盘/仿真启动与监控（抽象交易所细节）
* `strategy_loader.py`：统一策略加载（优先 `entry points`，后备 dotted-path）

### 2. API Layer（`src/app/api/v1/*`）

* `ohlcv.py`：`GET /api/v1/ohlcv`（供前端绘图）
* `trades.py`：`GET /api/v1/trades`（可选）
* `metrics.py`：`GET /api/v1/metrics`、`GET /api/v1/runs/{id}`
* 返回结构统一、分页/验证中间件在 `deps.py`

### 3. Data Access（`src/app/models` + `src/app/orm` + `src/app/db`）

* **Models**：`ohlcv.py / trade.py / run.py / metric.py`（SQLAlchemy Declarative）
* **ORM Base/Repositories**：常用查询/批量 upsert/分页
* **DB Session/Engine**：连接池、预 ping、统一会话

### 4. Exchange Adapter（`src/app/exchanges/binance.py`）

* 对 CCXT / Freqtrade DataProvider 做统一封装：

  * **重试/限流**（`tenacity` + limiter）
  * 规一化返回（DataFrame 或 dict 列表）

### 5. Pipelines（`src/app/pipelines/*`）

* `ohlcv_ingest.py`：抽取→清洗→入库（含去重、时间对齐）
* `signal_compute.py`：指标/信号计算（可落宽/窄表）

### 6. Tasks（可选，`src/app/tasks/*`）

* `queue.py / jobs.py`：Celery/RQ/Huey 三选一，支持多资产/多参数并发

### 7. Plugin Package（`plugins/freqtrader_plugins/*`）

* `strategies/*`：可插拔策略实现（**entry points** 注册）
* `services/*`：如需扩展可替换的业务组件，也可注册成插件

---

## Step-by-Step Workflow

### Step 1: 准备目录与环境

```
project/
├─ .env.example
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt / pyproject.toml
├─ alembic/ (env.py, versions/)
├─ plugins/
│  ├─ pyproject.toml
│  └─ freqtrader_plugins/
│     ├─ __init__.py
│     ├─ strategies/
│     │  └─ ma_rsi.py
│     └─ services/
│        └─ my_custom_runner.py
└─ src/app/...
```

`.env.example`（复制为 `.env` 后填写）：

```
DB_USER=alpha
DB_PASS=alpha_pw
DB_NAME=alphadb
DB_HOST=db
DB_PORT=5432
BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
DEFAULT_TIMEFRAME=1h
EXCHANGE=binance
```

### Step 2: 插件包声明 Entry Points（方案 A）

`plugins/pyproject.toml`

```toml
[project]
name = "freqtrader-plugins"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pandas", "numpy"]

[project.entry-points."freqtrade.strategies"]
ma_rsi = "freqtrader_plugins.strategies.ma_rsi:MaRsiStrategy"
```

> 只注册要**动态加载**的策略/组件；工具/基类无需注册。

### Step 3: 策略骨架

`plugins/freqtrader_plugins/strategies/ma_rsi.py`

```python
class MaRsiStrategy:
    def name(self) -> str:
        return "ma_rsi"
    # 可扩展：compute_signals(df)->dict / hooks 供统一面板展示
```

### Step 4: Loader（优先 Entry Points）

`src/app/services/strategy_loader.py`

```python
from importlib.metadata import entry_points

def load_strategy(name: str):
    eps = entry_points(group="freqtrade.strategies")
    for ep in eps:
        if ep.name == name:
            return ep.load()()  # 返回实例
    raise LookupError(f"Strategy '{name}' not found")
```

### Step 5: 数据入库 Pipeline（不落 CSV）

`src/app/pipelines/ohlcv_ingest.py`

```python
import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from app.db.session import SessionLocal
from app.models.ohlcv import OHLCV
from app.exchanges.binance import fetch_ohlcv_df  # 统一返回 DF

def ingest(symbol: str, timeframe: str, exchange: str) -> int:
    df: pd.DataFrame = fetch_ohlcv_df(symbol, timeframe, exchange)
    records = [dict(exchange=exchange, symbol=symbol, timeframe=timeframe, **r)
               for r in df.to_dict(orient="records")]
    if not records:
        return 0
    with SessionLocal() as s:
        stmt = insert(OHLCV).values(records)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["exchange","symbol","timeframe","ts"]
        )
        s.execute(stmt); s.commit()
    return len(records)
```

### Step 6: FastAPI 路由（供前端）

`src/app/api/v1/ohlcv.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.ohlcv import OHLCV

router = APIRouter(prefix="/ohlcv", tags=["ohlcv"])

@router.get("")
def list_ohlcv(symbol: str, tf: str="1h", limit: int=500, db: Session=Depends(get_db)):
    q = (db.query(OHLCV)
           .filter(OHLCV.symbol==symbol, OHLCV.timeframe==tf)
           .order_by(OHLCV.ts.desc())
           .limit(limit))
    rows = q.all()
    return [dict(ts=r.ts, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
            for r in reversed(rows)]
```

### Step 7: CLI（Typer）

`src/app/main/cli.py`

```python
import typer
from app.services.data_sync import sync_assets
from app.services.backtest import run_backtests
from app.services.hyperopt import run_hyperopt
from app.services.freqtrade_runner import run_live

app = typer.Typer()

@app.command()
def sync(pairs: str, timeframe: str="1h", exchange: str="binance"):
    sync_assets(pairs.split(","), timeframe, exchange)

@app.command()
def backtest(strategy: str, pairs: str, timeframe: str="1h", days: int=365):
    run_backtests(strategy, pairs.split(","), timeframe, days)

@app.command()
def hyperopt(strategy: str, pairs: str, timeframe: str="1h", max_trials: int=50):
    run_hyperopt(strategy, pairs.split(","), timeframe, max_trials)

@app.command()
def live(strategy: str, pairs: str, exchange: str="binance-futures"):
    run_live(strategy, pairs.split(","), exchange)

if __name__ == "__main__":
    app()
```

---

## API Features

### 1) OHLCV（前端绘图）

```
GET /api/v1/ohlcv?symbol=BTCUSDT&tf=1h&limit=500
200 [
  {"ts":"2025-10-08T01:00:00Z","open":..., "high":..., "low":..., "close":..., "volume":...},
  ...
]
```

### 2) 回测/超参（可选接口）

```
POST /api/v1/backtest
Body: {"strategy":"ma_rsi","pairs":["BTCUSDT","ETHUSDT"],"timeframe":"1h","days":365}

POST /api/v1/hyperopt
Body: {"strategy":"ma_rsi","pairs":["BTCUSDT"],"timeframe":"1h","maxTrials":80}
```

### 3) 运行查询

```
GET /api/v1/runs/{id}
```

---

## Error Handling

* 统一异常处理中间件：

  * `400 Bad Request`：参数/校验错误
  * `404 Not Found`：资源不存在/策略未注册
  * `429 Too Many Requests`：限流命中
  * `500 Internal Server Error`：未捕获的服务器错误
* 记录结构化日志（JSON），脱敏敏感字段

---

## Testing

* **pytest** + **fastapi.testclient**：API/服务层单元与集成测试
* DB 测试：使用事务回滚/临时 test DB
* 示例：

```bash
pytest -q
pytest tests/api/test_ohlcv.py::test_list_ohlcv
```

---

## Best Practices

1. **策略解耦**：策略仅依赖公共工具包/标准库，不反向 import 应用代码。
2. **Entry Points 注册**：只注册需要动态加载的策略；新增/改名后记得重新 `pip install -e`。
3. **幂等入库**：`ON CONFLICT DO NOTHING/UPDATE`；对齐时间戳与精度。
4. **限流与重试**：统一在 `exchanges/*` 层处理，避免把重试逻辑散落各处。
5. **模型先行，后迁移**：改 `models/*` → `alembic revision --autogenerate` → `upgrade`。
6. **日志与可观测性**：关键路径加 timing / 计数器；必要时导出 Prometheus 指标。
7. **配置集中**：使用 `pydantic-settings` 单一入口（`settings.py`），禁止硬编码。
8. **类型与质量**：`ruff`/`mypy`/`pytest` 作为合并前门禁。

---

## Development Checklist

* [ ] `.env` 准备并通过 `settings.py` 生效
* [ ] `plugins/*` 可安装包，含正确 `pyproject.toml` 与 `entry points`
* [ ] `pip install -e ./plugins` 成功，能通过 Loader 找到策略
* [ ] 模型/迁移对齐，`alembic upgrade head` 通过
* [ ] API 返回数据结构与前端对齐（顺序、字段名、数量限制）
* [ ] CLI 能跑通 `sync/backtest/hyperopt/live`
* [ ] 有基础测试（至少 OHLCV + 一个策略回测）
* [ ] Docker/Compose 可一键起服务与 DB
* [ ] 文档更新（本文件 & README）

---

## Quick Start（命令速查）

```bash
# 构建与启动
docker compose build
docker compose up -d db
docker compose run --rm api alembic upgrade head
docker compose up -d

# 注册/更新插件（更改了 entry points 后）
docker compose exec api pip install -e /plugins

# 同步数据（不落 CSV，直接入库）
docker compose run --rm api python -m app.main.cli sync \
  --pairs "BTCUSDT,ETHUSDT" --timeframe 1h --exchange binance

# 回测 / 超参 / 实盘
docker compose run --rm api python -m app.main.cli backtest --strategy ma_rsi --pairs "BTCUSDT" --timeframe 1h --days 365
docker compose run --rm api python -m app.main.cli hyperopt  --strategy ma_rsi --pairs "BTCUSDT" --timeframe 1h --max-trials 80
docker compose run --rm api python -m app.main.cli live      --strategy ma_rsi --pairs "BTCUSDT" --exchange binance-futures
```

---

## Example: 典型策略的 Entry Point 注册

`plugins/pyproject.toml`

```toml
[project.entry-points."freqtrade.strategies"]
ma_rsi = "freqtrader_plugins.strategies.ma_rsi:MaRsiStrategy"
ema_cross = "freqtrader_plugins.strategies.ema_cross:EmaCrossStrategy"
bbands   = "freqtrader_plugins.strategies.bbands:BollingerBandStrategy"
```

> **提示**：不必把 `strategies/` 下所有文件都登记，只登记需要被“动态发现/加载”的策略类；
> 工具/基类/指标文件用普通 `import` 即可。

---

如果你希望，这份指南我也可以**输出成仓库内的 `DEVELOPMENT_GUIDE.md`** 版本，并附一个最小可运行的骨架（含 `alembic/env.py`、`settings.py`、`Dockerfile/compose` 与一个演示策略），你直接丢进仓库即可用。
