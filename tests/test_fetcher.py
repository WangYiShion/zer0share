import pandas as pd
import pytest
from datetime import date
from unittest.mock import patch

from zer0share.fetcher import TushareFetcher
from zer0share.storage import MetaStore


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


def _basic_row(
    *,
    list_status: str = "L",
    list_date: str = "19910403",
    delist_date: str | None = None,
) -> dict[str, object]:
    return {
        "ts_code": "000001.SZ",
        "symbol": "000001",
        "name": "平安银行",
        "area": "深圳",
        "industry": "银行",
        "fullname": "平安银行股份有限公司",
        "enname": "Ping An Bank",
        "cnspell": "payh",
        "market": "主板",
        "exchange": "SZSE",
        "curr_type": "CNY",
        "list_status": list_status,
        "list_date": list_date,
        "delist_date": delist_date,
        "is_hs": "S",
        "act_name": "深圳市投资控股有限公司",
        "act_ent_type": "地方国企",
    }


@pytest.fixture
def mock_pro():
    with patch("tushare.pro_api") as mock:
        yield mock.return_value


def test_fetch_stock_basic_returns_all_documented_columns(mock_pro):
    mock_pro.stock_basic.return_value = pd.DataFrame([_basic_row()])
    fetcher = TushareFetcher("fake_token")

    df = fetcher.fetch_stock_basic()

    assert list(df.columns) == BASIC_COLS
    assert len(df) == 1


def test_fetch_stock_basic_requests_all_statuses_and_fields(mock_pro):
    mock_pro.stock_basic.return_value = pd.DataFrame([_basic_row()])
    fetcher = TushareFetcher("fake_token")

    fetcher.fetch_stock_basic()

    mock_pro.stock_basic.assert_called_once_with(
        exchange="",
        list_status="L,D,P,G",
        fields=",".join(BASIC_COLS),
    )


def test_fetch_stock_basic_converts_only_date_fields(mock_pro):
    mock_pro.stock_basic.return_value = pd.DataFrame(
        [_basic_row(list_status="D", delist_date="20240131")]
    )
    fetcher = TushareFetcher("fake_token")

    df = fetcher.fetch_stock_basic()

    assert df.iloc[0]["list_date"] == date(1991, 4, 3)
    assert df.iloc[0]["delist_date"] == date(2024, 1, 31)
    assert df.iloc[0]["fullname"] == "平安银行股份有限公司"
    assert df.iloc[0]["act_ent_type"] == "地方国企"


def test_fetch_daily_kline_returns_correct_data(mock_pro):
    mock_pro.daily.return_value = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240102"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "pre_close": [10.0],
            "change": [0.5],
            "pct_chg": [5.0],
            "vol": [100000.0],
            "amount": [1050000.0],
        }
    )
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_daily_kline(date(2024, 1, 2))
    assert len(df) == 1
    assert df.iloc[0]["ts_code"] == "000001.SZ"
    assert df.iloc[0]["trade_date"] == date(2024, 1, 2)


def test_fetch_daily_kline_returns_empty_on_no_data(mock_pro):
    mock_pro.daily.return_value = pd.DataFrame()
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_daily_kline(date(2024, 1, 1))
    assert df.empty


def test_fetch_daily_kline_returns_empty_when_none(mock_pro):
    mock_pro.daily.return_value = None
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_daily_kline(date(2024, 1, 1))
    assert df.empty


def test_fetch_stk_limit_single_page(mock_pro):
    mock_pro.stk_limit.return_value = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240102"],
            "pre_close": [10.0],
            "up_limit": [11.0],
            "down_limit": [9.0],
        }
    )
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_stk_limit(date(2024, 1, 2))

    mock_pro.stk_limit.assert_called_once()
    assert list(df.columns) == [
        "ts_code",
        "trade_date",
        "pre_close",
        "up_limit",
        "down_limit",
    ]
    assert len(df) == 1
    assert df.iloc[0]["up_limit"] == 11.0
    assert df.iloc[0]["trade_date"] == date(2024, 1, 2)


def test_fetch_stk_limit_concat_pages(mock_pro):
    page_a = pd.DataFrame(
        {
            "ts_code": [f"{i:06d}.SZ" for i in range(5000)],
            "trade_date": ["20240102"] * 5000,
            "pre_close": [1.0] * 5000,
            "up_limit": [1.1] * 5000,
            "down_limit": [0.9] * 5000,
        }
    )
    page_b = pd.DataFrame(
        {
            "ts_code": ["600000.SH"],
            "trade_date": ["20240102"],
            "pre_close": [8.0],
            "up_limit": [8.8],
            "down_limit": [7.2],
        }
    )
    mock_pro.stk_limit.side_effect = [page_a, page_b]
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_stk_limit(date(2024, 1, 2))

    assert mock_pro.stk_limit.call_count == 2
    assert len(df) == 5001


def test_fetch_stk_limit_returns_empty_when_none(mock_pro):
    mock_pro.stk_limit.return_value = None
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_stk_limit(date(2024, 1, 1))
    assert df.empty


def test_fetch_stk_limit_retries_after_rate_limit_error(mock_pro):
    err = Exception("抱歉，您访问接口(stk_limit)频率超限(400次/分钟)，详见文档")
    ok = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240102"],
            "pre_close": [10.0],
            "up_limit": [11.0],
            "down_limit": [9.0],
        }
    )
    mock_pro.stk_limit.side_effect = [err, ok]
    fetcher = TushareFetcher("fake_token")
    with patch("zer0share.fetcher.sleep") as mock_sleep:
        df = fetcher.fetch_stk_limit(date(2024, 1, 2))
    mock_sleep.assert_called_once_with(60)
    assert mock_pro.stk_limit.call_count == 2
    assert len(df) == 1
    lim = fetcher._limiter_for("stk_limit")
    assert lim._max_per_minute == 380
    assert lim._max_per_second == 6


def test_fetch_stk_limit_persists_rate_cap_for_next_process(mock_pro, tmp_path):
    err = Exception("抱歉，访问(stk_limit)频率超限(400次/分钟)，详见文档")
    ok = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240102"],
            "pre_close": [10.0],
            "up_limit": [11.0],
            "down_limit": [9.0],
        }
    )
    mock_pro.stk_limit.side_effect = [err, ok]
    db = tmp_path / "meta.duckdb"
    meta = MetaStore(db)
    fetcher = TushareFetcher("fake_token", meta)
    with patch("zer0share.fetcher.sleep"):
        fetcher.fetch_stk_limit(date(2024, 1, 2))
    assert meta.get_tushare_api_rate_cap("stk_limit") == (380, 6)

    mock_pro.stk_limit.side_effect = None
    mock_pro.stk_limit.return_value = ok
    meta.close()

    meta2 = MetaStore(db)
    fetcher2 = TushareFetcher("fake_token", meta2)
    fetcher2.fetch_stk_limit(date(2024, 1, 2))
    assert fetcher2._limiter_for("stk_limit")._max_per_minute == 380
    meta2.close()


def test_fetch_stock_st_single_page(mock_pro):
    mock_pro.stock_st.return_value = pd.DataFrame(
        {
            "ts_code": ["300313.SZ"],
            "name": ["*ST天山"],
            "trade_date": ["20240102"],
            "type": ["ST"],
            "type_name": ["风险警示板"],
        }
    )
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_stock_st(date(2024, 1, 2))

    mock_pro.stock_st.assert_called_once()
    assert list(df.columns) == ["ts_code", "name", "trade_date", "type", "type_name"]
    assert len(df) == 1
    assert df.iloc[0]["trade_date"] == date(2024, 1, 2)


def test_fetch_stock_st_concat_pages(mock_pro):
    page_a = pd.DataFrame(
        {
            "ts_code": [f"{i:06d}.SZ" for i in range(1000)],
            "name": ["x"] * 1000,
            "trade_date": ["20240102"] * 1000,
            "type": ["ST"] * 1000,
            "type_name": ["风险警示板"] * 1000,
        }
    )
    page_b = pd.DataFrame(
        {
            "ts_code": ["600000.SH"],
            "name": ["*ST浦发"],
            "trade_date": ["20240102"],
            "type": ["ST"],
            "type_name": ["风险警示板"],
        }
    )
    mock_pro.stock_st.side_effect = [page_a, page_b]
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_stock_st(date(2024, 1, 2))

    assert mock_pro.stock_st.call_count == 2
    assert len(df) == 1001


def test_fetch_stock_st_returns_empty_when_none(mock_pro):
    mock_pro.stock_st.return_value = None
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_stock_st(date(2024, 1, 1))
    assert df.empty


def _daily_basic_row(ts_code: str = "000001.SZ") -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": "20240102",
        "close": 10.5,
        "turnover_rate": 2.4584,
        "turnover_rate_f": 3.01,
        "volume_ratio": 0.72,
        "pe": 8.69,
        "pe_ttm": 8.1,
        "pb": 1.03,
        "ps": 1.5,
        "ps_ttm": 1.4,
        "dv_ratio": 1.11,
        "dv_ttm": 1.0,
        "total_share": 10000.0,
        "float_share": 8000.0,
        "free_share": 7200.0,
        "total_mv": 1000000.0,
        "circ_mv": 840000.0,
    }


def test_fetch_daily_basic_single_page(mock_pro):
    mock_pro.daily_basic.return_value = pd.DataFrame([_daily_basic_row()])
    fetcher = TushareFetcher("fake_token")

    df = fetcher.fetch_daily_basic(date(2024, 1, 2))

    mock_pro.daily_basic.assert_called_once()
    call_kw = mock_pro.daily_basic.call_args.kwargs
    assert call_kw["ts_code"] == ""
    assert call_kw["trade_date"] == "20240102"
    assert call_kw["offset"] == 0
    assert len(df) == 1
    assert df.iloc[0]["trade_date"] == date(2024, 1, 2)


def test_fetch_daily_basic_concat_pages(mock_pro):
    page_a = pd.DataFrame([_daily_basic_row(f"{i:06d}.SZ") for i in range(6000)])
    page_b = pd.DataFrame([_daily_basic_row("700000.SH")])
    mock_pro.daily_basic.side_effect = [page_a, page_b]
    fetcher = TushareFetcher("fake_token")

    df = fetcher.fetch_daily_basic(date(2024, 1, 2))

    assert mock_pro.daily_basic.call_count == 2
    assert len(df) == 6001


def test_fetch_daily_basic_returns_empty_when_none(mock_pro):
    mock_pro.daily_basic.return_value = None
    fetcher = TushareFetcher("fake_token")

    df = fetcher.fetch_daily_basic(date(2024, 1, 1))

    assert df.empty


def test_fetch_trade_cal_returns_correct_columns(mock_pro):
    mock_pro.trade_cal.return_value = pd.DataFrame({
        "exchange": ["SSE", "SSE"],
        "cal_date": ["20240102", "20240103"],
        "is_open": ["1", "0"],
        "pretrade_date": ["20231229", "20240102"],
    })
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_trade_cal("SSE")
    assert list(df.columns) == ["exchange", "cal_date", "is_open", "pretrade_date"]
    assert len(df) == 2


def test_fetch_trade_cal_converts_types(mock_pro):
    mock_pro.trade_cal.return_value = pd.DataFrame({
        "exchange": ["SSE", "SSE"],
        "cal_date": ["20240102", "20240103"],
        "is_open": ["1", "0"],
        "pretrade_date": ["20231229", "20240102"],
    })
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_trade_cal("SSE")
    assert df.iloc[0]["cal_date"] == date(2024, 1, 2)
    assert df.iloc[0]["is_open"] is True
    assert df.iloc[1]["is_open"] is False
    assert df.iloc[0]["pretrade_date"] == date(2023, 12, 29)


def test_fetch_trade_cal_returns_empty_when_none(mock_pro):
    mock_pro.trade_cal.return_value = None
    fetcher = TushareFetcher("fake_token")
    df = fetcher.fetch_trade_cal("SSE")
    assert df.empty
