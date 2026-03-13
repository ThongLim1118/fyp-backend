from datetime import datetime, timezone
import glob
import os
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.app.api.deps import get_ft, get_db, get_local_db
from src.app.services.ft import FT
from src.app.services.etl_backtest_to_db import etl_one_zip, etl_one_json, find_latest_zip, RESULTS_DIR
# from src.app.models.backtest import BacktestRun, BacktestPair, BacktestTrade
# from src.app.schemas.backtest import BacktestRunOut, BacktestPairOut, BacktestTradeOut
from src.app.services.db2feather import dump_pairs_to_feather


router = APIRouter(prefix="/backtest", tags=["backtest"])

class BacktestBody(BaseModel):
    strategy: str
    pairs: list[str]
    timeframe: str = "1h"
    timerange: str | None = None
    exchange: str = "binance"
    trading_mode: str = "spot"   # "spot" or "futures"
    # strategy_path: str | None = None
    # export_filename: str | None = None

@router.post("/import-latest")
def import_latest(db: Session = Depends(get_db)):
    zp = find_latest_zip(RESULTS_DIR)
    run_id = etl_one_zip(zp)
    return {"ok": True, "run_id": run_id, "source_zip": zp}

# @router.get("/runs", response_model=List[BacktestRunOut])
# def list_runs(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
#     q = db.query(BacktestRun).order_by(BacktestRun.run_started_at.desc().nullslast())
#     items = q.offset((page-1)*size).limit(size).all()
#     return items

@router.post("/db")
def run_backtest_with_db(body: BacktestBody,
                        #  db: Session = Depends(get_db),
                         local_db: Session = Depends(get_local_db),
                         ft: FT = Depends(get_ft)):
    
    strategy = body.strategy
    pairs = body.pairs
    timeframe = body.timeframe
    timerange = body.timerange
    exchange = body.exchange
    trading_mode = body.trading_mode

    
    for p in pairs:
        cnt = local_db.execute(text(
            "SELECT count(*) FROM ohlcv WHERE symbol=:s AND timeframe=:tf AND ts >= :t0"
        ), {"s": p, "tf": timeframe, "t0": "2025-01-01"}).scalar()
        print(f"[DB CHECK] {p} {timeframe} rows since 2025-01-01 = {cnt}")
    # DB -> temporary feather datadir
    tmp_datadir = dump_pairs_to_feather(
        db=local_db,
        exchange=exchange,
        pairs=pairs,
        timeframe=timeframe,
        timerange=timerange,
        trading_mode=trading_mode,
        base_dir=ft.userdir,
    )
    print("[FT ARGS]", strategy, pairs, timeframe, timerange, tmp_datadir)


    # Backtest (pointing datadir to temporary feather directory)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outname = f"bt_{strategy}_{timeframe}_{ts}.zip"
    result = ft.backtest(
        strategy=strategy,
        pairs=pairs,
        timeframe=timeframe,
        timerange=timerange,
        export="trades",
        export_filename=outname,     # Backtest output to userdir/backtest_results/outname
        # datadir=tmp_datadir,         # Use our temporary exported data
        # extra_args={
        #     "--data-format-ohlcv": "feather",
        #     "--trading-mode": trading_mode,
        # },
    )
    zip_path = result.get("export_file")

    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=400, detail=result["stdout"][:3000])
    run_id = etl_one_zip(zip_path)

    return {
        "ok": True,
        "run_id": run_id,
        "datadir": tmp_datadir,
        # "export_file": str(outpath),
        "summary": {
            "strategy": result.get("strategy") or strategy,
            "timeframe": timeframe,
            "pairs": pairs,
            "total_trades": (result.get("results", {}) or {}).get("total_trades"),
        }
    }

def import_backtest_auto(p: str) -> int:
    ext = os.path.splitext(p)[1].lower()
    if ext == ".zip":
        return etl_one_zip(p)
    elif ext == ".json":
        return etl_one_json(p)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported export file type: {ext}")