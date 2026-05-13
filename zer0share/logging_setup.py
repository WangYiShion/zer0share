"""pipeline.log 的 loguru 配置：支持「精简文件日志」模式。"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

from loguru import logger

_pipeline_file_sink_id: int | None = None

# True 时写入 pipeline.log：仅 ERROR 及以上与显式 allow_pipeline_file；其它 INFO 依赖 stderr
pipeline_condensed_file_log: ContextVar[bool] = ContextVar(
    "pipeline_condensed_file_log", default=False
)


def _pipeline_file_filter(record: dict) -> bool:
    if record["level"].no >= 40:
        return True
    if not pipeline_condensed_file_log.get():
        return True
    return bool(record["extra"].get("allow_pipeline_file"))


def init_pipeline_file_logging(log_path: Path) -> None:
    """注册 pipeline.log 文件 sink（进程内仅初始化一次）。"""
    global _pipeline_file_sink_id
    if _pipeline_file_sink_id is not None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _pipeline_file_sink_id = logger.add(
        str(log_path),
        rotation="10 MB",
        retention=None,
        encoding="utf-8",
        filter=_pipeline_file_filter,
    )
