import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from zer0share.config import load_config
from zer0share.fetcher import TushareFetcher
from zer0share.logging_setup import init_pipeline_file_logging, pipeline_condensed_file_log
from zer0share.notifier import Notifier
from zer0share.pipeline import Pipeline
from zer0share.pipeline_log import (
    append_plain_success_line,
    trim_success_records_if_needed,
    today_plain_success_exists,
)
from zer0share.storage import MetaStore

SCHEDULED_JOB_IDS = (
    "daily_kline",
    "stock_basic",
    "adj_factor",
    "stk_limit",
    "stock_st",
    "daily_basic",
    "suspend_d",
)


def _day_state_path(log_path: Path) -> Path:
    return log_path.parent / "pipeline_day_state.json"


def _load_day_state(log_path: Path) -> dict[str, Any]:
    p = _day_state_path(log_path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _save_day_state(log_path: Path, state: dict[str, Any]) -> None:
    p = _day_state_path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_today_state(raw: dict[str, Any], today: str) -> dict[str, Any]:
    if raw.get("date") == today and isinstance(raw.get("jobs"), dict):
        for jid in SCHEDULED_JOB_IDS:
            raw["jobs"].setdefault(jid, "pending")
        raw.setdefault("finalized", False)
        return raw
    return {
        "date": today,
        "jobs": {jid: "pending" for jid in SCHEDULED_JOB_IDS},
        "finalized": False,
    }


def _wrap_scheduled_job(
    log_path: Path,
    job_id: str,
    fn: Callable[[], None],
) -> Callable[[], None]:
    """精简 pipeline.log：单任务仅 ERROR；全部 7 项当日均成功后追加一行「日期 同步成功」。"""

    def runner() -> None:
        pipeline_condensed_file_log.set(True)
        trim_success_records_if_needed(log_path)
        today_s = date.today().isoformat()
        state = _ensure_today_state(_load_day_state(log_path), today_s)
        try:
            fn()
            state["jobs"][job_id] = "ok"
        except Exception:
            state["jobs"][job_id] = "error"
            state["finalized"] = False
            _save_day_state(log_path, state)
            raise
        _save_day_state(log_path, state)

        all_ok = all(state["jobs"].get(jid) == "ok" for jid in SCHEDULED_JOB_IDS)
        today_d = date.today()
        if (
            all_ok
            and not state.get("finalized")
            and not today_plain_success_exists(log_path, today_d)
        ):
            trim_success_records_if_needed(log_path)
            append_plain_success_line(log_path, today_d)
            state["finalized"] = True
            _save_day_state(log_path, state)

    return runner


def start_scheduler(config_path: str = "config/settings.toml") -> None:
    cfg = load_config(Path(config_path))
    init_pipeline_file_logging(cfg.log_path)
    pipeline_condensed_file_log.set(True)

    meta = MetaStore(cfg.db_path)
    fetcher = TushareFetcher(cfg.tushare_token, meta)
    notifier = Notifier(cfg.wecom_webhook_url, cfg.notifier_enabled)

    with Pipeline(cfg, fetcher, notifier, meta_store=meta) as pipeline:
        scheduler = BlockingScheduler()
        scheduler.add_job(
            _wrap_scheduled_job(cfg.log_path, "daily_kline", pipeline.sync_daily_kline),
            CronTrigger(
                hour=cfg.scheduler_daily_kline_hour,
                minute=cfg.scheduler_daily_kline_minute,
            ),
            id="daily_kline",
        )
        scheduler.add_job(
            _wrap_scheduled_job(
                cfg.log_path, "stock_basic", pipeline.sync_stock_basic
            ),
            CronTrigger(hour=cfg.scheduler_basic_hour),
            id="stock_basic",
        )
        scheduler.add_job(
            _wrap_scheduled_job(cfg.log_path, "adj_factor", pipeline.sync_adj_factor),
            CronTrigger(
                hour=cfg.scheduler_adj_factor_hour,
                minute=cfg.scheduler_adj_factor_minute,
            ),
            id="adj_factor",
        )
        scheduler.add_job(
            _wrap_scheduled_job(cfg.log_path, "stk_limit", pipeline.sync_stk_limit),
            CronTrigger(
                hour=cfg.scheduler_stk_limit_hour,
                minute=cfg.scheduler_stk_limit_minute,
            ),
            id="stk_limit",
        )
        scheduler.add_job(
            _wrap_scheduled_job(cfg.log_path, "stock_st", pipeline.sync_stock_st),
            CronTrigger(
                hour=cfg.scheduler_stock_st_hour,
                minute=cfg.scheduler_stock_st_minute,
            ),
            id="stock_st",
        )
        scheduler.add_job(
            _wrap_scheduled_job(
                cfg.log_path, "daily_basic", pipeline.sync_daily_basic
            ),
            CronTrigger(
                hour=cfg.scheduler_daily_basic_hour,
                minute=cfg.scheduler_daily_basic_minute,
            ),
            id="daily_basic",
        )
        scheduler.add_job(
            _wrap_scheduled_job(cfg.log_path, "suspend_d", pipeline.sync_suspend_d),
            CronTrigger(
                hour=cfg.scheduler_suspend_d_hour,
                minute=cfg.scheduler_suspend_d_minute,
            ),
            id="suspend_d",
        )
        logger.info(
            f"调度器启动: daily_kline 每天 "
            f"{cfg.scheduler_daily_kline_hour}:{cfg.scheduler_daily_kline_minute:02d}, "
            f"adj_factor 每天 "
            f"{cfg.scheduler_adj_factor_hour}:{cfg.scheduler_adj_factor_minute:02d}, "
            f"stk_limit 每天 "
            f"{cfg.scheduler_stk_limit_hour}:{cfg.scheduler_stk_limit_minute:02d}, "
            f"stock_st 每天 "
            f"{cfg.scheduler_stock_st_hour}:{cfg.scheduler_stock_st_minute:02d}, "
            f"daily_basic 每天 "
            f"{cfg.scheduler_daily_basic_hour}:{cfg.scheduler_daily_basic_minute:02d}, "
            f"suspend_d 每天 "
            f"{cfg.scheduler_suspend_d_hour}:{cfg.scheduler_suspend_d_minute:02d}, "
            f"stock_basic 每天 {cfg.scheduler_basic_hour}:00"
        )
        scheduler.start()
