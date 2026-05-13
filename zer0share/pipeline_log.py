"""pipeline.log 中的「同步成功」纯文本行与按自然日数量的修剪逻辑。"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

# 与 loguru 混排时仅匹配整行「YYYY-MM-DD 同步成功」，不误删带时间戳的 loguru 行
SUCCESS_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) 同步成功\s*$")

# 达到该数量的不同「同步成功」自然日时，于下次同步开始时清空所有纯文本成功行
DEFAULT_SUCCESS_TRIM_THRESHOLD_DAYS = 7


def distinct_success_dates_in_file(log_path: Path) -> set[str]:
    if not log_path.is_file():
        return set()
    dates: set[str] = set()
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        m = SUCCESS_LINE_RE.match(raw.strip())
        if m:
            dates.add(m.group(1))
    return dates


def trim_success_records_if_needed(
    log_path: Path, *, min_distinct_days: int = DEFAULT_SUCCESS_TRIM_THRESHOLD_DAYS
) -> None:
    """若已累积不少于 min_distinct_days 个「同步成功」自然日，则删除所有纯文本成功行（保留 loguru 与其它内容）。"""
    if not log_path.is_file():
        return
    raw = log_path.read_text(encoding="utf-8")
    parts = raw.splitlines(keepends=True)
    success_dates: set[str] = set()
    for line in parts:
        m = SUCCESS_LINE_RE.match(line.strip())
        if m:
            success_dates.add(m.group(1))
    if len(success_dates) < min_distinct_days:
        return
    kept = [line for line in parts if not SUCCESS_LINE_RE.match(line.strip())]
    log_path.write_text("".join(kept), encoding="utf-8")


def today_plain_success_exists(log_path: Path, d: date) -> bool:
    needle = f"{d.isoformat()} 同步成功"
    if not log_path.is_file():
        return False
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip() == needle:
            return True
    return False


def append_plain_success_line(log_path: Path, d: date) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"{d.isoformat()} 同步成功\n")
