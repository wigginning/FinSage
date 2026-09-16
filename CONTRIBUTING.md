# 贡献指南（CONTRIBUTING）

感谢你考虑为 FinSage 贡献代码。本指南帮助你快速、合规地参与贡献。

## 目录

- [开发环境](#开发环境)
- [仓库约定](#仓库约定)
- [如何提出变更](#如何提出变更)
- [编码规范](#编码规范)
- [测试要求](#测试要求)
- [提交信息规范](#提交信息规范)
- [许可证](#许可证)

## 开发环境

1. **前置条件**：Python ≥ 3.11、Node.js ≥ 18、Docker + Docker Compose。
2. **中间件**：`cp .env.example .env`（按需填充），然后 `docker compose up -d`。
3. **安装依赖**（后端）：

   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate ; Linux/macOS: source .venv/bin/activate
   pip install -e ".[dev]"
   ```

4. **初始化数据库**：`python scripts/init_db.py`

   **注意**：`resources/models/` 中的模型为只读，禁止修改/覆盖或提交。

## 仓库约定

- 不允许改动**冻结架构**，除非有显式架构决策记录（ADR）并经评审。
- 未经批准不得替换 Milvus / MySQL / Redis / LangGraph / MCP / BGE-M3 / BGE-Reranker-v2-m3。
- 不得引入第二个 ORM、向量数据库、工作流引擎或工具协议（AGENTS.md §1）。
- 金融数字必须由**确定性代码**计算，不得交由 LLM 执行权威运算（AGENTS.md §3）。
- 密钥/凭据永不入库（AGENTS.md §7）。

## 如何提出变更

1. 从最新的 `master` 检出新分支：`git checkout -b feat/<描述>`。
2. 变更尽可能**小且聚焦**，避免无关重构。
3. 关联对应 Issue，并在描述中引用相关规格章节编号（如有）。
4. 提交 PR，并在描述中说明**改了什么、为何改**，以及测试命令。

## 编码规范

- **后端**：`ruff` 与 `mypy` 必须零告警通过：

  ```bash
  ruff check src tests migrations
  mypy src
  ```

- **前端**：类型与 lint 通过：

  ```bash
  cd apps/web
  npm run typecheck
  npm run lint
  ```

- 日志与审计埋点遵循既有规范（异步中间件、SSE 事件名、`mask_value` 脱敏等）。

## 测试要求

- 每个实现包含测试（AGENTS.md §8）。
- Provider 必须通过 Contract Tests；LangGraph 工作流必须有 happy-path 与 failure-path 测试。
- **不得以失败测试合并**。提交前运行：

  ```bash
  pytest                      # 后端单元 + 评估
  cd apps/web && npm test     # 前端单元/组件
  cd apps/web && npx playwright test  # 前端 E2E
  ```

## 提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/) 风格，建议配合本仓库的提交钩子与 `git-commit` 技能：

```
feat(api): 新增 XXX 端点
fix(web): 修复 404 降级
docs(spec): 更新 m08 任务
```

## 许可证

本仓库以 **Apache-2.0** 发布。贡献即表示你同意你的贡献按 Apache-2.0 授权（见 [`LICENSE`](LICENSE)）。如有疑问，请先与维护者沟通。