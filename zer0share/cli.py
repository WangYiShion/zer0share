from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import click
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


def _init_logger(log_path: Path) -> None:
    init_pipeline_file_logging(log_path)


def _make_pipeline(config_path: str = "config/settings.toml") -> Pipeline:
    cfg = load_config(Path(config_path))
    _init_logger(cfg.log_path)
    meta = MetaStore(cfg.db_path)
    fetcher = TushareFetcher(cfg.tushare_token, meta)
    notifier = Notifier(cfg.wecom_webhook_url, cfg.notifier_enabled)
    return Pipeline(cfg, fetcher, notifier, meta_store=meta)


def _run_sync_all(
    pipeline: Pipeline,
    parsed_start_date: date | None,
    parsed_end_date: date | None,
) -> None:
    """顺序执行全部接口；单步失败时继续其余步骤，最后汇总错误。成功则写入一行纯文本「日期 同步成功」。"""
    pipeline_condensed_file_log.set(True)
    log_path = pipeline._cfg.log_path
    trim_success_records_if_needed(log_path)

    errors: list[tuple[str, Exception]] = []

    def run_step(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as e:
            errors.append((name, e))

    run_step("trade_cal", pipeline.sync_trade_cal)
    run_step("stock_basic", pipeline.sync_stock_basic)
    run_step(
        "daily_kline",
        lambda: pipeline.sync_daily_kline(
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        ),
    )
    run_step(
        "adj_factor",
        lambda: pipeline.sync_adj_factor(
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        ),
    )
    run_step(
        "daily_basic",
        lambda: pipeline.sync_daily_basic(
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        ),
    )
    run_step(
        "suspend_d",
        lambda: pipeline.sync_suspend_d(
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        ),
    )
    run_step(
        "stk_limit",
        lambda: pipeline.sync_stk_limit(
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        ),
    )
    run_step(
        "stock_st",
        lambda: pipeline.sync_stock_st(
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        ),
    )

    if errors:
        raise click.ClickException(
            f"同步未全部完成，失败 {len(errors)} 项: "
            + ", ".join(name for name, _ in errors)
        )
    if not today_plain_success_exists(log_path, date.today()):
        append_plain_success_line(log_path, date.today())


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    "--table",
    type=click.Choice(
        [
            "daily_kline",
            "stock_basic",
            "trade_cal",
            "adj_factor",
            "daily_basic",
            "suspend_d",
            "stk_limit",
            "stock_st",
        ]
    ),
    default=None,
)
@click.option("--all", "sync_all", is_flag=True, default=False)
@click.option("--start-date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--end-date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
def sync(
    table: str | None,
    sync_all: bool,
    start_date: datetime | None,
    end_date: datetime | None,
) -> None:
    """同步数据。"""
    if end_date is not None and start_date is None:
        raise click.UsageError("--end-date requires --start-date")
    if (start_date is not None or end_date is not None) and table not in (
        "daily_kline",
        "adj_factor",
        "daily_basic",
        "suspend_d",
        "stk_limit",
        "stock_st",
    ):
        raise click.UsageError(
            "date range options are only supported for "
            "daily_kline, adj_factor, daily_basic, suspend_d, stk_limit, and stock_st"
        )

    parsed_start_date = start_date.date() if start_date is not None else None
    parsed_end_date = end_date.date() if end_date is not None else None
    if (
        parsed_start_date is not None
        and parsed_end_date is not None
        and parsed_end_date < parsed_start_date
    ):
        raise click.UsageError("--end-date must be on or after --start-date")

    with _make_pipeline() as pipeline:
        trim_success_records_if_needed(pipeline._cfg.log_path)
        if sync_all:
            _run_sync_all(pipeline, parsed_start_date, parsed_end_date)
            return

        pipeline_condensed_file_log.set(True)
        if table == "trade_cal":
            pipeline.sync_trade_cal()
        if table == "stock_basic":
            pipeline.sync_stock_basic()
        if table == "daily_kline":
            pipeline.sync_daily_kline(
                start_date=parsed_start_date,
                end_date=parsed_end_date,
            )
        if table == "adj_factor":
            pipeline.sync_adj_factor(
                start_date=parsed_start_date,
                end_date=parsed_end_date,
            )
        if table == "daily_basic":
            pipeline.sync_daily_basic(
                start_date=parsed_start_date,
                end_date=parsed_end_date,
            )
        if table == "suspend_d":
            pipeline.sync_suspend_d(
                start_date=parsed_start_date,
                end_date=parsed_end_date,
            )
        if table == "stk_limit":
            pipeline.sync_stk_limit(
                start_date=parsed_start_date,
                end_date=parsed_end_date,
            )
        if table == "stock_st":
            pipeline.sync_stock_st(
                start_date=parsed_start_date,
                end_date=parsed_end_date,
            )


@cli.command()
def status() -> None:
    """显示各表最后更新时间。"""
    cfg = load_config(Path("config/settings.toml"))
    with MetaStore(cfg.db_path) as store:
        for table in [
            "trade_cal",
            "daily_kline",
            "adj_factor",
            "daily_basic",
            "suspend_d",
            "stk_limit",
            "stock_st",
            "stock_basic",
        ]:
            last = store.get_last_date(table)
            click.echo(f"{table}: {last or '从未同步'}")


@cli.command("scheduler")
@click.argument("action", type=click.Choice(["start"]))
def scheduler_cmd(action: str) -> None:
    """启动定时调度。"""
    from zer0share.scheduler import start_scheduler

    start_scheduler()
