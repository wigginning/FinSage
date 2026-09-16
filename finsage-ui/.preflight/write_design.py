import json
import os
from datetime import UTC, datetime

project_path = r"d:\Weijn\Codes\Github\FinSage\finsage-ui"
now = datetime.now(UTC)
timestamp_ms = int(now.timestamp() * 1000)
iso_now = now.isoformat()

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

design_data = {
    "data": [
        {
            "id": p["nodeId"],
            "title": p["title"],
            "type": "page",
            "version": 1,
            "createdAt": timestamp_ms,
            "devMetadata": {"htmlSrc": p["htmlSrc"], "interactions": []},
            "canvasData": {"x": 0, "y": 0, "group": 0},
        }
        for p in pages
    ],
    "config": {"autoLayout": True, "deviceType": "desktop", "projectName": "FinSage 前端 UI"},
}

with open(os.path.join(project_path, "finsage-ui.design"), "w", encoding="utf-8") as f:
    json.dump(design_data, f, ensure_ascii=False, indent=2)

print(".design written")
