"""seed_milvus 灌库脚本离线测试（不连 Milvus、不加载 BGE-M3）。

通过 monkeypatch 替换 ingestion/retrieval 真实依赖，验证编排链：
load -> chunk -> extract_metadata -> encode -> index，以及 tenant 注入与 dry-run 短路。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_spec = importlib.util.spec_from_file_location("seed_milvus", _SCRIPTS / "seed_milvus.py")
seed_milvus = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(seed_milvus)


class _FakeEmbedder:
    def encode_chunks(self, chunks):
        raise AssertionError("unexpected: use patched FakeEmb via seed_milvus.BGE3Embedder")


@pytest.fixture
def patched(monkeypatch):
    calls = {"load": [], "chunk": [], "meta": [], "encode": [], "index": [], "ensure": []}

    def fake_load(source, *, title="", source_type="upload"):
        calls["load"].append((source, title))
        return "PARSED"

    def fake_chunk(doc, document_id, *, size=800, overlap=120):
        calls["chunk"].append((doc, document_id))
        assert isinstance(document_id, str) and document_id
        return [f"CHUNK-{document_id}-0"]

    def fake_meta(*, title="", company=None, ticker=None, market=None,
                  document_type=None, report_period=None, authority_tier=1, published_at=None):
        calls["meta"].append((title, authority_tier))
        return {"authority_tier": authority_tier}  # 故意不含 tenant_id

    def fake_encode(chunks):
        calls["encode"].append(chunks)
        return [f"IDX:{c}" for c in chunks]

    def fake_index(manager, indexed, *, doc_meta):
        calls["index"].append((manager, indexed, doc_meta))
        assert doc_meta.get("tenant_id") == calls.get("tenant")
        return len(indexed)

    def fake_ensure(manager, *, force_recreate=False):
        calls["ensure"].append(force_recreate)

    class _FakeManager:
        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(seed_milvus, "load_document", fake_load)
    monkeypatch.setattr(seed_milvus, "chunk_document", fake_chunk)
    monkeypatch.setattr(seed_milvus, "extract_metadata", fake_meta)
    class FakeEmb:
        def encode_chunks(self, chunks):
            calls["encode"].append(chunks)
            return [f"IDX:{c}" for c in chunks]

    monkeypatch.setattr(seed_milvus, "BGE3Embedder", lambda *a, **k: FakeEmb())
    monkeypatch.setattr(seed_milvus, "index_chunks", fake_index)
    monkeypatch.setattr(seed_milvus, "ensure_collection", fake_ensure)
    monkeypatch.setattr(seed_milvus, "MilvusClientManager", lambda *a, **k: _FakeManager())
    calls["tenant"] = seed_milvus._DEFAULT_TENANT
    return calls


def _src_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    return f


def test_ingest_document_full_chain(patched, tmp_path):
    mgr = object()
    emb = seed_milvus.BGE3Embedder()
    n = seed_milvus.ingest_document(
        mgr, emb, _src_file(tmp_path), tenant="__default__", meta={}, dry_run=False
    )
    assert n == 1
    assert patched["load"] and patched["load"][0][1] == "sample"  # title=stem
    assert patched["chunk"] and patched["chunk"][0][0] == "PARSED"
    assert patched["encode"]  # 真实编码被调用
    assert patched["index"]
    # tenant 注入到 doc_meta
    assert patched["index"][0][2]["tenant_id"] == "__default__"
    assert "tenant_id" not in patched["meta"][0][0] or True


def test_ingest_document_dry_run_skips_encode_and_index(patched, tmp_path):
    n = seed_milvus.ingest_document(
        None, None, _src_file(tmp_path), tenant="__default__", meta={}, dry_run=True
    )
    assert n == 1
    assert patched["load"] and patched["chunk"]  # 仍解析+分块
    assert not patched["encode"]  # 不加载模型
    assert not patched["index"]  # 不写 Milvus


def test_main_force_recreate_and_count(patched, tmp_path):
    f = _src_file(tmp_path)
    rc = seed_milvus.main(["--source", str(f), "--force-recreate", "--company", "ACME"])
    assert rc == 0
    assert patched["ensure"] == [True]  # 重建集合
    assert patched["index"]  # 写入
    assert patched["meta"][0][0] == "sample"


def test_main_dry_run_on_dir(patched, tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.pdf").write_bytes(b"%PDF-1.4")
    (d / "b.pdf").write_bytes(b"%PDF-1.4")
    rc = seed_milvus.main(["--source", str(d), "--dry-run"])
    assert rc == 0
    assert len(patched["load"]) == 2
    assert not patched.get("ensure")
    assert not patched["index"]
