"""Workflow 可靠性（T607 checkpoint 注入 / T608 retry·timeout）。

分层说明：
- ``retry`` 的职责在 m03（Provider Failover/CircuitBreaker/sdk 重试）已承担；
  本模块提供**节点/工作流级**确定性重试与超时，作为最后防线（§28.4）。
- ``timeout`` 仅对 async 节点生效（``asyncio.timeout`` 无法中断同步阻塞代码），
  文档明确；超时后写入 ``error_code=FIN-5002``（WORKFLOW_TIMEOUT），决策交给路由。
- ``checkpoint`` 由调用方以 ``BaseCheckpointSaver`` 注入（默认 ``InMemorySaver``），
  实现 LangGraph 持久化、断点续跑（§15 / T607）。

重试语义：仅对 ``retryable=True`` 的 FinSageError（§8.1 Retry 列）进行有界重试，
其它异常一律原样抛出，不吞错、不无限重试。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import cast

from finsage.exceptions import ErrorCode, FinSageError
from finsage.observability.logger import get_logger
from finsage.workflows.nodes import AsyncNodeFn, NodeFn, SyncNodeFn

logger = get_logger(__name__)

# §8.1 Retry=yes 的错误码（工作流级默认可重试集合，与 exceptions 的 retry 标志一致）。
_DEFAULT_RETRYABLE: frozenset[str] = frozenset(
    {
        ErrorCode.PROVIDER_TIMEOUT.value,
        ErrorCode.PROVIDER_UNAVAILABLE.value,
        ErrorCode.PROVIDER_RATE_LIMITED.value,
        ErrorCode.PROVIDER_BAD_RESPONSE.value,
        ErrorCode.MARKET_DATA_UNAVAILABLE.value,
        ErrorCode.RETRIEVAL_FAILED.value,
        ErrorCode.RERANK_FAILED.value,
        ErrorCode.WORKFLOW_TIMEOUT.value,
    }
)


@dataclass
class RetryPolicy:
    """确定性重试策略（T608）。"""

    max_attempts: int = 3
    base_delay: float = 0.0  # 秒；单测传 0 避免拖慢
    retryable_codes: frozenset[str] = field(default_factory=lambda: _DEFAULT_RETRYABLE)


def _is_retryable(exc: BaseException, codes: frozenset[str]) -> bool:
    """是否命中可重试错误码（FinSageError 才有 code，其它异常不重试）。"""
    code = getattr(exc, "code", None)
    return isinstance(exc, FinSageError) and code is not None and code.value in codes


async def _await_node(node: NodeFn, state: dict) -> dict:
    """兼容调用 sync / async 节点并等待其结果。

    以 ``isinstance(res, dict)`` 而非 ``asyncio.iscoroutine`` 判别：
    - 类型检查器能据此把 ``dict | Awaitable[dict]`` 收敛回 ``dict``；
    - 顺带修正边界行为——返回**非协程** awaitable（Future/Task 等）的节点，
      旧写法会把该 awaitable 原样当结果返回，下游按 dict 使用即出错。
    """
    res = node(state)
    if isinstance(res, dict):
        return res
    return await res


def with_retry(node: NodeFn, policy: RetryPolicy | None = None) -> NodeFn:
    """包裹节点为有界确定性重试（仅对 retryable 的 FinSageError）。

    保持节点同步/异步形态：sync 节点返回同步包装，async 节点返回协程包装；
    其余异常原样抛出，不影响决策语义。
    用法：``graph.add_node("retrieval", with_retry(make_retrieval(deps)))``。
    """
    policy = policy or RetryPolicy()

    # iscoroutinefunction 是 NodeFn 联合的运行时判别式，类型检查器无法据此收窄
    # 可调用对象的 async 形态；故在判别点做一次 cast，避免包装体内散落 ignore。
    if asyncio.iscoroutinefunction(node):
        async_node = cast(AsyncNodeFn, node)

        async def _async_wrap(state: dict) -> dict:
            attempt = 0
            while True:
                attempt += 1
                try:
                    return await async_node(state)
                except FinSageError as exc:
                    if attempt >= policy.max_attempts or not _is_retryable(
                        exc, policy.retryable_codes
                    ):
                        raise
                    logger.warning(
                        "node.retry",
                        extra={"extra": {"attempt": attempt, "code": exc.code.value}},
                    )
                    if policy.base_delay:
                        await asyncio.sleep(policy.base_delay)

        return _async_wrap

    sync_node = cast(SyncNodeFn, node)

    def _sync_wrap(state: dict) -> dict:
        attempt = 0
        while True:
            attempt += 1
            try:
                return sync_node(state)
            except FinSageError as exc:
                if attempt >= policy.max_attempts or not _is_retryable(exc, policy.retryable_codes):
                    raise
                logger.warning(
                    "node.retry",
                    extra={"extra": {"attempt": attempt, "code": exc.code.value}},
                )
                if policy.base_delay:
                    time.sleep(policy.base_delay)

    return _sync_wrap


def with_timeout(node: NodeFn, timeout_s: float) -> NodeFn:
    """包裹 async 节点为超时受控（T608）。

    - ``timeout_s <= 0`` 表示不启用超时（原样透传）；
    - 仅 async 节点可被中断；触发超时后返回 ``{"error_code": "FIN-5002"}``，
      由 graph 路由丢弃作答/弃权，不外抛。
    """
    if timeout_s is None or timeout_s <= 0:
        return node

    async def _wrap(state: dict) -> dict:
        try:
            async with asyncio.timeout(timeout_s):
                return await _await_node(node, state)
        except TimeoutError:
            logger.warning("node.timeout", extra={"extra": {"timeout_s": timeout_s}})
            return {"error_code": ErrorCode.WORKFLOW_TIMEOUT.value}

    return _wrap


def state_aware_retry(node: NodeFn, policy: RetryPolicy | None = None) -> NodeFn:
    """状态感知重试：对节点返回的 ``error_code`` 为可重试码的也进行有界重试。

    现有 ``with_retry`` 仅对**抛出的** FinSageError 重试；但检索/财务节点按契约
    吞异常并把错误码写入 state（``{"error_code": "FIN-20xx"}``），导致重试永不触发
    （系统审计 P1：重试机制失效）。本包装在两次调用之间检查返回值中的 error_code，
    命中可重试码且未超次数则重新调用节点；其它情况原样返回，保持决策语义。
    """
    policy = policy or RetryPolicy()

    # 同 with_retry：在运行时判别点做一次形态收敛。
    if asyncio.iscoroutinefunction(node):

        async def _async_wrap(state: dict) -> dict:
            attempt = 0
            while True:
                attempt += 1
                result = await _await_node(node, state)
                code = result.get("error_code") if isinstance(result, dict) else None
                if (
                    code is None
                    or attempt >= policy.max_attempts
                    or code not in policy.retryable_codes
                ):
                    return result
                logger.warning(
                    "node.state_retry",
                    extra={"extra": {"attempt": attempt, "code": code}},
                )
                if policy.base_delay:
                    await asyncio.sleep(policy.base_delay)

        return _async_wrap

    sync_node = cast(SyncNodeFn, node)

    def _sync_wrap(state: dict) -> dict:
        attempt = 0
        while True:
            attempt += 1
            result = sync_node(state)
            code = result.get("error_code") if isinstance(result, dict) else None
            if code is None or attempt >= policy.max_attempts or code not in policy.retryable_codes:
                return result
            logger.warning(
                "node.state_retry",
                extra={"extra": {"attempt": attempt, "code": code}},
            )
            if policy.base_delay:
                time.sleep(policy.base_delay)

    return _sync_wrap


__all__ = ["RetryPolicy", "with_retry", "with_timeout", "state_aware_retry", "_DEFAULT_RETRYABLE"]