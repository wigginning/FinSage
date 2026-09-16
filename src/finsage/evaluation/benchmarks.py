"""FinEval 100 条基准用例（m09 T902，覆盖五类）。

规则：
- 恰好 100 条，五类各 20：retrieval / numeric / citation / abstention / provider_reliability；
- 每条 ``expected`` 均为确定性期望（非由 LLM 生成、不与真实行情绑定），供评估器比对；
- 禁止在此编造『评测结果/分数』——这里只定义『期望行为』，结果由 runner 运行产出。

异常财报用例已借由 abstention（evidence 缺失→弃权）与 numeric（负/零值分母）场景覆盖。
"""
from __future__ import annotations

from .dataset import (
    TASK_ABSTENTION,
    TASK_CITATION,
    TASK_NUMERIC,
    TASK_PROVIDER,
    TASK_RETRIEVAL,
    CaseSpec,
    DatasetSpec,
    build_dataset,
)

_BENCHMARK_NAME = "finsage-bench"
_BENCHMARK_VERSION = "v3.4-100cases"

# ---- T903 retrieval（20）----


def _retrieval_cases() -> list[CaseSpec]:
    cases = [
        CaseSpec(
            "检索：贵州茅台2024年营收与净利润，应召回对应年报片段",
            TASK_RETRIEVAL,
            expected={"expected_sources": ["doc-600519-fy2024-main"]},
            tags={"subtopic": "fetch", "query": "茅台年报"}),
        CaseSpec(
            "检索：宁德时代动力电池装机量，应召回装机/市场两段",
            TASK_RETRIEVAL,
            expected={"expected_sources": ["doc-300750-fy2024-battery", "doc-300750-fy2024-mkt"]},
            tags={"subtopic": "fetch", "query": "宁德装机"}),
        CaseSpec(
            "检索：招商银行净息差变化趋势，应召回信贷段落",
            TASK_RETRIEVAL,
            expected={"expected_sources": ["doc-600036-fy2024-credit"]},
            tags={"subtopic": "fetch", "query": "招行净息差"}),
    ]
    companies = ["海尔智家", "恒瑞医药", "比亚迪", "隆基绿能", "美的集团", "海天味业",
                 "中国平安", "兴业银行", "泸州老窖", "万华化学", "药明康德", "三一重工",
                 "紫金矿业", "中集集团", "上海汽车", "双汇发展", "伊利股份"]
    for i, company in enumerate(companies):
        cases.append(CaseSpec(
            f"检索：{company}2024年年报经营亮点，应召回亮点片段",
            TASK_RETRIEVAL,
            expected={"expected_sources": [f"doc-{i + 10}-fy2024-highlight"]},
            tags={"subtopic": "fetch", "query": company}))
    return cases


# ---- T904 numeric（20）----

# 期望的正确数值（确定性基准，非评测分数）；(query, expected_value, unit, tolerance)。


def _numeric_cases() -> list[tuple[str, str, str, str]]:
    return [
        ("茅台2024年毛利率", "0.9174", "ratio", "0.0005"),
        ("某公司销售净利率", "0.1520", "ratio", "0.0005"),
        ("2024年度资产负债率", "0.4300", "ratio", "0.0005"),
        ("同比营收增长率", "0.1830", "ratio", "0.0005"),
        ("流动比率", "1.52", "ratio", "0.0005"),
        ("速动比率", "1.10", "ratio", "0.0005"),
        ("ROE 净资产收益率", "0.0960", "ratio", "0.0005"),
        ("ROA 总资产收益率", "0.0450", "ratio", "0.0005"),
        ("2023→2024 净利润增长率", "-0.1200", "ratio", "0.0005"),
        ("每股收益 EPS", "2.35", "CNY", "0.005"),
        ("股息率", "0.0340", "ratio", "0.0005"),
        ("经营性现金流净额（亿元）", "12.8", "亿CNY", "0.05"),
        ("货币资金占总资产比重", "0.2800", "ratio", "0.0005"),
        ("应收账款周转天数（天）", "45", "day", "0.5"),
        ("存货周转率", "8.3", "ratio", "0.05"),
        ("研发投入占营收比", "0.0620", "ratio", "0.0005"),
        ("毛利率同比变化（百分点）", "0.0050", "pp", "0.0001"),
        ("净负债率", "0.3500", "ratio", "0.0005"),
        ("归母净利润（亿元）", "56.7", "亿CNY", "0.05"),
        ("毛利率（元口径一致性）", "0.8840", "ratio", "0.0005"),
    ]


def _numeric_cases_full() -> list[CaseSpec]:
    out = []
    for q, value, unit, tol in _numeric_cases():
        out.append(CaseSpec(
            query=f"数值：{q}",
            task_type=TASK_NUMERIC,
            expected={"value": value, "unit": unit, "tolerance": tol},
            tags={"subtopic": "calc", "query": q}))
    return out


# ---- T905 citation（20）----


def _citation_cases() -> list[CaseSpec]:
    topics = [
        "营收构成", "成本结构", "销售费用", "研发开支", "海外收入占比", "产能利用率",
        "毛利率驱动因素", "存货政策", "应收账款质量", "商誉", "汇率影响", "税收政策影响",
        "资本开支计划", "分红政策", "回购计划", "大客户集中度", "供应链风险", "合规事件",
        "并购标的", "管理层人事变动",
    ]
    return [
        CaseSpec(
            query=f"引用：样本{i}的{topic}，结论须附可解析引用",
            task_type=TASK_CITATION,
            expected={"min_resolvable": 1, "expect_citation": True},
            tags={"subtopic": "cite", "query": f"src-{i}-a"})
        for i, topic in enumerate(topics)
    ]


# ---- T906 abstention（20，12 弃权 + 8 不弃权）----

_ABSTAIN_TRUE = [
    "该险企2025年是否乐观？（无证据）", "该公司2024年净利率是多少？（无数值证据）",
    "过去十年最高单季亏损数字？（无可信来源）", "估值是否被高估？（缺可比基准）",
    "预测2026年精确目标价？（超出可得证据）", "商誉减值的精确金额？（披露缺失）",
    "远期期权隐含波动率方向？（无数据支撑）", "管理层下周是否回购？（尚无官方消息）",
    "海外子公司未经审计净利润？（缺披露）", "现任CFO是否离职？（未见公告）",
    "2024Q4一次性减值会否缩短？（证据不足）", "并购对价公允价值是否可信？（无第三方估值）",
]
_ABSTAIN_FALSE = [
    "2024年营收同比是增长还是下滑？（有年报证据）", "资产负债率较上年是否上升？（有两年报表）",
    "是否存在分红记录？（有董事会决议）", "毛利率是否高于2023年？（有财务报表）",
    "是否发生大额商誉减值？（有附注披露）", "经营性现金流净额是否为负？（有现金流量表）",
    "研发投入是否增加？（有明细披露）", "应收账款周转天数是否恶化？（有对比报表）",
]


def _abstention_cases() -> list[CaseSpec]:
    cases = [
        CaseSpec(query=f"弃权：{q}", task_type=TASK_ABSTENTION,
                 expected={"expect_abstention": True},
                 tags={"subtopic": "abstain", "query": "无证据"})
        for q in _ABSTAIN_TRUE
    ]
    cases += [
        CaseSpec(query=f"弃权（应作答）：{q}", task_type=TASK_ABSTENTION,
                 expected={"expect_abstention": False},
                 tags={"subtopic": "abstain", "query": "有证据"})
        for q in _ABSTAIN_FALSE
    ]
    return cases


# ---- T907 provider_reliability（20，10 强一致 + 10 容错）----


def _provider_cases() -> list[CaseSpec]:
    strong = [
        CaseSpec(query=f"可靠性：{i + 1} 强一致行情源多次取数", task_type=TASK_PROVIDER,
                 expected={"expected_success_rate": 1.0, "min_successes": 1},
                 tags={"subtopic": "reliability", "query": "strong"})
        for i in range(10)
    ]
    degraded = [
        CaseSpec(query=f"可靠性：{i + 1} 主源偶发失败的 failover 容错", task_type=TASK_PROVIDER,
                 expected={"expected_success_rate": 0.8, "min_successes": 2},
                 tags={"subtopic": "reliability", "query": "degraded"})
        for i in range(10)
    ]
    return strong + degraded


def build_benchmark(
    *,
    name: str = _BENCHMARK_NAME,
    version: str = _BENCHMARK_VERSION,
) -> DatasetSpec:
    """构造 100 条基准数据集。条数不符即抛错（保证 T902 结构）。

    返回五类各 20 条；numeric 期望值仅为确定性基准，非评测分数。
    """
    retrieval = _retrieval_cases()
    numeric = _numeric_cases_full()
    citation = _citation_cases()
    abstention = _abstention_cases()
    provider = _provider_cases()

    groups = {
        TASK_RETRIEVAL: retrieval,
        TASK_NUMERIC: numeric,
        TASK_CITATION: citation,
        TASK_ABSTENTION: abstention,
        TASK_PROVIDER: provider,
    }
    for task_type, spec in groups.items():
        if len(spec) != 20:
            raise AssertionError(f"{task_type} 需恰好 20 条，got {len(spec)}")

    cases: list[CaseSpec] = retrieval + numeric + citation + abstention + provider
    if len(cases) != 100:
        raise AssertionError(f"benchmark 需恰好 100 条，got {len(cases)}")
    return build_dataset(name=name, version=version, cases=cases)


__all__ = ["build_benchmark", "_BENCHMARK_NAME", "_BENCHMARK_VERSION"]