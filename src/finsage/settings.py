"""应用配置加载层。

基于 pydantic-settings 从环境变量 / .env 读取配置；键均带 FIN_ 前缀。
所有路径一律以项目根为基准的相对路径（禁止写死绝对路径）。

模型资源策略（见 tasks/index.md 全局规则）：
  1. 加载优先取本地预下载目录 model_local_dir（只读，不得修改/覆盖）；
  2. 本地缺失/损坏时在线下载到可配置缓存目录 model_cache_dir，成功缓存复用；
  3. 冻结技术栈模型（BGE-M3 / BGE-Reranker-v2-m3）不得更替。
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# src/finsage/settings.py -> 项目根（三层：finsage/ -> src/ -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """FinSage 全局配置。环境变量前缀 FIN_，读取 .env（不强制存在）。"""

    model_config = SettingsConfigDict(
        env_prefix="FIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 字段名以 model_ 开头（如 model_local_dir / model_cache_dir），
        # 属业务语义而非 pydantic 受保护命名空间，故关闭默认保护以消除告警。
        protected_namespaces=(),
    )

    # ---- 应用 ----
    app_name: str = "finsage"
    app_env: str = "dev"  # dev / test / prod
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # ---- 请求头（透传给 request_id / trace_id）----
    request_id_header: str = "X-Request-Id"
    trace_id_header: str = "X-Trace-Id"

    # ---- 持久化（FROZEN: MySQL 8 + Redis）----
    db_url: str = "mysql+pymysql://finsage:CHANGE_ME@localhost:13306/finsage?charset=utf8mb4"
    redis_url: str = "redis://localhost:6579/0"

    # ---- Milvus（FROZEN）----
    milvus_host: str = "localhost"
    milvus_port: int = 19730

    # ---- 模型资源策略 ----
    # 本地预下载目录：只读，实现不得修改/覆盖；加载优先取本地。
    model_local_dir: str = "resources/models"
    # 在线兜底下载缓存目录（相对项目根，可覆盖）。
    model_cache_dir: str = "data/models-cache"

    # ---- 可选：外部服务（留空则禁用对应 Provider）----
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    # LLM 模型名（OpenAI 兼容端点）；仅在 llm_api_key/llm_base_url 就绪时生效。
    llm_model: str = ""
    # LLM 请求超时（秒）。研究 QA 图内多次 LLM 调用，长叙事生成可能 >30s。
    llm_timeout: float = 90.0
    # 对抗视角 LLM（ADR-0009/0014 跨模型家族隔离）：独立模型家族凭据，留空则不注册
    # adversarial provider，辩论节点回退 default。
    llm_adversarial_api_key: str | None = None
    llm_adversarial_base_url: str | None = None
    llm_adversarial_model: str = ""
    # CORS 允许来源（前后端分离，浏览器→API 跨域）。逗号分隔；默认本地前端。
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3200",
        "http://127.0.0.1:3200",
    ]

    # ---- API（m08 §7）----
    # Bearer token 鉴权（§7/§8 FIN-1002）。留空 = 开发环境关闭鉴权；
    # 生产环境务必通过环境变量 FIN_API_TOKEN 注入强随机值。
    api_token: str = ""

    # 签名身份令牌密钥（P0 认证升级）：用于签发/校验携带 user_id/tenant_id 的
    # 身份令牌（见 api.identity_token）。留空则不启用身份令牌，接口走匿名放行
    # （与 api_token 兼容；生产环境务必经 FIN_IDENTITY_TOKEN_SECRET 注入强随机值）。
    identity_token_secret: str = ""
    # 身份令牌有效期（秒），默认 1 小时。
    identity_token_ttl: int = 3600

    # 是否启用真实 m06 工作流执行器（替代 DevRunner 冒烟替身）。
    # 默认 False（仍走 DevRunner）；置 True 经 FIN_ENABLE_REAL_RUNNER 注入
    # RealWorkflowRunner，真实执行 LangGraph（检索/财务依赖需另行装配，见 P2）。
    enable_real_runner: bool = False

    # 是否启用 Milvus 混合检索（接入 WorkflowDeps.retrieve）。
    # 默认 False（真实执行器仍走诚实空检索）；置 True 经 FIN_ENABLE_RETRIEVAL 注入
    # Milvus 检索适配器（需 finsage_chunks 已灌语料，否则调用时诚实抛 RetrievalError）。
    enable_retrieval: bool = False

    # 是否启用财务 Provider 真实接入（接入 WorkflowDeps.financial）。
    # 默认 False；置 True 经 FIN_ENABLE_FINANCIAL 注入 build_registry() 适配器
    # （需 Provider SDK/token 就绪，否则调用时诚实抛 Provider 错误）。
    enable_financial: bool = False

    # ---- 财务数据源凭据（留空则对应 Provider 降为低优先/不可用）----
    # Tushare 需注册 token（http://tushare.pro）。未配置时 TushareProvider 在
    # Registry 中保持低优先（priority=90），仅 token 就绪才参与 failover。
    tushare_token: str | None = None

    # 是否启用东财反爬补丁（opt-in，默认关闭）。
    # 东方财富强制反爬后，akshare/efinance 默认请求会被断开；开启本开关会通过
    # 伪造浏览器指纹 + 获取 NID 令牌来规避东财反爬（见 eastmoney_patch 合规说明）。
    # 默认 False；置 True 经 FIN_ENABLE_EASTMONEY_PATCH 注入，视为使用者接受合规风险。
    enable_eastmoney_patch: bool = False

    # 是否启用 MySQL 持久化仓储（替换内存 Store）。
    # 生产环境（app_env=prod）默认 True：任务/文档/证据/审计必须落库，重启不丢
    # （系统审计 P0：默认内存态导致数据重启即失）。开发/测试默认 False（内存 Store，
    # 便于本地跑通）。置 True 经 FIN_ENABLE_PERSISTENCE 显式覆盖；需先
    # `alembic upgrade head` 并保证 FIN_DB_URL 可达。
    enable_persistence: bool | None = None

    # LangGraph checkpoint 后端（ADR-0016）：memory / mysql / redis。
    # 默认 memory（InMemorySaver，重启丢失）；置 mysql/redis 需安装对应
    # langgraph-checkpoint-* 可选包并保证连接可达。
    checkpoint_backend: str = "memory"

    # 单租户/无租户场景的占位租户名（曾硬编码为 "__default__"，现统一从此处读取，
    # 便于部署时按环境覆盖，避免散落字面量）。
    default_tenant: str = "__default__"

    # 会话记忆上下文窗口（§2.4 Memory 接线）：
    # - 单次注入助手的历史消息条数上限，防无限增长；
    # - 在条数上限之内再做 token 预算截断（粗估 ~2 字符/token），超预算时丢弃最旧消息。
    # - 溢出部分可压缩为一条 system 摘要（ADR-0023，第三层），默认关闭。
    memory_history_limit: int = 20
    memory_token_budget: int = 6000

    # 溢出摘要（ADR-0023）：开启后 token 预算外的旧消息压缩为一条 system 摘要而非丢弃。
    # 默认关闭 —— 需额外 LLM 调用（延迟 + 成本），且不改变既有部署行为；
    # 摘要器缺失/失败一律回退"丢弃最旧"，绝不用模板伪造摘要（AGENTS.md §10）。
    memory_summary_enabled: bool = False
    # 摘要长度上限（字符）；摘要本身也计入 token 预算，保证注入总量受控。
    memory_summary_max_chars: int = 800

    # ---- 估值假设（ADR-0018：分析师假设必须显式配置，引擎绝不臆造）----
    # DCF 的 WACC 与永续增长率是分析师假设，不是可从财报推导的确定量
    # （AGENTS.md §10）。未配置时估值接线**跳过 DCF** 并记 warning，
    # 不使用任何"行业惯例默认值"——那等于编造假设。
    valuation_wacc: Decimal | None = None
    valuation_terminal_growth: Decimal | None = None

    # 增长率外推期数（ADR-0018）。增长率本身取自历史真实增速，非假设。
    valuation_projection_periods: int = 3

    # ---- 限流（ADR-0020）----
    # 固定窗口计数（复用 FinRedis.rate_limit_add）；关闭时所有端点直接放行（等同现状）。
    rate_limit_enabled: bool = True
    # Redis 不可用时的降级策略（ADR-0020 §3）：False = fail-open（放行 + warning，保可用性）；
    # True = fail-closed（按 FIN-1005 拒绝，保护后端资源，建议多租户生产启用）。
    rate_limit_fail_closed: bool = False
    # 按路由覆盖默认限额：{"/api/v1/research": {"limit": 30, "window_seconds": 60}}。
    # 未配置的路由用代码内置默认值（见 api/ratelimit.py::_DEFAULT_LIMITS）。
    rate_limit_routes: dict[str, dict] = {}

    # ---- 派生属性 ----
    @property
    def model_local_path(self) -> Path:
        """本地预下载模型根目录（只读资源）。"""
        return _resolve_project(self.model_local_dir)

    @property
    def model_cache_path(self) -> Path:
        """在线兜底下载缓存目录；缺失时可按需创建（不属于预下载只读目录）。"""
        return _resolve_project(self.model_cache_dir)

    @property
    def persistence_enabled(self) -> bool:
        """解析后的持久化开关：显式配置优先；否则生产默认开、其余默认关。"""
        if self.enable_persistence is not None:
            return self.enable_persistence
        return self.app_env == "prod"


def _resolve_project(raw: str) -> Path:
    """将相对项目根的路径解析为绝对路径；已绝对则原样返回。"""
    p = Path(raw)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


@lru_cache
def get_settings() -> Settings:
    """进程级单例配置，避免重复解析 .env。"""
    return Settings()
