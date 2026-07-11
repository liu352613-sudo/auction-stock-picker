# -*- coding: utf-8 -*-
"""预留扩展接口：AI 分析 / 多策略引擎 / 消息推送 / 实盘交易。

这些端点当前返回「已预留」结构化响应，便于前端提前对接、后端后续实现，
不影响现有功能。整体架构保持模块化，新增能力只需在此包内追加路由。
"""
import datetime
from typing import Optional

from fastapi import APIRouter, Body

from api import loaders

router = APIRouter()


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _reserved(feature: str, hint: str, extra: Optional[dict] = None):
    base = {
        "status": "reserved",
        "feature": feature,
        "message": hint,
        "available": False,
        "updated_at": _now(),
    }
    if extra:
        base.update(extra)
    return base


@router.get("/api/strategies")
def api_strategies():
    """多策略引擎：列出已注册策略。当前仅有竞价默认策略，预留扩展。"""
    return {
        "status": "ok",
        "active": "auction_default",
        "strategies": [
            {"id": "auction_default", "name": "竞价强势选股",
             "desc": "集合竞价量比/开盘涨幅/动能评分", "enabled": True},
        ],
        "note": "多策略引擎接口已预留，后续可注册自定义策略并路由权重。",
        "updated_at": _now(),
    }


@router.get("/api/analysis/{code}")
def api_analysis(code: str):
    """AI 分析接口（预留）：个股智能解读、风险提示、舆情摘要。"""
    return _reserved(
        "ai_analysis",
        "AI 分析接口已预留，待接入大语言模型/量化研究服务后启用。",
        {"code": code.zfill(6), "suggested_provider": "LLM / Quant Research Service"},
    )


@router.post("/api/signals/push")
def api_signals_push(payload: dict = Body(default={})):
    """消息推送接口（预留）：将推荐/预警推送到微信/邮件/Webhook。"""
    return _reserved(
        "message_push",
        "消息推送接口已预留，待接入推送网关（企业微信/邮件/Webhook）后启用。",
        {"received": payload},
    )


@router.post("/api/trade")
def api_trade(payload: dict = Body(default={})):
    """实盘交易接口（预留）：下单/撤单，需券商账户与风控授权。"""
    return _reserved(
        "live_trading",
        "实盘交易接口已预留，待接入券商 API 与实盘风控后启用（高风险，默认关闭）。",
        {"received": payload, "paper_trading_supported": True},
    )
