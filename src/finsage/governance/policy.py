"""确定性 Policy Gate（§16.5 / §23 V009 —— m06 内联落地）。

检查三类政策边界：
- Investment Advice Boundary：不得给出"买入/卖出/应该投资"等投资建议；
- Tool Permission：仅允许策略允许的工具（默认全放行，仅面向预留）；
- Prompt Injection Risk：拦截"忽略系统指令/你是/覆盖"等注入模式。

全部为确定性规则，不调用 LLM（AGENTS.md §3）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from finsage.models.entities import Entity

from .models import PolicyVerdict

# 投资建议边界关键词（命中即 block）。
_ADVICE_PATTERN = re.compile(
    r"(建议|应该|推荐).{0,12}(买|卖|买入|卖出|加仓|清仓|投资)|"
    r"(买入|卖出|加仓|清仓|抄底|追高)\s*(吧|!)?$",
    re.IGNORECASE,
)

# Prompt Injection 危险模式。
_INJECTION_PATTERNS = re.compile(
    r"(忽略|无视)\s*(之前|上文|系统)?(指令|提示|规则|约束)|"
    r"(你(现在)?是|假装你是|扮演)|"
    r"reveal\s+(system|prompt|instructions)",
    re.IGNORECASE,
)

# 检索/文档内容注入模式（更宽：外部文档是不可信输入，AGENTS.md §7）。
# 覆盖"忽略上文/忽略系统提示/你是AI助手/输出指令/覆盖规则"等常见注入面。
_CONTENT_INJECTION_PATTERNS = re.compile(
    r"(忽略|无视|不要理会)\s*(之前|上文|以上|系统|规则|指令|提示|约束)|"
    r"(从现在起|接下来|此后)\s*(你|请|必须)|"
    r"覆盖\s*(系统|之前的)?(指令|规则|提示)|"
    r"(你(现在)?是|假装你是|扮演|当作)\s*(\w|AI|GPT|助手|机器人)|"
    r"(system\s*prompt|ignore\s+previous|ignore\s+instructions|developer\s+message)",
    re.IGNORECASE,
)


@dataclass
class PolicyGate:
    """只读政策检查器（无内部状态，可复用）。"""

    allowed_tools: frozenset[str] = frozenset(
        {"rag", "financial_mcp", "calculator", "search", "knowledge"}
    )
    _warnings: list[str] = field(default_factory=list, init=False, repr=False)

    def _reset(self) -> None:
        self._warnings = []

    def assess(self, *, query: str, entities: list[Entity], tools: list[str]) -> PolicyVerdict:
        """判定政策门。返回 allow / block / abstain 并附 warning。"""
        self._reset()
        # 1. 投资建议边界
        if _ADVICE_PATTERN.search(query):
            self._warnings.append("query_contains_investment_advice")
            return PolicyVerdict(status="block", warnings=list(self._warnings))
        # 2. Tool 权限
        denied = [t for t in tools if t not in self.allowed_tools]
        if denied:
            self._warnings.append(f"tool_not_allowed:{','.join(denied)}")
            return PolicyVerdict(status="block", warnings=list(self._warnings))
        # 3. Prompt Injection
        if _INJECTION_PATTERNS.search(query):
            self._warnings.append("prompt_injection_detected")
            return PolicyVerdict(status="block", warnings=list(self._warnings))
        # 4. 无可解析实体 -> 证据不足，转 abstain（交由上层决定是否放弃）。
        if not entities:
            self._warnings.append("no_entities_found")
        return PolicyVerdict(status="allow", warnings=list(self._warnings))


def sanitize_retrieved_content(texts: list[str]) -> tuple[list[str], list[str]]:
    """检测并清理检索/文档内容中的 Prompt Injection（P1 —— 不可信输入防御）。

    外部文档/网页是不可信输入（AGENTS.md §7）：命中注入模式的片段不进入 LLM
    提示，改为返回该片段为"已拦截注入内容"的占位，并把命中信息作为 warning 上报，
    供上层审计。绝不把检索内容当作系统指令（§7：不允许检索内容覆盖系统指令）。

    返回 ``(safe_texts, warnings)``：
    - ``safe_texts``：与输入等长，注入片段替换为占位说明；
    - ``warnings``：每条注入片段的命中描述（含索引）。
    """
    safe: list[str] = []
    warnings: list[str] = []
    for i, text in enumerate(texts):
        if _CONTENT_INJECTION_PATTERNS.search(text or ""):
            safe.append(f"[注入内容已拦截，未纳入分析；来源片段 {i}]")
            warnings.append(f"retrieved_injection_blocked:{i}")
        else:
            safe.append(text)
    return safe, warnings


__all__ = ["PolicyGate", "sanitize_retrieved_content"]