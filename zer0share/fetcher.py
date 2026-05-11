from collections.abc import Callable
from datetime import date
from time import sleep
from typing import TypeVar

import pandas as pd
import tushare as ts
from loguru import logger

from zer0share.storage import MetaStore
from zer0share.tushare_rate_limit import (
    RATE_LIMIT_DOWNGRADE_MARGIN,
    TushareApiRateLimiter,
    parse_calls_per_minute_from_tushare_message,
    per_second_cap_for_minute,
)


BASIC_COLS = [
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "fullname",
    "enname",
    "cnspell",
    "market",
    "exchange",
    "curr_type",
    "list_status",
    "list_date",
    "delist_date",
    "is_hs",
    "act_name",
    "act_ent_type",
]
DAILY_COLS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
]
TRADE_CAL_COLS = ["exchange", "cal_date", "is_open", "pretrade_date"]
ADJ_FACTOR_COLS = ["ts_code", "trade_date", "adj_factor"]
STK_LIMIT_COLS = [
    "ts_code",
    "trade_date",
    "pre_close",
    "up_limit",
    "down_limit",
]
STOCK_ST_COLS = ["ts_code", "name", "trade_date", "type", "type_name"]
DAILY_BASIC_COLS = [
    "ts_code",
    "trade_date",
    "close",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "ps_ttm",
    "dv_ratio",
    "dv_ttm",
    "total_share",
    "float_share",
    "free_share",
    "total_mv",
    "circ_mv",
]
SUSPEND_D_COLS = ["ts_code", "trade_date", "suspend_timing", "suspend_type"]

_STK_LIMIT_PAGE_SIZE = 5000
_STOCK_ST_PAGE_SIZE = 1000
_DAILY_BASIC_PAGE_SIZE = 6000
_SUSPEND_D_PAGE_SIZE = 5000

T = TypeVar("T")


class TushareFetcher:
    def __init__(self, token: str, meta_store: MetaStore | None = None):
        self._pro = ts.pro_api(token)
        self._meta = meta_store
        self._limiters: dict[str, TushareApiRateLimiter] = {}

    def _limiter_for(self, api_name: str) -> TushareApiRateLimiter:
        if api_name not in self._limiters:
            caps = (
                self._meta.get_tushare_api_rate_cap(api_name)
                if self._meta
                else None
            )
            if caps:
                self._limiters[api_name] = TushareApiRateLimiter(
                    max_per_minute=caps[0],
                    max_per_second=caps[1],
                )
            else:
                self._limiters[api_name] = TushareApiRateLimiter()
        return self._limiters[api_name]

    def _call_pro_api(self, api_name: str, fn: Callable[[], T]) -> T:
        while True:
            self._limiter_for(api_name).acquire()
            try:
                return fn()
            except Exception as e:
                msg = str(e)
                if "频率超限" not in msg:
                    raise
                announced = parse_calls_per_minute_from_tushare_message(msg)
                if announced is None:
                    raise
                new_min = max(1, announced - RATE_LIMIT_DOWNGRADE_MARGIN)
                new_sec = per_second_cap_for_minute(new_min)
                logger.warning(
                    f"Tushare API「{api_name}」频率超限（服务端提示 {announced} 次/分钟），"
                    f"将本地限流调整为 {new_min} 次/分钟、{new_sec} 次/秒，"
                    "已写入元数据库，60 秒后重试当前请求"
                )
                self._limiter_for(api_name).set_caps(new_min, new_sec)
                if self._meta:
                    self._meta.upsert_tushare_api_rate_cap(
                        api_name,
                        new_min,
                        new_sec,
                    )
                sleep(60)

    def fetch_stock_basic(self) -> pd.DataFrame:
        logger.info("拉取 stock_basic")
        df = self._call_pro_api(
            "stock_basic",
            lambda: self._pro.stock_basic(
                exchange="",
                list_status="L,D,P,G",
                fields=",".join(BASIC_COLS),
            ),
        )
        df["list_date"] = pd.to_datetime(
            df["list_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
        df["delist_date"] = pd.to_datetime(
            df["delist_date"], format="%Y%m%d", errors="coerce"
        ).apply(lambda x: x.date() if not pd.isnull(x) else None)
        return df[BASIC_COLS]

    def fetch_daily_kline(self, trade_date: date) -> pd.DataFrame:
        date_str = trade_date.strftime("%Y%m%d")
        logger.info(f"拉取日线行情: {date_str}")
        df = self._call_pro_api(
            "daily",
            lambda: self._pro.daily(
                trade_date=date_str, fields=",".join(DAILY_COLS)
            ),
        )
        if df is None or df.empty:
            return pd.DataFrame(columns=DAILY_COLS)
        df["trade_date"] = pd.to_datetime(
            df["trade_date"], format="%Y%m%d"
        ).dt.date
        return df[DAILY_COLS]

    def fetch_adj_factor(self, trade_date: date) -> pd.DataFrame:
        date_str = trade_date.strftime("%Y%m%d")
        logger.info(f"拉取复权因子: {date_str}")
        df = self._call_pro_api(
            "adj_factor",
            lambda: self._pro.adj_factor(
                trade_date=date_str, fields=",".join(ADJ_FACTOR_COLS)
            ),
        )
        if df is None or df.empty:
            return pd.DataFrame(columns=ADJ_FACTOR_COLS)
        df["trade_date"] = pd.to_datetime(
            df["trade_date"], format="%Y%m%d"
        ).dt.date
        return df[ADJ_FACTOR_COLS]

    def fetch_stk_limit(self, trade_date: date) -> pd.DataFrame:
        date_str = trade_date.strftime("%Y%m%d")
        logger.info(f"拉取每日涨跌停价格 stk_limit: {date_str}")
        field_str = ",".join(STK_LIMIT_COLS)
        chunks: list[pd.DataFrame] = []
        offset = 0
        while True:
            df = self._call_pro_api(
                "stk_limit",
                lambda o=offset: self._pro.stk_limit(
                    trade_date=date_str,
                    offset=o,
                    limit=_STK_LIMIT_PAGE_SIZE,
                    fields=field_str,
                ),
            )
            if df is None or df.empty:
                break
            chunks.append(df)
            if len(df) < _STK_LIMIT_PAGE_SIZE:
                break
            offset += len(df)
        if not chunks:
            return pd.DataFrame(columns=STK_LIMIT_COLS)
        out = pd.concat(chunks, ignore_index=True)
        out = out.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
        out["trade_date"] = pd.to_datetime(
            out["trade_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
        return out[STK_LIMIT_COLS]

    def fetch_stock_st(self, trade_date: date) -> pd.DataFrame:
        date_str = trade_date.strftime("%Y%m%d")
        logger.info(f"拉取 ST 股票列表 stock_st: {date_str}")
        field_str = ",".join(STOCK_ST_COLS)
        chunks: list[pd.DataFrame] = []
        offset = 0
        while True:
            df = self._call_pro_api(
                "stock_st",
                lambda o=offset: self._pro.stock_st(
                    trade_date=date_str,
                    offset=o,
                    limit=_STOCK_ST_PAGE_SIZE,
                    fields=field_str,
                ),
            )
            if df is None or df.empty:
                break
            chunks.append(df)
            if len(df) < _STOCK_ST_PAGE_SIZE:
                break
            offset += len(df)
        if not chunks:
            return pd.DataFrame(columns=STOCK_ST_COLS)
        out = pd.concat(chunks, ignore_index=True)
        out = out.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
        out["trade_date"] = pd.to_datetime(
            out["trade_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
        return out[STOCK_ST_COLS]

    def fetch_daily_basic(self, trade_date: date) -> pd.DataFrame:
        date_str = trade_date.strftime("%Y%m%d")
        logger.info(f"拉取每日指标 daily_basic: {date_str}")
        field_str = ",".join(DAILY_BASIC_COLS)
        chunks: list[pd.DataFrame] = []
        offset = 0
        while True:
            df = self._call_pro_api(
                "daily_basic",
                lambda o=offset: self._pro.daily_basic(
                    ts_code="",
                    trade_date=date_str,
                    offset=o,
                    limit=_DAILY_BASIC_PAGE_SIZE,
                    fields=field_str,
                ),
            )
            if df is None or df.empty:
                break
            chunks.append(df)
            if len(df) < _DAILY_BASIC_PAGE_SIZE:
                break
            offset += len(df)
        if not chunks:
            return pd.DataFrame(columns=DAILY_BASIC_COLS)
        out = pd.concat(chunks, ignore_index=True)
        out = out.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
        out["trade_date"] = pd.to_datetime(
            out["trade_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
        return out[DAILY_BASIC_COLS]

    def fetch_suspend_d(self, trade_date: date) -> pd.DataFrame:
        date_str = trade_date.strftime("%Y%m%d")
        logger.info(f"拉取每日停复牌信息 suspend_d: {date_str}")
        field_str = ",".join(SUSPEND_D_COLS)
        chunks: list[pd.DataFrame] = []
        offset = 0
        while True:
            df = self._call_pro_api(
                "suspend_d",
                lambda o=offset: self._pro.suspend_d(
                    trade_date=date_str,
                    offset=o,
                    limit=_SUSPEND_D_PAGE_SIZE,
                    fields=field_str,
                ),
            )
            if df is None or df.empty:
                break
            chunks.append(df)
            if len(df) < _SUSPEND_D_PAGE_SIZE:
                break
            offset += len(df)
        if not chunks:
            return pd.DataFrame(columns=SUSPEND_D_COLS)
        out = pd.concat(chunks, ignore_index=True)
        out = out.drop_duplicates(
            subset=["ts_code", "trade_date", "suspend_type"],
            keep="last",
        )
        out["trade_date"] = pd.to_datetime(
            out["trade_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
        return out[SUSPEND_D_COLS]

    def fetch_trade_cal(self, exchange: str) -> pd.DataFrame:
        today = date.today().strftime("%Y%m%d")
        logger.info(f"拉取交易日历: {exchange}")
        df = self._call_pro_api(
            "trade_cal",
            lambda: self._pro.trade_cal(
                exchange=exchange,
                start_date="19900101",
                end_date=today,
                fields=",".join(TRADE_CAL_COLS),
            ),
        )
        if df is None or df.empty:
            return pd.DataFrame(columns=TRADE_CAL_COLS)
        df["cal_date"] = pd.to_datetime(
            df["cal_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
        df["pretrade_date"] = pd.to_datetime(
            df["pretrade_date"], format="%Y%m%d", errors="coerce"
        ).apply(lambda x: x.date() if not pd.isnull(x) else None)
        df["is_open"] = (
            df["is_open"].astype(str).map({"1": True, "0": False}).astype(object)
        )
        return df[TRADE_CAL_COLS]
