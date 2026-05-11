from unittest.mock import patch

from zer0share.tushare_rate_limit import (
    TushareApiRateLimiter,
    parse_calls_per_minute_from_tushare_message,
    per_second_cap_for_minute,
)


def test_limiter_blocks_ninth_call_in_same_second() -> None:
    clock = {"t": 0.0}
    sleeps: list[float] = []

    def mono() -> float:
        return clock["t"]

    def sleepy(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    lim = TushareApiRateLimiter(max_per_minute=480, max_per_second=8)
    with patch("zer0share.tushare_rate_limit.monotonic", mono):
        with patch("zer0share.tushare_rate_limit.sleep", sleepy):
            for _ in range(8):
                lim.acquire()
            assert not sleeps
            lim.acquire()
    assert sleeps == [1.0]


def test_limiter_blocks_when_minute_window_full() -> None:
    clock = {"t": 100.0}
    sleeps: list[float] = []

    def mono() -> float:
        return clock["t"]

    def sleepy(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    lim = TushareApiRateLimiter(max_per_minute=3, max_per_second=100)
    with patch("zer0share.tushare_rate_limit.monotonic", mono):
        with patch("zer0share.tushare_rate_limit.sleep", sleepy):
            for i in range(3):
                clock["t"] = 100.0 + i * 0.01
                lim.acquire()
            clock["t"] = 100.05
            lim.acquire()
    assert sleeps and sleeps[-1] >= 59.0


def test_parse_calls_per_minute_from_tushare_message() -> None:
    msg = "抱歉，您访问接口(stk_limit)频率超限(400次/分钟)，具体频次详情"
    assert parse_calls_per_minute_from_tushare_message(msg) == 400


def test_parse_calls_per_minute_returns_none_when_missing() -> None:
    assert parse_calls_per_minute_from_tushare_message("network error") is None


def test_per_second_cap_for_minute_scales() -> None:
    assert per_second_cap_for_minute(380) == 6
    assert per_second_cap_for_minute(480) == 8


def test_set_caps_clears_history() -> None:
    lim = TushareApiRateLimiter(max_per_minute=3, max_per_second=10)
    lim.acquire()
    lim.acquire()
    assert len(lim._calls) == 2
    lim.set_caps(100, 5)
    assert len(lim._calls) == 0
    assert lim._max_per_minute == 100
    assert lim._max_per_second == 5
