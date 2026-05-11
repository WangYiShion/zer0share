from pathlib import Path

import pytest

from zer0share import config as config_module
from zer0share.api import LocalPro
from zer0share import pro_api
from zer0share.config import (
    ZER0SHARE_DATA_DIR_ENV,
    find_optional_settings_toml,
    load_config,
    parse_data_dir_from_settings_toml,
    resolve_pro_api_data_directory,
)


VALID_TOML = """
[paths]
data_dir = "data"
db_path = "db/meta.duckdb"
log_path = "logs/pipeline.log"

[scheduler]
daily_kline_hour = 18
daily_kline_minute = 0
basic_hour = 8
adj_factor_hour = 18
adj_factor_minute = 5

[notifier]
wecom_webhook_url = "https://example.com/webhook"
enabled = false
"""


def test_load_config_returns_all_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "test_token")
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(VALID_TOML, encoding="utf-8")

    cfg = load_config(cfg_file)

    assert cfg.tushare_token == "test_token"
    assert cfg.data_dir == Path("data")
    assert cfg.db_path == Path("db/meta.duckdb")
    assert cfg.log_path == Path("logs/pipeline.log")
    assert cfg.scheduler_daily_kline_hour == 18
    assert cfg.scheduler_daily_kline_minute == 0
    assert cfg.scheduler_basic_hour == 8
    assert cfg.scheduler_adj_factor_hour == 18
    assert cfg.scheduler_adj_factor_minute == 5
    assert cfg.scheduler_stk_limit_hour == 18
    assert cfg.scheduler_stk_limit_minute == 10
    assert cfg.scheduler_stock_st_hour == 18
    assert cfg.scheduler_stock_st_minute == 15
    assert cfg.scheduler_daily_basic_hour == 18
    assert cfg.scheduler_daily_basic_minute == 20
    assert cfg.scheduler_suspend_d_hour == 18
    assert cfg.scheduler_suspend_d_minute == 25
    assert cfg.wecom_webhook_url == "https://example.com/webhook"
    assert cfg.notifier_enabled is False


def test_load_config_notifier_enabled_true(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "x")
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(
        VALID_TOML.replace("enabled = false", "enabled = true"),
        encoding="utf-8",
    )

    cfg = load_config(cfg_file)

    assert cfg.notifier_enabled is True


def test_load_config_explicit_stk_limit_scheduler(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "x")
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(
        VALID_TOML.replace(
            "adj_factor_minute = 5",
            "adj_factor_minute = 5\nstk_limit_hour = 9\nstk_limit_minute = 0",
        ),
        encoding="utf-8",
    )

    cfg = load_config(cfg_file)

    assert cfg.scheduler_stk_limit_hour == 9
    assert cfg.scheduler_stk_limit_minute == 0


def test_load_config_explicit_stock_st_scheduler(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "x")
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(
        VALID_TOML.replace(
            "adj_factor_minute = 5",
            "adj_factor_minute = 5\nstock_st_hour = 9\nstock_st_minute = 25",
        ),
        encoding="utf-8",
    )

    cfg = load_config(cfg_file)

    assert cfg.scheduler_stock_st_hour == 9
    assert cfg.scheduler_stock_st_minute == 25


def test_load_config_explicit_daily_basic_scheduler(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "x")
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(
        VALID_TOML.replace(
            "adj_factor_minute = 5",
            "adj_factor_minute = 5\ndaily_basic_hour = 10\ndaily_basic_minute = 30",
        ),
        encoding="utf-8",
    )

    cfg = load_config(cfg_file)

    assert cfg.scheduler_daily_basic_hour == 10
    assert cfg.scheduler_daily_basic_minute == 30


def test_load_config_explicit_suspend_d_scheduler(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "x")
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(
        VALID_TOML.replace(
            "adj_factor_minute = 5",
            "adj_factor_minute = 5\nsuspend_d_hour = 10\nsuspend_d_minute = 45",
        ),
        encoding="utf-8",
    )

    cfg = load_config(cfg_file)

    assert cfg.scheduler_suspend_d_hour == 10
    assert cfg.scheduler_suspend_d_minute == 45


def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError, match="配置文件不存在"):
        load_config(Path("nonexistent/settings.toml"))


def test_load_config_missing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "x")
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(
        "[paths]\n"
        "data_dir='data'\n"
        "db_path='db/meta.duckdb'\n"
        "log_path='logs/pipeline.log'\n"
        "[scheduler]\n"
        "daily_kline_hour=18\n"
        "daily_kline_minute=0\n"
        "basic_hour=8\n"
        # adj_factor keys missing
        "[notifier]\n"
        "wecom_webhook_url='https://x.com'\n"
        "enabled=false\n",
        encoding="utf-8",
    )

    with pytest.raises(KeyError, match="配置文件缺少必要字段"):
        load_config(cfg_file)


def test_load_config_requires_tushare_token_env(tmp_path, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(VALID_TOML, encoding="utf-8")

    with pytest.raises(ValueError, match="TUSHARE_TOKEN"):
        load_config(cfg_file)


def test_load_config_rejects_empty_tushare_token_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "   ")
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(VALID_TOML, encoding="utf-8")

    with pytest.raises(ValueError, match="TUSHARE_TOKEN"):
        load_config(cfg_file)


def test_config_is_immutable(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(VALID_TOML, encoding="utf-8")
    cfg = load_config(cfg_file)

    with pytest.raises(Exception):
        cfg.tushare_token = "hacked"


def test_parse_data_dir_relative_to_repo_root(tmp_path):
    repo = tmp_path / "repo"
    cfg_file = repo / "config" / "settings.toml"
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text(VALID_TOML, encoding="utf-8")

    assert parse_data_dir_from_settings_toml(cfg_file) == (repo / "data").resolve()


def test_parse_data_dir_absolute_path(tmp_path):
    target = tmp_path / "absolute_data_target"
    target.mkdir()
    cfg_file = tmp_path / "settings.toml"
    cfg_file.write_text(
        VALID_TOML.replace(
            'data_dir = "data"',
            f'data_dir = "{target.resolve().as_posix()}"',
        ),
        encoding="utf-8",
    )

    assert parse_data_dir_from_settings_toml(cfg_file) == target.resolve()


def test_find_explicit_settings_raises_when_missing(tmp_path):
    missing = tmp_path / "nosuch.toml"

    with pytest.raises(FileNotFoundError, match="配置文件不存在"):
        find_optional_settings_toml(missing)


def test_resolve_pro_api_prefers_kw_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(ZER0SHARE_DATA_DIR_ENV, str(tmp_path / "env_should_lose"))

    dd = tmp_path / "chosen"
    dd.mkdir()

    assert resolve_pro_api_data_directory(None, data_dir=dd) == dd.resolve()


def test_resolve_pro_api_prefers_env_over_settings(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    cfg = repo / "config" / "settings.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(VALID_TOML, encoding="utf-8")

    env_dir = tmp_path / "from_env"
    env_dir.mkdir()
    monkeypatch.setenv(ZER0SHARE_DATA_DIR_ENV, str(env_dir.resolve()))

    import os

    old = os.getcwd()
    try:
        os.chdir(repo)
        assert resolve_pro_api_data_directory() == env_dir.resolve()
    finally:
        os.chdir(old)


def test_resolve_pro_api_reads_implicit_settings_in_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv(ZER0SHARE_DATA_DIR_ENV, raising=False)

    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config" / "settings.toml").write_text(VALID_TOML, encoding="utf-8")

    import os

    old = os.getcwd()
    try:
        os.chdir(repo)
        assert resolve_pro_api_data_directory() == (repo / "data").resolve()
    finally:
        os.chdir(old)


def test_resolve_fallback_package_adjacent(monkeypatch, tmp_path):
    monkeypatch.delenv(ZER0SHARE_DATA_DIR_ENV, raising=False)

    install_root = tmp_path / "root"
    pkg_dir = install_root / "zer0share"
    pkg_dir.mkdir(parents=True)
    (install_root / "data").mkdir()

    monkeypatch.setattr(config_module, "__file__", str(pkg_dir / "config.py"))

    junk = tmp_path / "junk_cwd"
    junk.mkdir()
    monkeypatch.chdir(junk)

    assert resolve_pro_api_data_directory() == (install_root / "data").resolve()


def test_pro_api_requires_no_tushare_token(tmp_path, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv(ZER0SHARE_DATA_DIR_ENV, raising=False)

    dd = tmp_path / "stored"
    dd.mkdir()

    pro = pro_api(data_dir=dd)

    assert isinstance(pro, LocalPro)
    assert pro._data_dir == dd.resolve()


def test_pro_api_positional_settings_path_reads_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv(ZER0SHARE_DATA_DIR_ENV, raising=False)

    repo = tmp_path / "repo"
    cfg_file = repo / "config" / "settings.toml"
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text(VALID_TOML, encoding="utf-8")

    pro = pro_api(str(cfg_file))
    assert pro._data_dir == (repo / "data").resolve()
