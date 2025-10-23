# app/api/v1/ping.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter()

@router.get("/raw")                 # 返回原始 dict（会被统一包装）
def raw():
    return {"hello": "world"}

@router.get("/jsonresponse")        # 手动 JSONResponse（也会被统一包装）
def j():
    return JSONResponse({"v": 1})

@router.get("/already")             # 已是统一结构（不会二次包装）
def already():
    return JSONResponse({"code": 0, "msg": "ok", "data": {"a": 1}})

@router.get("/text")                # 非 JSON（跳过包装）
def text():
    return PlainTextResponse("hi", status_code=202)

@router.get("/boom")                # 抛异常 → 异常处理器统一结构
def boom():
    raise HTTPException(status_code=404, detail="not found")
