"""Tushare Pro 调用侧限流：略低于账号级配额，便于长期稳定同步。"""

import re
from collections import deque
from time import monotonic, sleep

# 与 Tushare 文档/账号策略对齐的参考值（实现采用更保守的一侧）
OFFICIAL_MAX_CALLS_PER_MINUTE = 500

DEFAULT_SAFE_MAX_CALLS_PER_MINUTE = 480
DEFAULT_SAFE_MAX_CALLS_PER_SECOND = 8

# 服务端报「频率超限」且能从文案解析出每分钟配额时：新配额 = 解析值 − 下边距（至少为 1）
RATE_LIMIT_DOWNGRADE_MARGIN = 20

_TUSHARE_CALLS_PER_MINUTE = re.compile(r"(\d+)\s*次\s*/\s*分钟")


def parse_calls_per_minute_from_tushare_message(message: str) -> int | None:
    """从 Tushare 返回文案中解析「N次/分钟」中的 N。"""
    match = _TUSHARE_CALLS_PER_MINUTE.search(message)
    if not match:
        return None
    return int(match.group(1))


def per_second_cap_for_minute(max_per_minute: int) -> int:
    """按默认 480/min、8/s 的比例，为新的每分钟上限推导每秒上限。"""
    return max(
        1,
        min(
            DEFAULT_SAFE_MAX_CALLS_PER_SECOND,
            max_per_minute
            * DEFAULT_SAFE_MAX_CALLS_PER_SECOND
            // DEFAULT_SAFE_MAX_CALLS_PER_MINUTE,
        ),
    )


class TushareApiRateLimiter:
    """滑动窗口：任意 60 秒内不超过 *max_per_minute*；任意连续 1 秒内不超过 *max_per_second*。"""

    def __init__(
        self,
        *,
        max_per_minute: int = DEFAULT_SAFE_MAX_CALLS_PER_MINUTE,
        max_per_second: int = DEFAULT_SAFE_MAX_CALLS_PER_SECOND,
    ) -> None:
        self._max_per_minute = max_per_minute
        self._max_per_second = max_per_second
        self._calls: deque[float] = deque()

    def set_caps(
        self,
        max_per_minute: int,
        max_per_second: int | None = None,
    ) -> None:
        self._max_per_minute = max(1, max_per_minute)
        if max_per_second is None:
            self._max_per_second = per_second_cap_for_minute(self._max_per_minute)
        else:
            self._max_per_second = max(1, max_per_second)
        self._calls.clear()

    def acquire(self) -> None:
        while True:
            now = monotonic()
            while self._calls and self._calls[0] <= now - 60.0:
                self._calls.popleft()
            if len(self._calls) >= self._max_per_minute:
                wait = max(0.0, self._calls[0] + 60.0 - now)
                sleep(wait)
                continue
            in_last_second = [t for t in self._calls if t > now - 1.0]
            if len(in_last_second) >= self._max_per_second:
                wait = max(0.0, min(in_last_second) + 1.0 - now)
                sleep(wait)
                continue
            self._calls.append(monotonic())
            return
