"""FinEval 评估器（m09 T903–T907）。

每个 evaluator 对一条 ``CaseSpec`` + 该任务的确定性 ``result`` 输出
``EvalOutcome``（passed / score(0..1) / details）。全部为确定性逻辑：
指标仅由实际结果计算，绝不编造（AGENTS.md §10/§31.10）。

result 契约（由各 evaluator 文档化，禁止猜测）：
- retrieval            : 可取 ``SearchResult`` / dict，其中含可提取的 hits/source ids
- numeric              : dict {answer: number, unit?: str}，对照 expected.value/tolerance/unit
- citation             : dict {citations: [{source_id?...}], 或直接 [source_id]}
- abstention           : dict {abstained: bool, confidence_bucket?: str, score?: number}
- provider_reliability : dict {attempts, successes, success_rate}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from .dataset import (
    TASK_ABSTENTION,
    TASK_CITATION,
    TASK_DECISION,
    TASK_NUMERIC,
    TASK_PROVIDER,
    TASK_RETRIEVAL,
    CaseSpec,
)


@dataclass
class EvalOutcome:
    """单条用例的评估结果（确定性）。"""

    task_type: str
    passed: bool
    score: float
    details: dict[str, Any] = field(default_factory=dict)


class Evaluator(Protocol):
    """评估器契约。"""

    task_type: str

    def evaluate(self, case: CaseSpec, result: Any) -> EvalOutcome: ...


# ---- 工具 ----

def _hits_of(result: Any) -> list[str]:
    """从检索结果中提取已命中文档/片段 id 列表（尽量宽容但不猜测）。"""
    if result is None:
        return []
    if isinstance(result, dict):
        raw = result.get("hits") or result.get("hit_ids") or result.get("sources") or []
    else:
        raw = list(getattr(result, "hits", None) or [])
    ids: list[str] = []
    for item in raw:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            for k in ("pk", "chunk_id", "document_id", "id", "source_id"):
                if item.get(k):
                    ids.append(str(item[k]))
                    break
        else:
            for k in ("pk", "chunk_id", "document_id", "id", "source_id"):
                if getattr(item, k, None):
                    ids.append(str(getattr(item, k)))
                    break
    return ids


def _citations_of(result: Any) -> list[str]:
    """提取结果里的引用目标 id 列表。"""
    if result is None:
        return []
    if isinstance(result, dict):
        raw = result.get("citations") or result.get("sources") or []
    else:
        raw = list(getattr(result, "citations", None) or [])
    ids: list[str] = []
    for item in raw:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            for k in ("source_id", "chunk_id", "document_id", "id", "pk"):
                if item.get(k):
                    ids.append(str(item[k]))
                    break
        elif item is not None:
            for k in ("source_id", "chunk_id", "document_id", "id", "pk"):
                if getattr(item, k, None):
                    ids.append(str(getattr(item, k)))
                    break
    return ids


def _as_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _ratio(hit: int, total: int) -> float:
    return 0.0 if total <= 0 else round(hit / total, 4)


# ---- T903 retrieval ----

# 检索期望：expected.expected_sources = [doc_id, ...]；缺省要求全部召回。
_RETRIEVAL_DEFAULT_MIN_RECALL = 1.0


class RetrievalEvaluator:
    task_type = TASK_RETRIEVAL

    def evaluate(self, case: CaseSpec, result: Any) -> EvalOutcome:
        expected = case.expected or {}
        targets = set(expected.get("expected_sources") or [])
        if not targets:
            return EvalOutcome(self.task_type, False, 0.0, {"reason": "missing expected_sources"})
        min_recall = float(expected.get("min_recall", _RETRIEVAL_DEFAULT_MIN_RECALL))
        hit_ids = set(_hits_of(result))
        matched = targets & hit_ids
        recall = _ratio(len(matched), len(targets))
        passed = recall >= min_recall
        return EvalOutcome(
            self.task_type,
            passed,
            recall,
            {"matched": sorted(matched), "expected": len(targets), "recall": recall},
        )


# ---- T904 numeric ----

# 数值期望：expected.value / tolerance / unit；缺省容差与十进制比较同一字符串解析。
_NUMERIC_DEFAULT_TOLERANCE = "1e-6"


class NumericEvaluator:
    task_type = TASK_NUMERIC

    def evaluate(self, case: CaseSpec, result: Any) -> EvalOutcome:
        expected = case.expected or {}
        expected_value = _as_decimal(expected.get("value"))
        if expected_value is None:
            return EvalOutcome(self.task_type, False, 0.0, {"reason": "missing expected.value"})
        produced = _answer_value(result)
        produced_decimal = _as_decimal(produced)
        if produced_decimal is None:
            return EvalOutcome(
                self.task_type, False, 0.0, {"reason": "result has no numeric answer"}
            )
        tolerance = Decimal(str(expected.get("tolerance", _NUMERIC_DEFAULT_TOLERANCE)))
        diff = abs(produced_decimal - expected_value)
        correct = diff <= tolerance
        unit_ok = self._unit_ok(case, result)
        passed = correct and unit_ok
        return EvalOutcome(
            self.task_type,
            passed,
            1.0 if correct else 0.0,
            {"expected": str(expected_value), "produced": str(produced_decimal), "diff": str(diff),
             "unit_ok": unit_ok},
        )

    @staticmethod
    def _unit_ok(case: CaseSpec, result: Any) -> bool:
        exp_unit = (case.expected or {}).get("unit")
        if not exp_unit:
            return True  # 未声明单位不做校验
        produced_unit = None
        if isinstance(result, dict):
            produced_unit = result.get("unit")
        return str(produced_unit) == str(exp_unit)


def _answer_value(result: Any) -> Any:
    if isinstance(result, dict):
        for k in ("answer", "value", "result", "score"):
            if k in result and result[k] is not None:
                return result[k]
    return getattr(result, "answer", None)


# ---- T905 citation ----

# 引用期望：expected.min_resolvable（缺省 1）；expected.expect_citation 可选。
_CITATION_DEFAULT_MIN = 1


class CitationEvaluator:
    task_type = TASK_CITATION

    def evaluate(self, case: CaseSpec, result: Any) -> EvalOutcome:
        expected = case.expected or {}
        citations = _citations_of(result)
        # 可解析性：引用须能落到有效 SourceRef（result.valid_sources 提供合法 source id 集合）。
        valid_ids = self._valid_sources(result)
        resolvable = [cid for cid in citations if cid in valid_ids]
        min_resolvable = int(expected.get("min_resolvable", _CITATION_DEFAULT_MIN))
        total = len(citations)
        ratio = _ratio(len(resolvable), total)
        passed = ratio >= 1.0 and len(resolvable) >= min_resolvable
        if expected.get("expect_citation", True) and total == 0:
            passed = False
            ratio = 0.0
        return EvalOutcome(
            self.task_type,
            passed,
            ratio,
            {"citations": len(citations), "resolvable": len(resolvable), "ratio": ratio},
        )

    @staticmethod
    def _valid_sources(result: Any) -> set[str]:
        if result is None:
            return set()
        if isinstance(result, dict):
            raw = result.get("valid_sources") or result.get("sources_registry") or []
        else:
            raw = list(getattr(result, "valid_sources", None) or [])
        return {str(s) for s in raw}


# ---- T906 abstention ----

# 弃权期望：expected.expect_abstention(bool)。判定一致性。
class AbstentionEvaluator:
    task_type = TASK_ABSTENTION

    def evaluate(self, case: CaseSpec, result: Any) -> EvalOutcome:
        expected = case.expected or {}
        expect = bool(expected.get("expect_abstention", False))
        abstained = self._abstained(result)
        passed = abstained == expect
        return EvalOutcome(
            self.task_type,
            passed,
            1.0 if passed else 0.0,
            {"expect_abstention": expect, "abstained": abstained},
        )

    @staticmethod
    def _abstained(result: Any) -> bool:
        if result is None:
            return False
        if isinstance(result, dict):
            if "abstained" in result:
                return bool(result["abstained"])
            bucket = result.get("confidence_bucket")
            if bucket:
                return bucket == "ABSTAIN"
            sc = result.get("score")
            if isinstance(sc, (int, float)):
                return float(sc) < 0.45  # §24 ABSTAIN 档
        else:
            bucket = getattr(result, "confidence_bucket", None)
            if bucket:
                return bucket == "ABSTAIN"
            sc = getattr(result, "score", None)
            if isinstance(sc, (int, float)):
                return float(sc) < 0.45
        return False


# ---- T907 provider_reliability ----

# Provider 可靠性期望：expected.expected_success_rate / min_successes；
# result：{attempts, successes} 或 {success_rate}。
_PROVIDER_MIN_SUCCESSES = 1
_PROVIDER_DEFAULT_RATE = 1.0


class ProviderReliabilityEvaluator:
    task_type = TASK_PROVIDER

    def evaluate(self, case: CaseSpec, result: Any) -> EvalOutcome:
        expected = case.expected or {}
        if not isinstance(result, dict):
            return EvalOutcome(self.task_type, False, 0.0, {"reason": "result is not a dict"})
        attempts = int(result.get("attempts") or 0)
        successes = int(result.get("successes") or 0)
        rate = float(result.get("success_rate", _ratio(successes, attempts)))
        if attempts > 0:
            # 与实际计数一致，避免 success_rate 与 successes/attempts 矛盾。
            rate = _ratio(successes, attempts)
        min_successes = int(expected.get("min_successes", _PROVIDER_MIN_SUCCESSES))
        exp_rate = float(expected.get("expected_success_rate", _PROVIDER_DEFAULT_RATE))
        passed = successes >= min_successes and rate >= exp_rate
        return EvalOutcome(
            self.task_type,
            passed,
            rate,
            {"attempts": attempts, "successes": successes, "success_rate": rate,
             "expected_success_rate": exp_rate},
        )


# ---- T908 decision（ADR-0015 决策级：分歧标注 + 决策一致性）----

# 高分歧阈值：disagreement >= 该值视为高分歧，不得给出单边自信结论。
_DECISION_DIVERGENCE_THRESHOLD = 0.5


class DecisionEvaluator:
    task_type = TASK_DECISION

    def evaluate(self, case: CaseSpec, result: Any) -> EvalOutcome:
        disagreement = self._disagreement(result)
        if disagreement is None:
            return EvalOutcome(
                self.task_type, False, 0.0, {"reason": "missing disagreement annotation"}
            )
        if not (0.0 <= disagreement <= 1.0):
            return EvalOutcome(
                self.task_type, False, 0.0, {"reason": "disagreement out of [0,1]"}
            )
        verdict = self._verdict(result)
        consistent = self._consistent(disagreement, verdict)
        return EvalOutcome(
            self.task_type,
            consistent,
            1.0 if consistent else 0.0,
            {"disagreement": disagreement, "verdict": verdict, "consistent": consistent},
        )

    @staticmethod
    def _disagreement(result: Any) -> float | None:
        if result is None:
            return None
        if isinstance(result, dict):
            raw = result.get("disagreement")
        else:
            raw = getattr(result, "disagreement", None)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        return float(raw)

    @staticmethod
    def _verdict(result: Any) -> str | None:
        if result is None:
            return None
        if isinstance(result, dict):
            return result.get("verdict")
        return getattr(result, "verdict", None)

    @classmethod
    def _consistent(cls, disagreement: float, verdict: str | None) -> bool:
        # 高分歧不得给出单边自信结论（bull/bear）；低分歧任意结论均可。
        if disagreement >= _DECISION_DIVERGENCE_THRESHOLD:
            return verdict == "balanced"
        return True


# ---- 注册表 ----

_EVALUATORS: dict[str, Evaluator] = {
    TASK_RETRIEVAL: RetrievalEvaluator(),
    TASK_NUMERIC: NumericEvaluator(),
    TASK_CITATION: CitationEvaluator(),
    TASK_ABSTENTION: AbstentionEvaluator(),
    TASK_PROVIDER: ProviderReliabilityEvaluator(),
    TASK_DECISION: DecisionEvaluator(),
}


def get_evaluator(task_type: str) -> Evaluator | None:
    """按 task_type 取评估器；未知返回 None（runner 跳过并不计数）。"""
    return _EVALUATORS.get(task_type)


def available_evaluators() -> dict[str, Evaluator]:
    return dict(_EVALUATORS)


__all__ = [
    "EvalOutcome",
    "Evaluator",
    "RetrievalEvaluator",
    "NumericEvaluator",
    "CitationEvaluator",
    "AbstentionEvaluator",
    "ProviderReliabilityEvaluator",
    "DecisionEvaluator",
    "get_evaluator",
    "available_evaluators",
]