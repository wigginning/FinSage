"""m05 确定性金融引擎的领域模型（T508，§4.5 / §22）。

- ``Calculation``：单次确定性计算的溯源对象（§4.5 冻结字段）。
- ``ComparisonResult``：``compare_periods`` 的单条结果（字段按用户 2026-08-24
  确认：metric / metric_a / metric_b / delta / delta_pct / period_a / period_b）。

这些是领域模型（pydantic BaseModel），与 m01 的持久化 ORM 模型（§5.13，
``finsage.persistence.models.rag.Calculation``）职责分离：这里承载计算溯源语义，
持久化模型负责入库。跨层不得混用（AGENTS.md §2 接口契约）。
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from finsage.observability.trace import uuid_str


class Calculation(BaseModel):
    """§4.5 Calculation —— 一次确定性计算的输入/公式/结果及其证据溯源。"""

    id: str = Field(default_factory=uuid_str, description="计算记录主键（UUID4）")
    formula: str = Field(description="计算表达式（确定性代码生成，非 LLM 生成）")
    inputs: dict[str, Decimal] = Field(description="计算输入（指标名 -> 数值）")
    output_value: Decimal = Field(description="计算输出数值")
    output_unit: str | None = Field(default=None, description="输出单位")
    output_currency: str | None = Field(default=None, description="输出币种")
    period: str | None = Field(default=None, description="所属期间")
    source_evidence_ids: list[str] = Field(
        default_factory=list, description="依据证据 ID 列表（溯源）"
    )


class ComparisonResult(BaseModel):
    """compare_periods 单条结果：同一指标在 period_a/b 两期的对比。"""

    metric: str = Field(description="指标名")
    metric_a: Decimal = Field(description="period_a 期数值")
    metric_b: Decimal = Field(description="period_b 期数值")
    delta: Decimal = Field(description="绝对差额 = metric_b - metric_a")
    delta_pct: Decimal = Field(description="相对变化（比率，0.25 表示 +25%）")
    period_a: str = Field(description="前一期标识")
    period_b: str = Field(description="后一期标识")