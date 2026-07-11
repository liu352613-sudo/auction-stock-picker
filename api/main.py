# -*- coding: utf-8 -*-
"""FastAPI 应用入口。

启动:
    cd <项目根>
    python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

能力:
- 7 个核心 API（/api/market, /recommend, /history, /backtest, /hot-sector, /stock/{code}, /config）
- 预留扩展接口（/api/strategies, /analysis/{code}, /signals/push, /trade）
- 同源托管前端静态资源（index.html / assets / data），单进程即可开发联调
- CORS 已开启，便于 EdgeOne 静态站跨域调用独立部署的 API
"""
import os

import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import loaders
from api.routers import core, extensions

ROOT = loaders.ROOT


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

app = FastAPI(
    title="竞价选股系统 API",
    description="静态数据 + 实时 API 双模式后端。所有行情经 DataService 统一封装。",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(core.router)
app.include_router(extensions.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "auction-stock-picker-api", "time": _now()}


@app.get("/")
def root():
    return {"message": "竞价选股系统 API。访问 /docs 查看接口文档，访问 /index.html 查看前端。"}


# 静态资源托管（API 路由之后注册，优先匹配 /api/*）
_STATIC_DIR = ROOT
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
