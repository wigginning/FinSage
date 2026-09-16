"""East Money 反爬补丁（opt-in，默认关闭）。

背景：东方财富（push2.eastmoney.com / push2his.eastmoney.com）自某版本起强制要求
反爬 NID 授权令牌（``nid18`` cookie）。akshare / efinance 的默认请求不带该令牌，
服务器会直接断开连接（``RemoteDisconnected: Remote end closed connection without
response``），导致这两个东财源在部分网络下不可用。

本模块参考 daily_stock_analysis 的 ``eastmoney_patch`` 实现，但**默认关闭**，仅当
显式开启 ``FIN_ENABLE_EASTMONEY_PATCH=true`` 时才生效。

⚠️ 合规边界（重要）：
本补丁通过伪造浏览器指纹（canvas/webgl/font/audio key、随机屏幕分辨率）、随机
User-Agent 掩盖身份、并获取东财授权令牌来**规避东财的反爬访问控制**。这与本仓库
``sina.py`` / ``tencent.py`` 声明的「不绕过任何访问控制、不发送伪造来源掩盖身份」
边界相冲突。因此：
- 默认关闭，绝不默认启用；
- 启用即视为使用者明确接受该合规风险；
- 生产环境请优先评估东财官方数据服务或付费源（如 Tushare）的合规替代方案。

实现说明：
- 全局替换 ``requests.Session.request``，仅对东财域名生效，其它请求原样透传；
- 幂等：重复调用只打一次补丁；
- NID 令牌带 TTL 缓存，避免频繁请求授权接口。
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import secrets
import threading
import time
import uuid
from typing import Any

import requests

logger = logging.getLogger(__name__)

# 仅对东财域名打补丁，其它请求原样透传。
_EASTMONEY_DOMAINS = (
    "fund.eastmoney.com",
    "push2.eastmoney.com",
    "push2his.eastmoney.com",
)

# 兜底 UA 池（fake_useragent 首次使用需联网下载，失败时回退到静态池）。
_FALLBACK_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

_original_request = requests.Session.request
_patch_lock = threading.Lock()
_patched = False

# NID 令牌缓存：{data, expire_at}
_nid_cache: dict[str, Any] = {"data": None, "expire_at": 0.0}
_NID_TTL = 20.0
_NID_FAIL_TTL = 5 * 60.0  # 授权接口失败时冷却，避免频繁重试


def _random_ua() -> str:
    """返回随机 UA；fake_useragent 不可用时回退到静态池。"""
    try:
        from fake_useragent import UserAgent  # noqa: PLC0415 - 延迟 import

        return UserAgent().random
    except Exception:  # noqa: BLE001 - 联网失败回退静态池
        return random.choice(_FALLBACK_UA)


def _generate_st_nvi() -> str:
    """生成东财授权接口所需的 st_nvi 值（参考 daily_stock_analysis 实现）。"""
    charset = "useandom-26T198340PX75pxJACKVERYMINDBUSHWOLF_GQZbfghjklqvwyzrict"
    random_str = "".join(secrets.choice(charset) for _ in range(21))
    hash_prefix = hashlib.sha256(random_str.encode("utf-8")).hexdigest()[:4]
    return random_str + hash_prefix


def _get_nid(user_agent: str) -> str | None:
    """从东财授权接口获取 NID 令牌；带 TTL 缓存，失败返回 None。"""
    now = time.time()
    if _nid_cache["data"] and now < _nid_cache["expire_at"]:
        return _nid_cache["data"]
    with _patch_lock:
        try:
            url = "https://anonflow2.eastmoney.com/backend/api/webreport"
            payload = json.dumps(
                {
                    "osPlatform": "Windows",
                    "sourceType": "WEB",
                    "osversion": "Windows 10.0",
                    "language": "zh-CN",
                    "timezone": "Asia/Shanghai",
                    "webDeviceInfo": {
                        "screenResolution": random.choice(
                            ["1920X1080", "2560X1440", "3840X2160"]
                        ),
                        "userAgent": user_agent,
                        "canvasKey": hashlib.md5(str(uuid.uuid4()).encode()).hexdigest(),
                        "webglKey": hashlib.md5(str(uuid.uuid4()).encode()).hexdigest(),
                        "fontKey": hashlib.md5(str(uuid.uuid4()).encode()).hexdigest(),
                        "audioKey": hashlib.md5(str(uuid.uuid4()).encode()).hexdigest(),
                    },
                }
            )
            headers = {"Cookie": f"st_nvi={_generate_st_nvi()}", "Content-Type": "application/json"}
            resp = requests.request("POST", url, headers=headers, data=payload, timeout=30)
            resp.raise_for_status()
            nid = resp.json()["data"]["nid"]
            _nid_cache["data"] = nid
            _nid_cache["expire_at"] = now + _NID_TTL
            return nid
        except Exception as exc:  # noqa: BLE001 - 授权失败按冷却处理
            logger.warning(
                "eastmoney_nid_fetch_failed",
                extra={"extra": {"error": type(exc).__name__}},
            )
            _nid_cache["data"] = None
            _nid_cache["expire_at"] = now + _NID_FAIL_TTL
            return None


def apply_eastmoney_patch() -> bool:
    """应用东财反爬补丁（幂等）。返回是否本次实际应用。"""
    global _patched
    with _patch_lock:
        if _patched:
            return False

        def _patched_request(self: Any, method: str, url: str, **kwargs: Any) -> Any:
            if not any(d in (url or "") for d in _EASTMONEY_DOMAINS):
                return _original_request(self, method, url, **kwargs)
            user_agent = _random_ua()
            headers = dict(kwargs.get("headers") or {})
            headers["User-Agent"] = user_agent
            nid = _get_nid(user_agent)
            if nid:
                headers["Cookie"] = f"nid18={nid}"
            kwargs["headers"] = headers
            time.sleep(random.uniform(1, 4))  # 随机休眠降频，降低被封风险
            return _original_request(self, method, url, **kwargs)

        requests.Session.request = _patched_request  # type: ignore[assignment, method-assign]
        _patched = True
        logger.warning(
            "eastmoney_patch_applied",
            extra={"extra": {"note": "opt-in anti-bot bypass; risk accepted by operator"}},
        )
        return True


def is_patched() -> bool:
    """返回补丁是否已应用。"""
    return _patched


__all__ = ["apply_eastmoney_patch", "is_patched"]
