"""settings 冒烟：配置加载、项目相对路径解析、模型缓存路径可覆盖。"""

from __future__ import annotations

from finsage.settings import PROJECT_ROOT, Settings


def test_model_local_path_defaults_to_project_models() -> None:
    """本地预下载模型根目录应解析到 <项目根>/resources/models。"""
    s = Settings()
    assert s.model_local_path == PROJECT_ROOT / "resources/models"


def test_model_local_dir_relative_default() -> None:
    """默认 model_local_dir 为相对路径 resources/models。"""
    assert Settings().model_local_dir == "resources/models"


def test_model_cache_dir_override() -> None:
    """在线兜底下载缓存目录可通过 model_cache_dir 覆盖（相对项目根解析）。"""
    s = Settings(_env_file=None, model_cache_dir="data/alt-cache")
    assert s.model_cache_path == PROJECT_ROOT / "data/alt-cache"


def test_defaults_contain_no_secret(monkeypatch) -> None:
    """默认配置不携带真实凭据（占位口令仅用于本地开发说明）。"""
    # 显式不读 .env，并清除相关 OS 环境变量，避免本地环境变量/凭据污染
    # 「默认值无 secret」的判定 —— 这样才能真正验证代码默认值是占位符，
    # 而非被 FIN_DB_URL / LLM_API_KEY 等运行时环境变量覆盖（_env_file=None
    # 仅屏蔽 .env 文件，不屏蔽 os.environ）。
    monkeypatch.delenv("FIN_DB_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("FIN_LLM_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.llm_api_key is None
    assert "CHANGE_ME" in s.db_url  # 占位值，非真实密文


def test_persistence_enabled_default_by_env() -> None:
    """P0 持久化：生产环境默认开启持久化；开发/测试默认关闭。"""
    prod = Settings(_env_file=None, app_env="prod")
    assert prod.persistence_enabled is True

    dev = Settings(_env_file=None, app_env="dev")
    assert dev.persistence_enabled is False


def test_persistence_explicit_override() -> None:
    """显式 enable_persistence 优先于环境默认。"""
    prod_off = Settings(_env_file=None, app_env="prod", enable_persistence=False)
    assert prod_off.persistence_enabled is False

    dev_on = Settings(_env_file=None, app_env="dev", enable_persistence=True)
    assert dev_on.persistence_enabled is True
