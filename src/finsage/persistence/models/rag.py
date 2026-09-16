"""RAG 域模型：documents、document_chunks、evidence、claims、claim_evidence、calculations。

对应规格 §5.8–5.13。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from finsage.persistence.base import Base, DateTime3, IdMixin, TimestampMixin, utcnow


class Document(IdMixin, TimestampMixin, Base):
    """文档（§5.8）。"""

    __tablename__ = "documents"
    __table_args__ = (
        # P1：内容去重改为「租户内唯一」，跨租户上传相同内容互不冲突（原全局唯一导致 500）。
        UniqueConstraint("tenant_id", "sha256", name="uq_documents_tenant_sha256"),
        {"comment": "文档表"},
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        comment="租户ID（外键，索引）",
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="文档标题")
    filename: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="文件名（上传元数据，工程补全 ADR-0007）"
    )
    size: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="文件大小（字节，工程补全 ADR-0007）"
    )
    source_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="来源类型：upload/web/financial"
    )
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True, comment="来源 URI")
    sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="内容 SHA256（租户内唯一）"
    )
    company: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True, comment="关联公司"
    )
    ticker: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, comment="证券代码"
    )
    market: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True, comment="市场"
    )
    document_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, comment="文档类型"
    )
    report_period: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True, comment="报告期"
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime3, nullable=True, comment="发布时间（UTC）"
    )
    authority_tier: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, comment="权威层级（数值，越高越权威）"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="状态：ingested/failed/archived"
    )


class DocumentChunk(IdMixin, Base):
    """文档片段（§5.9）。"""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_idx"),
        {"comment": "文档片段表"},
    )

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属文档ID（外键，索引）",
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="片段序号")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="页码")
    section: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="章节标题")
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="片段文本 SHA256")
    text_length: Mapped[int] = mapped_column(Integer, nullable=False, comment="片段文本长度")
    milvus_pk: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, comment="Milvus 主键（预留）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )


class Evidence(IdMixin, Base):
    """证据（§5.10）。"""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_tenant_idx", "tenant_id"),
        {"comment": "证据表"},
    )

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="租户ID（索引）")
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        comment="来源文档ID（外键）",
    )
    chunk_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        comment="来源片段ID（外键）",
    )
    provider: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="数据来源 Provider"
    )
    relevance_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), nullable=False, comment="相关度得分"
    )
    authority_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), nullable=False, comment="权威度得分"
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime3, nullable=False, comment="检索时间（UTC）"
    )
    evidence_json: Mapped[Any] = mapped_column(JSON, nullable=False, comment="证据详情（JSON）")
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )


class Claim(IdMixin, Base):
    """论断（§5.11）。"""

    __tablename__ = "claims"
    __table_args__ = {"comment": "论断表"}

    research_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="研究运行ID（外键，索引）",
    )
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="论断类型")
    text: Mapped[str] = mapped_column(Text, nullable=False, comment="论断文本")
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, comment="置信度")
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, comment="是否通过校验（TINYINT(1)）"
    )
    verification_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="校验结论说明"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )


class ClaimEvidence(Base):
    """论断-证据关联（§5.12，复合主键）。"""

    __tablename__ = "claim_evidence"
    __table_args__ = (
        UniqueConstraint("claim_id", "evidence_id", name="uq_claim_evidence_pair"),
        {"comment": "论断与证据的关联表"},
    )

    claim_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("claims.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        comment="论断ID",
    )
    evidence_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("evidence.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        comment="证据ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )


class Calculation(IdMixin, Base):
    """计算记录（§5.13）。"""

    __tablename__ = "calculations"
    __table_args__ = {"comment": "计算记录表"}

    research_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="研究运行ID（外键，索引）",
    )
    formula: Mapped[str] = mapped_column(
        Text, nullable=False, comment="计算表达式（确定性代码生成）"
    )
    inputs_json: Mapped[Any] = mapped_column(JSON, nullable=False, comment="计算输入（JSON）")
    output_value: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, comment="计算输出数值"
    )
    output_unit: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="输出单位")
    output_currency: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="输出币种"
    )
    period: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="所属期间")
    source_evidence_ids_json: Mapped[Any] = mapped_column(
        JSON, nullable=False, comment="依据证据ID列表（JSON）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )
