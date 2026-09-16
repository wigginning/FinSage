import json
import os
from datetime import UTC, datetime

project_path = r"d:\Weijn\Codes\Github\FinSage\finsage-ui"
now = datetime.now(UTC)
timestamp_ms = int(now.timestamp() * 1000)
iso_now = now.isoformat()

context_files = [
    "shared-runtime/runtime-boundaries/lane-runtime-contracts.md",
    "shared-runtime/agent-dispatch-runtime/lane-dispatch-index.md",
    "shared-runtime/agent-dispatch-runtime/shared-page-rendering-kernel.md",
    "delivery-quality/page-rendering-quality-gate.md",
    "delivery-quality/design-artifact-validation.md",
    "delivery-quality/delivery-evidence-contract.md",
    "visual-experience/visual-experience-guidelines.md",
    "visual-experience/visual-checkpoint-protocol.md",
    "intent-workflows/intent-project-complex-build/INTENT_WORKFLOW.md",
    "intent-workflows/intent-project-complex-build/start-complex-project-build.md",
    "intent-workflows/intent-project-complex-build/00-requirement-and-style-intake.md",
    "intent-workflows/intent-project-complex-build/complex-page-runtime.md",
    "intent-workflows/intent-project-complex-build/complex-page-dispatch-contract.md",
    "intent-workflows/intent-project-complex-build/orchestration-summary-fields.md",
    "shared-runtime/design-artifact-formats/design-project-file-format.md",
]

pages = [
    {
        "nodeId": "page-index",
        "title": "研究工作台",
        "htmlSrc": "pages/index.html",
        "pageIndex": 1,
        "visualNorthStar": (
            "研究工作台：左侧边栏导航 + 顶部搜索，中央大输入框与快捷问题，"
            "下方最近任务列表，专业金融 SaaS 密度。"
        ),
        "compositionPattern": "sticky-left-sidebar-flowing-right",
        "pageType": "task-driven",
    },
    {
        "nodeId": "page-research-running",
        "title": "研究执行中",
        "htmlSrc": "pages/research-running.html",
        "pageIndex": 2,
        "visualNorthStar": (
            "研究执行中：左侧固定边栏，主区域显示 Trace 时间线、当前阶段、"
            "进度条与流式答案预览，突出过程可观测性。"
        ),
        "compositionPattern": "sticky-left-sidebar-flowing-right",
        "pageType": "task-driven",
    },
    {
        "nodeId": "page-research-result",
        "title": "研究结果",
        "htmlSrc": "pages/research-result.html",
        "pageIndex": 3,
        "visualNorthStar": (
            "研究结果：三栏布局，左侧答案/Claims，中间 Evidence/Calculation 卡片，"
            "右侧 Trace/Metadata，引用标记可定位证据。"
        ),
        "compositionPattern": "asymmetric-three-column",
        "pageType": "information-dense",
    },
    {
        "nodeId": "page-companies",
        "title": "公司库",
        "htmlSrc": "pages/companies.html",
        "pageIndex": 4,
        "visualNorthStar": (
            "公司库：搜索过滤栏 + 数据表格，展示公司名称、代码、市场、最新财务摘要，"
            "高信息密度。"
        ),
        "compositionPattern": "sticky-left-sidebar-flowing-right",
        "pageType": "information-dense",
    },
    {
        "nodeId": "page-company-detail",
        "title": "公司详情",
        "htmlSrc": "pages/company-detail.html",
        "pageIndex": 5,
        "visualNorthStar": (
            "公司详情：顶部公司概况与 KPI，下方财务摘要、研究操作与最近任务，"
            "卡片分区清晰。"
        ),
        "compositionPattern": "large-medium-stacked",
        "pageType": "information-dense",
    },
    {
        "nodeId": "page-documents",
        "title": "文档库",
        "htmlSrc": "pages/documents.html",
        "pageIndex": 6,
        "visualNorthStar": (
            "文档库：上传区 + 文档列表，展示来源、期间、公司、处理状态，"
            "支持元数据扫描。"
        ),
        "compositionPattern": "sticky-left-sidebar-flowing-right",
        "pageType": "information-dense",
    },
    {
        "nodeId": "page-document-detail",
        "title": "文档详情",
        "htmlSrc": "pages/document-detail.html",
        "pageIndex": 7,
        "visualNorthStar": "文档详情：左侧文档元数据，右侧内容预览与 Chunk/证据列表，引用可展开。",
        "compositionPattern": "asymmetric-two-column",
        "pageType": "information-dense",
    },
    {
        "nodeId": "page-history",
        "title": "研究历史",
        "htmlSrc": "pages/history.html",
        "pageIndex": 8,
        "visualNorthStar": (
            "研究历史：过滤栏 + 任务列表，状态标签、公司、时间、操作，"
            "支持筛选与打开结果。"
        ),
        "compositionPattern": "sticky-left-sidebar-flowing-right",
        "pageType": "information-dense",
    },
    {
        "nodeId": "page-settings",
        "title": "设置",
        "htmlSrc": "pages/settings.html",
        "pageIndex": 9,
        "visualNorthStar": "设置：简洁表单页面，分组卡片，会话、Provider、账户设置，低密度专业感。",
        "compositionPattern": "sticky-left-sidebar-flowing-right",
        "pageType": "task-driven",
    },
]

continuity_anchors = [
    "统一左侧边栏导航（研究工作台、公司库、文档库、历史、设置）与顶部 FinSage Logo",
    "统一卡片风格：白色表面、1px 浅灰边框、8px 圆角、极淡阴影",
    "统一主色深靛蓝 #1d4ed8，状态色仅用于语义标签",
    "统一 Inter + Noto Sans SC 字体体系，财务数据使用等宽字 Tabular Nums",
    "统一 1440px 容器、24px 栅格间距、左侧边栏 240px 固定宽度",
]

shared_shell = {
    "navigationShell": "web-app-sidebar",
    "header": {
        "heightPx": 64,
        "layout": "full-width top bar with logo, global search, user avatar",
    },
    "sidebar": {
        "widthPx": 240,
        "position": "fixed-left",
        "items": [
            {"key": "workspace", "label": "研究工作台", "icon": "layout-dashboard"},
            {"key": "companies", "label": "公司库", "icon": "building-2"},
            {"key": "documents", "label": "文档库", "icon": "file-text"},
            {"key": "history", "label": "研究历史", "icon": "history"},
            {"key": "settings", "label": "设置", "icon": "settings"},
        ],
    },
    "mainContent": {"marginLeftPx": 240, "paddingPx": 32, "maxWidthPx": 1440},
    "radiusScale": {"sm": 4, "md": 8, "lg": 12, "xl": 16},
    "surfaceDepthModel": "static-surfaces-border-led",
    "typographySystem": {
        "title": "Inter / Noto Sans SC",
        "body": "Inter / Noto Sans SC",
        "mono": "JetBrains Mono / Noto Sans Mono",
    },
}

generation_tree = {
    "version": "1.0",
    "root": {
        "nodeId": "root",
        "type": "root",
        "status": "generated",
        "children": [
            {
                "nodeId": p["nodeId"],
                "type": "page",
                "status": "pending",
                "htmlSrc": p["htmlSrc"],
                "dependencies": [],
            }
            for p in pages
        ],
    },
}

with open(os.path.join(project_path, "generation-tree.json"), "w", encoding="utf-8") as f:
    json.dump(generation_tree, f, ensure_ascii=False, indent=2)

dispatch_manifest = []
for p in pages:
    dispatch_manifest.append(
        {
            "nodeId": p["nodeId"],
            "htmlSrc": p["htmlSrc"],
            "title": p["title"],
            "pageIndex": p["pageIndex"],
            "laneContract": {
                "resolvedLane": "complex_html_page",
                "packetType": "ComplexPagePacket",
                "pageRuntimeGuide": (
                    "intent-workflows/intent-project-complex-build/"
                    "complex-page-runtime.md"
                ),
                "dispatchContract": (
                    "intent-workflows/intent-project-complex-build/"
                    "complex-page-dispatch-contract.md"
                ),
            },
            "sharedTemplate": None,
            "supplementaryReads": [
                {
                    "path": "visual-experience/visual-experience-guidelines.md",
                    "reason": "professional fintech app design tokens and anti-slop rules",
                    "ownerLane": "complex_html_page",
                },
                {
                    "path": "delivery-quality/page-rendering-quality-gate.md",
                    "reason": "information-dense desktop app pages",
                    "ownerLane": "complex_html_page",
                },
            ],
            "allowedWritePaths": [p["htmlSrc"]],
            "forbiddenWriteRoots": [
                "*.design",
                "runtime-orchestration-summary.json",
                "validation-report.json",
                "finish-readiness-report.json",
            ],
            "toolPolicy": {
                "todoWriteAllowed": False,
                "validationScriptsAllowed": False,
                "previewAllowed": False,
                "helperScriptsAllowed": False,
                "designFileWriteAllowed": False,
                "allowedWritePaths": [p["htmlSrc"], "assets/"],
            },
            "deviceType": "desktop",
            "viewportMode": "document-scroll",
            "cssPath": "colors_and_type.css",
            "brandPrefix": "",
            "fillHtmlHeadCommand": (
                "node c:\\Users\\TaoistMaster\\.trae-cn\\builtin\\design\\default\\skills"
                "\\solo-design\\shared-runtime\\deterministic-tooling"
                "\\apply-html-head-contract.mjs d:\\Weijn\\Codes\\Github\\FinSage"
                "\\finsage-ui\\colors_and_type.css {outputPath} --title=\""
            )
            + p["title"]
            + '" --lang=zh',
            "pageType": p["pageType"],
            "qualityRisks": ["information-dense", "cjk-density", "sidebar-fixed-layout"],
            "visualNorthStar": p["visualNorthStar"],
            "compositionPattern": p["compositionPattern"],
            "continuityAnchors": continuity_anchors,
            "componentPlan": [
                {"name": "Sidebar", "source": "inline-html", "notes": "固定左侧边栏导航"},
                {"name": "TopHeader", "source": "inline-html", "notes": "顶部 Logo、搜索、用户区"},
                {"name": "Card", "source": "tailwind", "notes": "白色表面、浅边框、8px 圆角"},
                {"name": "Button", "source": "tailwind", "notes": "深靛蓝主按钮、描边次要按钮"},
                {"name": "Input", "source": "tailwind", "notes": "48px 高、浅边框、focus ring"},
                {"name": "Badge/Tag", "source": "tailwind", "notes": "状态语义色、圆角标签"},
                {"name": "DataTable", "source": "tailwind", "notes": "公司库/历史列表"},
                {"name": "EvidenceCard", "source": "inline-html", "notes": "研究结果页证据卡片"},
                {"name": "CalculationCard", "source": "inline-html", "notes": "财务计算卡片"},
                {"name": "CitationMarker", "source": "inline-html", "notes": "引用角标"},
                {"name": "ResearchTrace", "source": "inline-html", "notes": "Trace 时间线"},
            ],
            "assets": [],
            "domIdsRequired": [],
        }
    )

expected_dispatches = [
    {
        "nodeId": p["nodeId"],
        "packetType": "ComplexPagePacket",
        "status": "pending",
        "changedFiles": [],
        "toolCallLedger": {
            "todoWriteCalls": 0,
            "previewCalls": 0,
            "validationScriptCalls": 0,
            "helperScriptWrites": 0,
        },
    }
    for p in pages
]

pages_summary = []
for p in pages:
    pages_summary.append(
        {
            "nodeId": p["nodeId"],
            "title": p["title"],
            "htmlSrc": p["htmlSrc"],
            "pageIndex": p["pageIndex"],
            "deviceType": "desktop",
            "viewportMode": "document-scroll",
            "pageType": p["pageType"],
            "visualNorthStar": p["visualNorthStar"],
            "compositionPattern": p["compositionPattern"],
            "continuityAnchors": continuity_anchors,
            "componentPlan": [
                {"name": "Sidebar", "source": "inline-html"},
                {"name": "TopHeader", "source": "inline-html"},
                {"name": "Card", "source": "tailwind"},
                {"name": "Button", "source": "tailwind"},
                {"name": "Input", "source": "tailwind"},
                {"name": "Badge/Tag", "source": "tailwind"},
                {"name": "DataTable", "source": "tailwind"},
            ],
            "imagePlan": [],
            "chartsRequired": False,
            "miniProgramStyle": False,
        }
    )

summary = {
    "schemaVersion": "1.0",
    "skillProvenance": {
        "name": "solo-design",
        "version": "2026.08.06.19.15.08",
        "version_source": "skill-release-manifest.json",
        "schema_version": "1.0",
        "release": "prompt-base-cloud-ssot-migration",
        "read_status": "loaded",
    },
    "project": {
        "operation": "create",
        "resolvedLane": "complex_html_page",
        "projectName": "FinSage 前端 UI",
        "deviceType": "desktop",
        "designRead": "金融研究 SaaS / 专业分析师 / 机构严谨风 / 高密度信息 / 避免营销感与柔和圆角",
        "designDials": {"layoutVariance": 3, "motionIntensity": 2, "visualDensity": 4},
        "styleDefinitionBrief": (
            "专业机构金融风：冷灰底色 + 深靛蓝主色，高密度数据表格，"
            "克制卡片，强调证据链与审计感。"
        ),
        "selectedIntentWorkflowRead": True,
        "contextRequirementsLoaded": [
            {"path": cf, "readStatus": "loaded", "bodyRead": True, "recordedAt": iso_now}
            for cf in context_files
        ],
        "contextReadScope": [
            "intent-workflows/intent-project-complex-build/*.md",
            "shared-runtime/agent-dispatch-runtime/lane-dispatch-index.md",
            "shared-runtime/agent-dispatch-runtime/shared-page-rendering-kernel.md",
            "shared-runtime/runtime-boundaries/lane-runtime-contracts.md",
            "shared-runtime/design-artifact-formats/design-project-file-format.md",
            "delivery-quality/*.md",
            "visual-experience/*.md",
        ],
        "readScopeLedger": [
            {"phase": "preflight", "scope": "context-requirements", "recordedAt": iso_now}
        ],
        "cssPreflightEvidence": {
            "scriptPath": "shared-runtime/deterministic-tooling/apply-html-head-contract.mjs",
            "cssFilePath": "colors_and_type.css",
            "preflightOutputPath": ".preflight/preflight.html",
            "exitCode": 0,
            "semanticTokenFallback": "present",
            "themeVarsPresent": True,
            "tailwindCdnPresent": True,
            "lucidePresent": True,
            "recordedAt": iso_now,
        },
        "generationTree": generation_tree,
        "mobileNavigation": {"applies": False},
        "sharedProjectShellContract": shared_shell,
        "dispatchPreflightManifest": dispatch_manifest,
        "expectedDispatches": expected_dispatches,
        "validationRunDiscipline": {
            "preDispatchContractCheck": True,
            "postGenerationWorkspaceValidation": True,
            "artifactReadinessCheck": True,
        },
        "validationHistory": [],
        "validationRepairLedger": [],
        "validationSnapshot": {},
        "artifactReadinessEvidence": {},
        "lowValueCallWatchdog": {
            "applies": True,
            "noProgressSignals": ["no_tool_call", "no_artifact_diff", "no_structured_decision"],
            "noProgressNextAction": "enter_readiness_or_blocked_summary",
            "recordedAt": iso_now,
        },
        "sourceAuthorityLock": {
            "visualAuthority": "engineering-specification",
            "contentSupplement": "FinSage-V3.4-Full-Stack-Engineering-Spec.md",
            "browserObservationRole": "none",
            "mayOverrideVisualAuthority": False,
            "lockedBeforeDispatch": True,
        },
        "visualQualityCheckpoints": [
            {
                "checkpointId": "vq-anchor",
                "dimension": "visual-anchor",
                "expected": "每个页面顶部稳定的 FinSage Logo + 左侧边栏构成识别锚点",
                "evidenceTarget": "all-pages#shell",
            },
            {
                "checkpointId": "vq-hierarchy",
                "dimension": "information-hierarchy",
                "expected": "标题、KPI、表格/卡片、辅助元数据层级分明，证据链清晰可见",
                "evidenceTarget": "page-research-result#content",
            },
            {
                "checkpointId": "vq-structure",
                "dimension": "composition-structure",
                "expected": (
                    "左侧 240px 固定边栏 + 主内容区 32px 内边距，"
                    "1440px 最大宽度，信息密集但不拥挤"
                ),
                "evidenceTarget": "all-pages#layout",
            },
            {
                "checkpointId": "vq-implementation",
                "dimension": "implementation-strategy",
                "expected": "Tailwind CSS + Lucide 图标 + 自定义 design tokens，无生成图片依赖",
                "evidenceTarget": "all-pages#implementation",
            },
        ],
    },
    "designSource": {
        "operatingMode": "free-explore",
        "cssFilePath": "colors_and_type.css",
        "styleConstraints": {
            "primaryHue": "indigo",
            "radiusMax": 16,
            "staticShadowAlphaMax": 0.05,
            "noSecondaryAccent": True,
            "stateColorsOnly": True,
        },
    },
    "pages": pages_summary,
    "assets": [],
    "wiringPlan": [
        {
            "from": "page-index",
            "to": "page-research-running",
            "domId": "btn-start-research",
            "label": "开始研究",
        },
        {
            "from": "page-research-running",
            "to": "page-research-result",
            "domId": "link-view-result",
            "label": "查看结果",
        },
        {
            "from": "page-index",
            "to": "page-companies",
            "domId": "nav-companies",
            "label": "公司库",
            "hideEdge": True,
        },
        {
            "from": "page-index",
            "to": "page-documents",
            "domId": "nav-documents",
            "label": "文档库",
            "hideEdge": True,
        },
        {
            "from": "page-index",
            "to": "page-history",
            "domId": "nav-history",
            "label": "研究历史",
            "hideEdge": True,
        },
        {
            "from": "page-index",
            "to": "page-settings",
            "domId": "nav-settings",
            "label": "设置",
            "hideEdge": True,
        },
        {
            "from": "page-companies",
            "to": "page-company-detail",
            "domId": "row-company-1",
            "label": "打开公司",
        },
        {
            "from": "page-documents",
            "to": "page-document-detail",
            "domId": "row-document-1",
            "label": "打开文档",
        },
        {
            "from": "page-history",
            "to": "page-research-result",
            "domId": "row-task-1",
            "label": "打开历史结果",
        },
        {
            "from": "page-research-result",
            "to": "page-document-detail",
            "domId": "evidence-doc-1",
            "label": "查看证据来源",
        },
    ],
    "hiddenInteractionPlan": [
        {"from": "page-companies", "to": "page-index", "domId": "nav-workspace", "hideEdge": True},
        {"from": "page-documents", "to": "page-index", "domId": "nav-workspace", "hideEdge": True},
        {"from": "page-history", "to": "page-index", "domId": "nav-workspace", "hideEdge": True},
        {"from": "page-settings", "to": "page-index", "domId": "nav-workspace", "hideEdge": True},
        {
            "from": "page-company-detail",
            "to": "page-companies",
            "domId": "nav-companies",
            "hideEdge": True,
        },
        {
            "from": "page-document-detail",
            "to": "page-documents",
            "domId": "nav-documents",
            "hideEdge": True,
        },
    ],
}

with open(
    os.path.join(project_path, "runtime-orchestration-summary.json"), "w", encoding="utf-8"
) as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print("runtime-orchestration-summary.json written")
