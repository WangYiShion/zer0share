from dataclasses import dataclass
import os
from pathlib import Path
import tomllib


ZER0SHARE_DATA_DIR_ENV = "ZER0SHARE_DATA_DIR"


def _resolve_user_path(raw: str | Path) -> Path:
    """Resolve a filesystem path relative to cwd if not absolute."""
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()


def find_optional_settings_toml(config_path: str | Path | None) -> Path | None:
    """Return an existing ``settings.toml`` path, or None.

    With *config_path*: that file must exist (raises ``FileNotFoundError`` otherwise).
    Otherwise: try ``cwd/config/settings.toml`` then ``<package_parent>/config/settings.toml``.
    """
    if config_path is not None:
        resolved = _resolve_user_path(config_path)
        if not resolved.is_file():
            raise FileNotFoundError(f"配置文件不存在: {resolved}")
        return resolved
    cwd_cfg = Path.cwd() / "config" / "settings.toml"
    if cwd_cfg.is_file():
        return cwd_cfg.resolve()
    beside_pkg = Path(__file__).resolve().parent.parent / "config" / "settings.toml"
    if beside_pkg.is_file():
        return beside_pkg
    return None


def parse_data_dir_from_settings_toml(settings_path: Path) -> Path:
    """Load only ``paths.data_dir``. Relative paths are anchored to repo root (parent of ``config/``)."""
    try:
        with open(settings_path, "rb") as f:
            raw = tomllib.load(f)
        rel_or_abs = Path(raw["paths"]["data_dir"])
    except KeyError as e:
        raise ValueError(f"配置文件缺少 paths.data_dir: {settings_path}") from e

    if rel_or_abs.is_absolute():
        return rel_or_abs.resolve()
    repo_root = settings_path.resolve().parent.parent
    return (repo_root / rel_or_abs).resolve()


def default_package_adjacent_data_dir() -> Path:
    """`<install_or_repo>/data`, i.e. next to the ``zer0share`` package."""
    return (Path(__file__).resolve().parent.parent / "data").resolve()


def resolve_pro_api_data_directory(
    config_path: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
) -> Path:
    """Resolve Parquet root for ``pro_api()`` — no ``TUSHARE_TOKEN`` needed.

    Precedence: *data_dir* → ``ZER0SHARE_DATA_DIR`` env → optional ``settings.toml`` → package ``data/``.
    """
    if data_dir is not None:
        return _resolve_user_path(data_dir)
    env = os.environ.get(ZER0SHARE_DATA_DIR_ENV, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    settings_path = find_optional_settings_toml(config_path)
    if settings_path is not None:
        return parse_data_dir_from_settings_toml(settings_path)
    return default_package_adjacent_data_dir()


def _load_tushare_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "未设置环境变量 TUSHARE_TOKEN。请在运行同步或调度前设置该变量，"
            "勿再将 token 写入配置文件。"
        )
    return token


@dataclass(frozen=True)
class Config:
    tushare_token: str
    data_dir: Path
    db_path: Path
    log_path: Path
    scheduler_daily_kline_hour: int
    scheduler_daily_kline_minute: int
    scheduler_basic_hour: int
    scheduler_adj_factor_hour: int
    scheduler_adj_factor_minute: int
    scheduler_stk_limit_hour: int
    scheduler_stk_limit_minute: int
    scheduler_stock_st_hour: int
    scheduler_stock_st_minute: int
    wecom_webhook_url: str
    notifier_enabled: bool


def load_config(path: Path = Path("config/settings.toml")) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"配置文件格式错误: {e}") from e
    try:
        scheduler = raw["scheduler"]
        return Config(
            tushare_token=_load_tushare_token(),
            data_dir=Path(raw["paths"]["data_dir"]),
            db_path=Path(raw["paths"]["db_path"]),
            log_path=Path(raw["paths"]["log_path"]),
            scheduler_daily_kline_hour=scheduler["daily_kline_hour"],
            scheduler_daily_kline_minute=scheduler["daily_kline_minute"],
            scheduler_basic_hour=scheduler["basic_hour"],
            scheduler_adj_factor_hour=scheduler["adj_factor_hour"],
            scheduler_adj_factor_minute=scheduler["adj_factor_minute"],
            scheduler_stk_limit_hour=scheduler.get("stk_limit_hour", 18),
            scheduler_stk_limit_minute=scheduler.get("stk_limit_minute", 10),
            scheduler_stock_st_hour=scheduler.get("stock_st_hour", 18),
            scheduler_stock_st_minute=scheduler.get("stock_st_minute", 15),
            wecom_webhook_url=raw["notifier"]["wecom_webhook_url"],
            notifier_enabled=raw["notifier"]["enabled"],
        )
    except KeyError as e:
        raise KeyError(f"配置文件缺少必要字段: {e}") from e
