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
from zer0share.sync_notify import (
    LEVEL1_ALL_SUCCESS_MESSAGE,
    format_level1_failure_message,
    sync_notify_suppressed,
)

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
        raw.setdefault("errors", {})
        if not isinstance(raw["errors"], dict):
            raw["errors"] = {}
        raw.setdefault("finalized", False)
        raw.setdefault("digest_sent", False)
        return raw
    return {
        "date": today,
        "jobs": {jid: "pending" for jid in SCHEDULED_JOB_IDS},
        "errors": {},
        "finalized": False,
        "digest_sent": False,
    }


def _try_send_level1_scheduler_digest(
    notifier: Notifier, log_path: Path, state: dict[str, Any]
) -> None:
    """七大定时任务均在当日进入终态后：只推送一条成功或一条汇总失败列表。"""
    if state.get("digest_sent"):
        return
    terminal = all(
        state["jobs"].get(j) in ("ok", "error") for j in SCHEDULED_JOB_IDS
    )
    if not terminal:
        return
    failed = [j for j in SCHEDULED_JOB_IDS if state["jobs"].get(j) == "error"]
    errs: dict[str, str] = state.get("errors") or {}
    today_d = date.today()
    if not failed:
        if not state.get("finalized") and not today_plain_success_exists(
            log_path, today_d
        ):
            trim_success_records_if_needed(log_path)
            append_plain_success_line(log_path, today_d)
            state["finalized"] = True
        notifier.send(LEVEL1_ALL_SUCCESS_MESSAGE)
    else:
        pairs = [(j, errs.get(j, "未知错误")) for j in failed]
        notifier.send(format_level1_failure_message(pairs))
    state["digest_sent"] = True
    _save_day_state(log_path, state)


def _wrap_scheduled_job(
    log_path: Path,
    job_id: str,
    fn: Callable[[], None],
    notifier: Notifier,
) -> Callable[[], None]:
    """单任务内抑制 Pipeline 逐条推送；全部任务终态后由 _try_send_level1_scheduler_digest 聚合一条。"""

    def runner() -> None:
        pipeline_condensed_file_log.set(True)
        trim_success_records_if_needed(log_path)
        today_s = date.today().isoformat()
        state = _ensure_today_state(_load_day_state(log_path), today_s)
        suppress_tok = sync_notify_suppressed.set(True)
        try:
            fn()
        except Exception as e:
            state["jobs"][job_id] = "error"
            state.setdefault("errors", {})[job_id] = str(e)
            state["finalized"] = False
            _save_day_state(log_path, state)
            sync_notify_suppressed.reset(suppress_tok)
            _try_send_level1_scheduler_digest(notifier, log_path, state)
            raise
        else:
            state["jobs"][job_id] = "ok"
            state.setdefault("errors", {}).pop(job_id, None)
            _save_day_state(log_path, state)
            sync_notify_suppressed.reset(suppress_tok)
            _try_send_level1_scheduler_digest(notifier, log_path, state)

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
            _wrap_scheduled_job(
                cfg.log_path, "daily_kline", pipeline.sync_daily_kline, notifier
            ),
            CronTrigger(
                hour=cfg.scheduler_daily_kline_hour,
                minute=cfg.scheduler_daily_kline_minute,
            ),
            id="daily_kline",
        )
        scheduler.add_job(
            _wrap_scheduled_job(
                cfg.log_path, "stock_basic", pipeline.sync_stock_basic, notifier
            ),
            CronTrigger(hour=cfg.scheduler_basic_hour),
            id="stock_basic",
        )
        scheduler.add_job(
            _wrap_scheduled_job(
                cfg.log_path, "adj_factor", pipeline.sync_adj_factor, notifier
            ),
            CronTrigger(
                hour=cfg.scheduler_adj_factor_hour,
                minute=cfg.scheduler_adj_factor_minute,
            ),
            id="adj_factor",
        )
        scheduler.add_job(
            _wrap_scheduled_job(
                cfg.log_path, "stk_limit", pipeline.sync_stk_limit, notifier
            ),
            CronTrigger(
                hour=cfg.scheduler_stk_limit_hour,
                minute=cfg.scheduler_stk_limit_minute,
            ),
            id="stk_limit",
        )
        scheduler.add_job(
            _wrap_scheduled_job(
                cfg.log_path, "stock_st", pipeline.sync_stock_st, notifier
            ),
            CronTrigger(
                hour=cfg.scheduler_stock_st_hour,
                minute=cfg.scheduler_stock_st_minute,
            ),
            id="stock_st",
        )
        scheduler.add_job(
            _wrap_scheduled_job(
                cfg.log_path, "daily_basic", pipeline.sync_daily_basic, notifier
            ),
            CronTrigger(
                hour=cfg.scheduler_daily_basic_hour,
                minute=cfg.scheduler_daily_basic_minute,
            ),
            id="daily_basic",
        )
        scheduler.add_job(
            _wrap_scheduled_job(
                cfg.log_path, "suspend_d", pipeline.sync_suspend_d, notifier
            ),
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
