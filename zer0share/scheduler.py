from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from zer0share.config import load_config
from zer0share.fetcher import TushareFetcher
from zer0share.notifier import Notifier
from zer0share.pipeline import Pipeline
from zer0share.storage import MetaStore


_logger_initialized = False


def _init_logger(log_path: Path) -> None:
    global _logger_initialized
    if not _logger_initialized:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(log_path, rotation="10 MB", retention="30 days")
        _logger_initialized = True


def start_scheduler(config_path: str = "config/settings.toml") -> None:
    cfg = load_config(Path(config_path))
    _init_logger(cfg.log_path)

    meta = MetaStore(cfg.db_path)
    fetcher = TushareFetcher(cfg.tushare_token, meta)
    notifier = Notifier(cfg.wecom_webhook_url, cfg.notifier_enabled)

    with Pipeline(cfg, fetcher, notifier, meta_store=meta) as pipeline:
        scheduler = BlockingScheduler()
        scheduler.add_job(
            pipeline.sync_daily_kline,
            CronTrigger(
                hour=cfg.scheduler_daily_kline_hour,
                minute=cfg.scheduler_daily_kline_minute,
            ),
            id="daily_kline",
        )
        scheduler.add_job(
            pipeline.sync_stock_basic,
            CronTrigger(hour=cfg.scheduler_basic_hour),
            id="stock_basic",
        )
        scheduler.add_job(
            pipeline.sync_adj_factor,
            CronTrigger(
                hour=cfg.scheduler_adj_factor_hour,
                minute=cfg.scheduler_adj_factor_minute,
            ),
            id="adj_factor",
        )
        scheduler.add_job(
            pipeline.sync_stk_limit,
            CronTrigger(
                hour=cfg.scheduler_stk_limit_hour,
                minute=cfg.scheduler_stk_limit_minute,
            ),
            id="stk_limit",
        )
        scheduler.add_job(
            pipeline.sync_stock_st,
            CronTrigger(
                hour=cfg.scheduler_stock_st_hour,
                minute=cfg.scheduler_stock_st_minute,
            ),
            id="stock_st",
        )
        scheduler.add_job(
            pipeline.sync_daily_basic,
            CronTrigger(
                hour=cfg.scheduler_daily_basic_hour,
                minute=cfg.scheduler_daily_basic_minute,
            ),
            id="daily_basic",
        )
        scheduler.add_job(
            pipeline.sync_suspend_d,
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
