# FinSage 评估（FinEval）

> English: see [`benchmark.md`](benchmark.md)

本文档描述 FinEval 基准套件及其运行/上报方式。遵循 `AGENTS.md` 的诚实原则（§10 / §31.10）：**基准结果只能由配置好执行器的套件实际运行产出；伪造或自评数字被禁止。**

## 1. FinEval 提供什么

- **确定性数据集**——`finsage-bench` v3.4，恰好 **100 个用例**，均匀分布在五类任务上（每类 20 个）：
  - `retrieval`——期望的源文档应被召回；
  - `numeric`——财务算术结果与确定性期望一致（覆盖分母为负/为零的边界情形）；
  - `citation`——回答必须引用正确的证据；
  - `abstention`——证据缺失时必须弃答，而不是给出自信的猜测；
  - `provider_reliability`——围绕数据源/Provider 冲突与可靠性的期望行为。

  期望值全部是确定性的（绝不由 LLM 生成，也绝不绑定实时行情）。

- **评估器**（每类任务一个）与 **`BenchmarkRunner`**：用注入的执行器运行用例、聚合指标、可持久化结果。

- **可复现元数据**（`RunMetadata`）：`git_commit`（尽力获取，非 git 仓库时为 `"unknown"`）、`model_name`、`embedding_model`、`reranker_model` 与 `config`。

## 2. 打分机制

`BenchmarkRunner.run(spec)` 遍历每个用例，经注入的 `CaseExecutor` 取得确定性结果，用对应类型的评估器打分并聚合：

```text
overall: total / passed / pass_rate / avg_score
per_type: {retrieval, numeric, citation, abstention, provider_reliability} → 同一组指标
```

指标**仅从真实运行结果计算**——绝不编造、绝不由 LLM 汇总平均。

## 3. 运行基准

给基准真实打分需要一个接入生产工作流的 `CaseExecutor`（m06 各图 + 模型 + Provider Registry）。DB 持久化通过 `EvaluationStore` 可选。由于该执行器依赖已配置的模型/基础设施，**本仓库暂不声称任何生产基准数值。**

要新增运行入口，用 `build_benchmark()` 构建数据集并调用 runner：

```python
import asyncio
from finsage.evaluation.benchmarks import build_benchmark
from finsage.evaluation.runner import BenchmarkRunner

async def main():
    spec = build_benchmark()                 # finsage-bench, v3.4-100cases
    executor = ...                           # 生产 m06 工作流的适配器
    report = await BenchmarkRunner(executor).run(spec)
    print(report.metrics)

asyncio.run(main())
```

请记录报告的 `RunMetadata`（模型名、git commit、config），使结果可复现。

## 4. 诚实规则

- 只上报由真实执行器实际运行产出的数字。
- 确定性评估器未判通过的用例，绝不能标记为通过。
- 当某类任务的期望行为无法评估（未知 `task_type`）时跳过——不计数、不编造分数（No-Guess）。
- 任何公开数字都必须附上确切的数据集版本与 `RunMetadata`。

## 5. 框架自身的测试状态

基础设施由 `tests/evaluation/test_evaluation.py` 覆盖（确定性评估器 + runner 行为，使用合成的完美/失败执行器）。这些框架测试在 CI 中通过；它们验证的是机制本身，而非任何生产模型质量数字。
