# FinSage V3.4 — 完整验收方案（Acceptance Plan）

> 目标：将规格 §36 Final Acceptance Checklist 与各模块 DoD 转为**可执行的总验收清单**——每项给命令 + 预期 + 判定，逐条核销。
> 原则（AGENTS.md §10 / ADR-0005）：只把"跑过并拿到结果"的判定标为已证；未执行的标为待执行，禁止冒充结论。首个版本基线日期：2026-08-23。
>
> 名词约定：
> - **[已证]** 有实际输出/通过记录（附日期与命令）。
> - **[待执行]** 未跑或需在目标环境复验，逐项在发布前核销。

---

## 1. 前置环境

| 项 | 版本/说明 | 判定 |
|---|---|---|
| Python | 3.11+（镜像用 3.11-slim） | `python --version` |
| Node | 18/20（Next.js） | `node --version` |
| MySql / Redis / Milvus | 经 Docker Compose（`finsage-` 前缀）启动 | 见 §7 |
| Docker Desktop | 本机容器实跑依赖 | 需确认启动 |
| 环境变量 | 复制 `.env.example` → `.env.local`（无 secret） | 见 §8 |

---

## 2. 后端测试（quality gate）

命令（项目根）：

```bash
pytest -q                       # 全量单测 + 非 MySQL 集成
pytest tests/integration/test_mysql.py   # MySQL 集成（需 FIN_DB_URL）
ruff check src tests            # lint
```

判定：`pytest` 全绿，MySQL 集成仅因未设 `FIN_DB_URL` 跳过为可接受边界；`ruff` 无 error（迁移生成文件 E501 已按 per-file 豁免）。

**[已证 2026-08-23]** `pytest` 209 passed / 6 skipped；`ruff check src tests` 全绿（基线，来自 m11/T1108）。
**[待执行]** 在干净环境复跑并记录。

---

## 3. 前端验证（apps/web）

```bash
cd apps/web
npm ci
npm run typecheck        # TS 类型
npm run vitest run       # 组件单测
npm run build            # next build（9 路由）
npx playwright test      # E2E F001–F010
```

判定：typecheck 0 error；vitest 全绿；build 成功无打包错误；E2E 10 项全绿。

**[已证 2026-08-23]** `next build` 9 路由 / typecheck / vitest 63 passed / E2E 10 passed（基线，m10/m11）。
**[待执行]** 目标环境完整复跑。

---

## 4. 分层验收（对应规格 §36）

> 每类已按模块落地，勾选以最近核销为准。

### 4.1 数据层
- [ ] MySQL schema frozen and migrated —— 实现=m01 T101/T102（19 表，Alembic）；判定=`alembic upgrade head` 成功 + 6 项集成测全绿。**[已证 2026-08-23 集成 6 全绿]** **[待执行 干净迁移复跑]**
- [ ] Milvus schema frozen and initialized —— 实现=m02 T202（§6 集合）；判定=单元/集成检索测通过。**[已证 检索单测 12]** **[待执行 Milvus 实例实跑]**

### 4.2 领域模型 / 契约
- [ ] Pydantic models complete —— 实现=m00（src/finsage/models）。判定=导入无错、契约测试过。
- [ ] API OpenAPI contract complete —— 实现=m08（routes/errors）。判定=OpenAPI 生成 + 13 项集成测。**[已证 13 项]**
- [ ] FinancialDataProvider contract + 全部 Provider —— 实现=m03（§9）；判定=Contract Tests + 23 项 provider 测。**[已证]**
- [ ] Error codes complete —— 实现=m08（FIN-1001~6001）。**[已证 错误契约不透传]**

### 4.3 前端路由 / 状态 / SSE / 组件
- [ ] Route + TS models + state machine + SSE client —— 实现=m10 T1003–T1007。判定=typecheck + 组件测。
- [ ] Evidence / Calculation / Citation / Trace components —— m10 T1008–T1012。**[已证 组件测]**
- [ ] Frontend unit/component/E2E green —— **[已证 见 §3]**

### 4.4 工作流与引擎
- [ ] MCP schemas complete —— m04 T401–T403（Financial/Knowledge/Search）。**[已证 19 项集成]**
- [ ] ResearchState frozen + 四张 LangGraph workflows —— m06 T601–T609。判定=四图 happy/退化路径测。**[已证 152 passed]**
- [ ] Deterministic Financial Engine —— m05 T501–T509（§22）。**[已证 38 项]**
- [ ] Evidence/Claim/Calculation linked —— m02 T212 / m03 T312 / m06。**[已证]**
- [ ] Verification + Audit pipelines —— m07 T701–T709（V001–V008 / PersistentAuditWriter）。**[已证 24 项]**
- [ ] SSE tested —— m08 T805（§26.9 信封）。**[已证 13 项含迟到订阅]**

### 4.5 评估
- [ ] FinEval runner works —— m09 T908（BenchmarkRunner 落 execution_runs）。**[已证 tests/evaluation 20 项]**
- [ ] No fabricated benchmark metrics —— docs/benchmark.md 如实声明未发布生产数字。**[已证]**

---

## 5. 全局放行条件（§36 尾）

| # | 条件 | 判定 | 状态 |
|---|---|---|---|
| 1 | MySQL schema frozen and migrated | §4.1 | [ ] |
| 2 | Milvus schema frozen and initialized | §4.1 | [ ] |
| 3 | Pydantic models complete | §4.2 | [ ] |
| 4 | API OpenAPI contract complete | §4.2 | [ ] |
| 5 | Frontend route contract complete | §4.3 | [ ] |
| 6 | Frontend TS models complete | §4.3 | [ ] |
| 7 | Frontend state machine complete | §4.3 | [ ] |
| 8 | SSE event client complete | §4.3 | [ ] |
| 9 | Evidence/Calculation/Citation/Trace components | §4.3 | [ ] |
| 10 | Frontend unit tests green | §3 | [ ] |
| 11 | Frontend component tests green | §3 | [ ] |
| 12 | Frontend E2E tests green | §3 | [ ] |
| 13 | Error codes complete | §4.2 | [ ] |
| 14 | FinancialDataProvider contract complete | §4.2 | [ ] |
| 15 | All required providers implemented | §4.2 | [ ] |
| 16 | Provider Contract Tests green | §4.2 | [ ] |
| 17 | MCP schemas complete | §4.4 | [ ] |
| 18 | ResearchState frozen | §4.4 | [ ] |
| 19 | LangGraph nodes implemented | §4.4 | [ ] |
| 20 | All four workflows tested | §4.4 | [ ] |
| 21 | Deterministic Financial Engine tested | §4.4 | [ ] |
| 22 | Evidence/Claim/Calculation linked | §4.4 | [ ] |
| 23 | Verification pipeline tested | §4.4 | [ ] |
| 24 | Audit pipeline tested | §4.4 | [ ] |
| 25 | SSE tested | §4.4 | [ ] |
| 26 | FinEval runner works | §4.5 | [ ] |
| 27 | No fabricated benchmark metrics | §4.5 | [ ] |
| 28 | Docker Compose works from clean checkout | §7 | [ ] |
| 29 | README quickstart works | §6 | [ ] |
| 30 | AGENTS.md present | 根路径文件 | [ ] |
| 31 | No secrets committed | §8 | [ ] |
| 32 | Full test suite green | §2/§3 | [ ] |

---

## 6. 文档与快速开始

- [ ] README + README.zh-CN（双语 quickstart）—— m11 T1101/T1102。**[已证 存在]**
- [ ] Architecture docs + ADR 索引 —— m11 T1103；`docs/architecture.md` + `docs/adr/index.md`（0001–0005）。**[已证 存在]**
- [ ] Security docs —— m11 T1105；`docs/security.md`（§26.16/§31.7）。**[已证 存在]**
- [ ] Benchmark docs（无捏造）—— m11 T1104；`docs/benchmark.md`。**[已证]**

---

## 7. Docker 验收（关键边界）

命令：

```bash
docker compose config        # 校验编排语法
docker compose --profile app build   # 构建 API 镜像
docker compose up -d         # 启动 mysql/redis/milvus/etcd/minio/app
docker compose run --rm app alembic upgrade head   # init_db
# 复跑 6 项 MySQL 集成 + app 冒烟
```

判定：
- `docker compose config` 通过（六容器 `finsage-` 前缀合法）；
- app 镜像构建成功；
- `up -d` 全部容器 healthy；
- init_db（migrate）成功；
- 6 项 MySQL 集成对真实库全绿；
- app 服务可访问（healthcheck）。

**验收状态（据实标注，2026-08-23）：**
- **[已证]** 编译校验 `docker compose config` 通过（基线 m00）。
- **[已证]** app 镜像**构建成功（BUILD_EXIT=0，含 CUDA 运行时 ~2.7GB）**——本次会话实际执行，`docker/api/Dockerfile`。
- **[未证/待执行]** `docker compose up -d` 干净启动 + 容器内 init_db + MySQL 集成 + app 冒烟：**需本机 Docker Desktop 已启且镜像/依赖资源齐备**，当前未实跑容器，标注为待执行，不冒充已跑结论。

---

## 8. 安全验收

- `.env` / `.env.local` 不入库，仓库仅 `.env.example`（占位无 secret）—— **[已证 m11 T1108]**
- 模型资源 `resources/models/` 只读、不烧录入镜像，缺失走在线兜底（ADR-0004）—— **[已证 策略确认]**
- `audit_events` 不存 secret（PersistentAuditWriter 过滤）—— **[已证 m07]**
- Secret 数据从不写入代码/日志/审计——强制约束，发布前 grep 复核。

---

## 9. 如何执行本次验收

建议按顺序：

1. 启动 Docker Desktop；
2. `docker compose --profile app build && docker compose up -d`；
3. 跑 §7 init_db + 6 项 MySQL 集成，确认干净检出可启动；——把 §7 [未证] 翻转为 [已证]；
4. 复跑 §2/§3 全部命令，逐条勾选 §5 放行表；
5. 全部绿后，把结果追加到 `docs/CHANGELOG.md` 新版本块。