import json
import os

project_path = r"d:\Weijn\Codes\Github\FinSage\finsage-ui"

pages = [
    {"nodeId": "page-index", "title": "研究工作台", "htmlSrc": "pages/index.html", "pageIndex": 1},
    {
        "nodeId": "page-research-running",
        "title": "研究执行中",
        "htmlSrc": "pages/research-running.html",
        "pageIndex": 2,
    },
    {
        "nodeId": "page-research-result",
        "title": "研究结果",
        "htmlSrc": "pages/research-result.html",
        "pageIndex": 3,
    },
    {
        "nodeId": "page-companies",
        "title": "公司库",
        "htmlSrc": "pages/companies.html",
        "pageIndex": 4,
    },
    {
        "nodeId": "page-company-detail",
        "title": "公司详情",
        "htmlSrc": "pages/company-detail.html",
        "pageIndex": 5,
    },
    {
        "nodeId": "page-documents",
        "title": "文档库",
        "htmlSrc": "pages/documents.html",
        "pageIndex": 6,
    },
    {
        "nodeId": "page-document-detail",
        "title": "文档详情",
        "htmlSrc": "pages/document-detail.html",
        "pageIndex": 7,
    },
    {
        "nodeId": "page-history",
        "title": "研究历史",
        "htmlSrc": "pages/history.html",
        "pageIndex": 8,
    },
    {"nodeId": "page-settings", "title": "设置", "htmlSrc": "pages/settings.html", "pageIndex": 9},
]

generation_tree = {
    "version": "1.0",
    "root": {
        "nodeId": "root",
        "kind": "root",
        "status": "generated",
        "children": [
            {
                "nodeId": "gen-project-shell",
                "kind": "project-shell",
                "status": "pending",
                "output": "partials/project-shell.html",
                "sharedRegions": [
                    "header",
                    "sidebar",
                    "main-wrapper",
                    "footer",
                    "brand-css",
                    "type-scale",
                    "radius-shadow-model",
                ],
                "privateRegions": [],
                "mutableSlots": ["slot-active-nav-key", "slot-page-title", "slot-main-content"],
                "children": [
                    {
                        "nodeId": p["nodeId"],
                        "kind": "page-leaf",
                        "status": "pending",
                        "output": p["htmlSrc"],
                        "sharedRegions": ["header", "sidebar", "main-wrapper", "footer"],
                        "privateRegions": ["slot-main-content"],
                        "mutableSlots": [
                            "slot-active-nav-key",
                            "slot-page-title",
                            "slot-main-content",
                        ],
                        "dependencies": ["gen-project-shell"],
                        "children": [],
                    }
                    for p in pages
                ],
            }
        ],
    },
}

with open(os.path.join(project_path, "generation-tree.json"), "w", encoding="utf-8") as f:
    json.dump(generation_tree, f, ensure_ascii=False, indent=2)

# Update runtime summary
with open(os.path.join(project_path, "runtime-orchestration-summary.json"), encoding="utf-8") as f:
    summary = json.load(f)

summary["project"]["generationTree"] = generation_tree

# Add project-shell to dispatch manifest
shell_manifest = {
    "nodeId": "gen-project-shell",
    "htmlSrc": "partials/project-shell.html",
    "title": "共享外壳",
    "pageIndex": 0,
    "laneContract": {
        "resolvedLane": "complex_html_page",
        "packetType": "ComplexPagePacket",
        "pageRuntimeGuide": "intent-workflows/intent-project-complex-build/complex-page-runtime.md",
        "dispatchContract": (
            "intent-workflows/intent-project-complex-build/"
            "complex-page-dispatch-contract.md"
        ),
    },
    "sharedTemplate": None,
    "supplementaryReads": [
        {
            "path": "visual-experience/visual-experience-guidelines.md",
            "reason": "professional fintech app design tokens",
            "ownerLane": "complex_html_page",
        },
        {
            "path": "delivery-quality/page-rendering-quality-gate.md",
            "reason": "shared shell layout stability",
            "ownerLane": "complex_html_page",
        },
    ],
    "allowedWritePaths": ["partials/project-shell.html"],
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
        "allowedWritePaths": ["partials/project-shell.html"],
    },
    "deviceType": "desktop",
    "viewportMode": "document-scroll",
    "cssPath": "colors_and_type.css",
    "brandPrefix": "",
    "fillHtmlHeadCommand": (
        "node c:\\Users\\TaoistMaster\\.trae-cn\\builtin\\design\\default\\skills"
        "\\solo-design\\shared-runtime\\deterministic-tooling"
        "\\apply-html-head-contract.mjs d:\\Weijn\\Codes\\Github\\FinSage"
        "\\finsage-ui\\colors_and_type.css d:\\Weijn\\Codes\\Github\\FinSage"
        '\\finsage-ui\\.preflight\\preflight-shell.html --title="共享外壳" --lang=zh'
    ),
    "pageType": "fragment",
    "qualityRisks": ["shared-shell-stability", "slot-consistency"],
    "visualNorthStar": "共享应用外壳：顶部导航栏、左侧边栏、主内容槽位，所有页面保持一致。",
    "compositionPattern": "sticky-left-sidebar-flowing-right",
    "continuityAnchors": summary["pages"][0]["continuityAnchors"],
    "componentPlan": [
        {"name": "TopHeader", "source": "inline-html"},
        {"name": "Sidebar", "source": "inline-html"},
        {"name": "MainWrapper", "source": "inline-html"},
    ],
    "assets": [],
    "domIdsRequired": [],
}

summary["project"]["dispatchPreflightManifest"] = [shell_manifest] + summary["project"][
    "dispatchPreflightManifest"
]
summary["project"]["expectedDispatches"] = [
    {
        "nodeId": "gen-project-shell",
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
] + summary["project"]["expectedDispatches"]

with open(
    os.path.join(project_path, "runtime-orchestration-summary.json"), "w", encoding="utf-8"
) as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print("generation tree and summary updated")
