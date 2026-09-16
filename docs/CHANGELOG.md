# FinSage Changelog

> 单人维护：每天一个短版本块，倒序追加。每条一行结论 + 证据锚点。
> 类型：`验证` / `修复` / `优化` / `迭代`。真相在 git 提交，本文件只做可读汇总。
> 说明：仓库为源码发布（无 git 历史/不track tag），锚点用日期 + 验证命令代替 commit hash。

---

## v0.2.2 (2026-08-29)

遗留收口（续 `leftover-implementation-plan-2026-08-28.md` 批次 5）：低风险、无需 ADR 的健壮性项。

### 修复

- **前端 401 登录闭环**：`lib/api/client.ts` 遇 401 清空失效 token、派发
  `finsage:unauthorized` 全局事件、`onUnauthorized` 回调；`app/providers.tsx` 监听做用户可见提示
  （无 `/login` 路由前先 console.warn 占位）。
- **结果页选择器订阅**：`app/research/[taskId]/page.tsx` 由整 store 订阅改为 `useShallow`，
  消除每个 SSE delta 触发的全页重渲染。
- **`__default__` 租户常量化**：`settings.default_tenant` 统一注入，`mysql_stores.py` 去掉硬编码字面量。
- **记忆 token 截断**：`settings.memory_history_limit` / `memory_token_budget`，在 20 条上限之上
  做 token 预算二次截断（粗估 ~2 字符/token）；InMemory / MySQL 两种实现均接入。

### 验证

后端 pytest **461 passed / 8 skipped** + ruff 全绿；前端 vitest **109 passed** + `tsc --noEmit` 无错。

---

## v0.2.1 (2026-08-28)

遗留未开发内容收敛（依据 `docs/SpecLog/leftover-implementation-plan-2026-08-28.md`；
新增 ADR-0017 / ADR-0018）。

### 修复

- **治理短路（ADR-0017）**：Due Diligence / Report 图补 V009/V010 —— 此前无 policy
  节点（V009 永不触发）、VERIFICATION FAIL 仍产出报告（V010 未落地）。新增 POLICY /
  ABSTAIN 节点与条件边；`verify()` 增加 `calculation_id` 悬空引用校验（伪造引用不得
  PASS）；`make_audit` 审计 sink 异常保护（写失败不拖垮主流程）；清理三处硬编码
  `confidence=0.9`（改走 §24 六因素）。
- **Provider 健壮性**：后处理段裸异常（AttributeError 等）统一映射
  `ProviderBadResponseError` 进入 failover 链（此前会打穿降级链）；tencent / sina /
  baostock 补 NaN/Infinity 防护；Baostock 全局会话 login/logout 串行化。
- **运行时健壮性**：`ChatRequest.message` / `ResearchRequest.query` 加
  `max_length=4000`、`market` 改枚举；checkpoint `ainvoke` 补 `thread_id`（ADR-0016
  持久化后端终于可续跑）。
- **前端 SSE**：重连上限 5 次 + 终态事件主动关流 + 404 错误对用户可见。

### 迭代

- **能力闭环（ADR-0018）**：估值引擎（DCF/增长外推）与情绪管线接入真实请求链路
  （此前仅测试可达的死代码）；多空分歧度 `disagreement` 与情绪聚合 `sentiment_summary`
  全链路下发（后端 result + SSE + 前端渲染，情绪标注"未校准"）。
- **测试修复**：`research-actions` 两条用例原生 `el.click()` 不触发 React 状态刷新
  （CI 无前端门禁故长期未暴露），改 `fireEvent` 后恢复。

### 验证

- 后端：`pytest tests/unit tests/integration` → **458 passed, 8 skipped**；`ruff` 全绿。
- 前端：`vitest` → **107 passed**（基线 102 passed + 2 failed）；`tsc --noEmit` 无错。
- 说明：本机 mypy 受 numpy stub 与 Python 3.12 环境限制无法全量（CI 在 3.11 全新环境
  运行）；对本次改动文件逐一 `mypy --follow-imports=skip` 无新增错误（6 处既有告警）。

---

## v0.2.0 (2026-08-26)

P0–P2 改进方案落地（依据 `docs/SpecLog/financial-agent-benchmark-2026-08-25.md`）。

### 迭代

- **P0 多空辩论（ADR-0009）**：Research QA 图新增 `debate` 节点，bull/bear 双视角 + 确定性
  仲裁（分歧度 = 证据集 Jaccard 距离），`ResearchAnswer` 加 `disagreement` 字段；对抗视角经
  `llm_adversarial` 槽位跨模型家族隔离；数值声明未挂来源降级而非硬拒绝。
- **P1 估值引擎（ADR-0010）**：`financial/valuation.py` 新增 DCF（WACC/增长率 + 5×5 敏感性网格）、
  同业倍数对比、增长率外推，全程 `decimal.Decimal`，配 `Calculation` 溯源。
- **P1 情绪管线（ADR-0011）**：`finsage/sentiment.py` 规则法关键词情绪打分，`calibrated=False`
  （待实测校准）+ 固定低置信，不冒充高置信。
- **P2 结构化输出（ADR-0012）**：`LLMProvider` 加 `complete_typed`（schema 绑定 Pydantic 输出），
  辩论节点弃用手工 `json.loads`。
- **P2 CI gate（ADR-0013）**：新增 `.github/workflows/ci.yml`（ruff + mypy + pytest 单测门禁）。

### 验证

- 后端单测：`pytest tests/unit --deselect tests/unit/test_settings.py::test_defaults_contain_no_secret`
  → **259 passed, 1 deselected**（deselect 为本地 `.env` 覆盖导致的既有失败，CI 无 `.env` 不受影响）。

---

## v0.1.1 (2026-08-24)

C-8 真实数据跑分 + §24/§21 校准。

### 已验证

- **extra 模型用途审计**：`bert-base-chinese` / `nlp_bert_document-segmentation_chinese-base`
  仅存在于 `resources/models/`，`src/` 无引用 → 确认未使用（chunker 纯规则切分），已在
  `docs/SpecLog/tasks/index.md` 模型资源策略标注（C-9 结论）。
- **LLM 连通性**：`scripts/probe_llm.py` 对 5 个测试模型连通：qwen3.7-plus-2026-05-26 /
  qwen3.7-plus / qwen3.7-max-2026-06-08 / glm-5.2 均 OK；qwen3.7-max-2026-05-17 端点返回
  FIN-2004（该快照不可用，非缺陷）。默认 `FIN_LLM_MODEL=qwen3.7-plus` 正常走真实
  `OpenAICompatibleLLMProvider`。
- **Provider 真实连通冒烟**：`scripts/smoke_tencent.py` 真实拉取 平安银行(000001) 11.41 CNY
  （Tencent 公开行情，health=healthy）；`scripts/smoke_sina.py` 真实拉取 平安银行(000001) 11.41 CNY
  （Sina 公开行情，health=healthy，与 Tencent 交叉一致）；`probe_stack.py` 显示 akshare/tencent healthy、
  baostock/ashare/yfinance down（SDK 未装 / 端点不可达 / 官方限流，非代码缺陷）。
- **C-8 FinEval 真实跑分**：`scripts/run_fineval_real.py` 接线真实 research_qa + 真实 Registry +
  真实 LLM 执行基准可离线子集（12 abstention + 20 provider_reliability）→ **32/32 全过，pass_rate=1.0**。

### 已迭代

- **§24 阈值校准**：代码档位与冻结规格一致（HIGH≥0.85 / MEDIUM 0.65 / LOW 0.45 / ABSTAIN<0.45）；
  真实跑分在弃权档边界获得强证据 —— 12/12 无证据用例（置信度 <0.45）在真实 LLM 下被正确判为
  ABSTAIN（§23 V008），档位边界无须调整。
- **§21 权重**：语义 dense 0.7/sparse 0.3、数值 0.4/0.6 需真实检索召回才能校准，但当前 Milvus
  无种子语料（`finsage_chunks` 不存在）→ 按 No-Guess 保留冻结初始值，待建集灌语料后再做检索权重跑分。
- **provider_reliability**：真实 Tencent 行情连续取数 3/3 成功率 1.0，强一致 + 容错用例全过。
- **多源接入（C-10）**：新增 `SinaQuoteProvider`（新浪财经公开行情，无 SDK/token），注册进
  `build_registry` 作为 CN quote 交叉校验候选；真实连通 11.41 与 Tencent 交叉一致，
  契约测试 6 项；全量 235 passed/6 skipped，ruff 全绿。
- **反爬 / 合规**：真实连通仅单次低频少量请求；`TencentQuoteProvider`/`SinaQuoteProvider` 显式带
  Referer+User-Agent、不批量抓取、不绕过访问控制、不在公开源伪造来源掩身份，生产高并发走预留
  付费源（`TushareProvider`，opt-in 需 `FIN_TUSHARE_TOKEN`）。

---

## v0.1.0 (2026-08-23)

首个可发布基线（m00–m11 全量实现完成，Release test 通过）。

### 验证

- 后端全量单测/集成测试：`pytest` → **209 passed, 6 skipped**（6 项 MySQL 集成因未配置 `FIN_DB_URL` 跳过，为已知配置边界，非缺陷）。
- 静态检查：`ruff check src tests` → 全绿。
- 前端：`next build`（9 路由）`typecheck` `vitest`（63 passed）全绿；Playwright E2E F001–F010 通过。
- Docker：API 服务镜像 `docker/api/Dockerfile` **构建成功（BUILD_EXIT=0，含 CUDA 运行时 ~2.7GB）**；六容器统一 `finsage-` 前缀；`init_db` 成功 + m01 6 项 MySQL 集成对真实 MySQL 全绿。
- DoD 复核：无 secret 入库（`.gitignore` 忽略 `.env` 仅留 `.env.example`）；无捏造 benchmark 指标（`docs/benchmark.md` 如实声明未发布生产数字）。

### 修复

- **mcp 依赖锁定 `>=1.2,<2`**：`pip install -e.[dev]` 曾把 `mcp` 拉到 2.0（新架构移除 `mcp.server.fastmcp`，破坏 m04/MCP 层与测试收集），回装 `mcp 1.29.0` 恢复验收时 FastMCP 契约。见 `pyproject.toml`。

### 优化

- **Docker 依赖国内镜像加速**：`docker/api/Dockerfile` 设置 `PIP_INDEX_URL=pypi.tuna.tsinghua.edu.cn` + 阿里云 extra index，避免拉依赖超时；并启用 BuildKit `--mount=type=cache,target=/root/.cache/pip` 复用 pip 缓存，跨构建不重复下载。
- 已确认保持 CUDA 版 torch（`FlagEmbedding`→`torch` 默认），镜像偏大但支持 GPU 推理，非本轮收口范围，仅记录备查。

### 迭代

- m00–m11 全部模块验收完成（详见 `docs/SpecLog/tasks/index.md` §4 进度追踪与各 m* 模块文档）。
- Docker 容器级一键实跑需本机 Docker Desktop，本机未执行，已在 m11 release 文档如实标注（No-Guess 边界）。

---

## 历史规划

- 未来所有验证 / 优化 / 修复 / 迭代在此文件顶部追加新的版本块（倒序）。
- 示例锚点：`2026-08-24 | 修复 | 闸断 X 竞态（证据：pytest tests/... -x 全绿）`