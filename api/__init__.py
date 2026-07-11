# -*- coding: utf-8 -*-
"""FastAPI 后端包：竞价选股系统 实时 API 层。

与 EdgeOne 静态前端配合，构成「静态数据 + 实时 API」双模式：
- 静态数据 (data/*.json) 由本机/CI 的 Python 脚本每日 09:26 预生成，供前端秒开。
- 实时 API 经统一 DataService 拉取盘中行情/板块/资金流，前端每 15~30s 刷新。
"""
