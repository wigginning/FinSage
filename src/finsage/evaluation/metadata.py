"""可复现性元数据（m09 T909，§5.21 evaluation_runs 字段）。

收集运行所需的环境 / 模型 / 配置指纹，保证一次 benchmark 可被精确定位与复现：
git_commit / model_name / embedding_model / reranker_model / config。git_commit
为尽力而为（非 git 仓库或 git 不可用时回退 'unknown'，不抛错），其余字段由调用方显式注入。
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

_GIT_UNKNOWN = "unknown"


@dataclass(frozen=True)
class RunMetadata:
    """§5.21 evaluation_runs 的可复现字段。"""

    git_commit: str = _GIT_UNKNOWN
    model_name: str = ""
    embedding_model: str = ""
    reranker_model: str = ""
    config: dict[str, Any] = field(default_factory=dict)


def _git_commit(cwd: str) -> str:
    """尽力获取当前 git commit hash；非仓库/无 git/失败一律回退 unknown。"""
    if not shutil.which("git"):
        return _GIT_UNKNOWN
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _GIT_UNKNOWN
    if proc.returncode != 0:
        return _GIT_UNKNOWN
    commit = proc.stdout.strip()
    return commit if commit else _GIT_UNKNOWN


def collect_metadata(
    *,
    model_name: str = "",
    embedding_model: str = "",
    reranker_model: str = "",
    config: dict[str, Any] | None = None,
    cwd: str | None = None,
) -> RunMetadata:
    """组装可复现元数据。``cwd`` 传给 git 探测，缺省取当前工作目录。"""
    import os

    return RunMetadata(
        git_commit=_git_commit(cwd or os.getcwd()),
        model_name=model_name,
        embedding_model=embedding_model,
        reranker_model=reranker_model,
        config=dict(config or {}),
    )


def metadata_to_run_fields(metadata: RunMetadata) -> dict[str, Any]:
    """取落 evaluation_runs 的列字段（不含 config_json，由调用方决定写哪）。"""
    return {
        "git_commit": metadata.git_commit,
        "model_name": metadata.model_name,
        "embedding_model": metadata.embedding_model,
        "reranker_model": metadata.reranker_model,
    }


__all__ = ["RunMetadata", "collect_metadata", "metadata_to_run_fields", "_GIT_UNKNOWN"]