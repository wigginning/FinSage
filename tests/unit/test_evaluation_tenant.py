"""ADR-0022：评估域 ``tenant_id`` 列契约（纯元数据校验，不依赖 DB / MySQL）。

评估三表 ``tenant_id``：**NOT NULL** + 索引 + 外键到 ``tenants.id``。

演进史：ADR-0019 §5 先加列（`0005`，列暂可空，兼容仅脚本离线跑的场景）；
ADR-0022 FinEval API 落地后运行必有 HTTP 身份可解析租户，故 `0006` 迁移把列
收紧为 NOT NULL——写入强制归属租户，读取强制按租户隔离。
"""
from __future__ import annotations

from finsage.persistence.models.evaluation import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationRun,
)

_MODELS = (EvaluationDataset, EvaluationCase, EvaluationRun)


def test_evaluation_models_expose_tenant_id():
    for model in _MODELS:
        assert "tenant_id" in model.__table__.columns, model.__name__


def test_evaluation_tenant_id_is_not_null():
    """ADR-0022 强制隔离：列不可空，杜绝无租户归属的评估数据。"""
    for model in _MODELS:
        col = model.__table__.columns["tenant_id"]
        assert col.nullable is False, model.__name__


def test_evaluation_tenant_id_references_tenants():
    for model in _MODELS:
        col = model.__table__.columns["tenant_id"]
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert targets == {"tenants.id"}, (model.__name__, targets)


def test_evaluation_tenant_id_is_indexed():
    """索引用于按租户过滤（ADR-0022 读路径隔离）。"""
    for model in _MODELS:
        col = model.__table__.columns["tenant_id"]
        assert col.index is True, model.__name__
