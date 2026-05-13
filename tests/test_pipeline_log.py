"""pipeline.log 纯文本成功行与修剪逻辑。"""

from datetime import date, timedelta
from pathlib import Path

from zer0share.pipeline_log import (
    SUCCESS_LINE_RE,
    append_plain_success_line,
    distinct_success_dates_in_file,
    trim_success_records_if_needed,
)


def test_success_line_regex_matches_plain_only():
    assert SUCCESS_LINE_RE.match("2026-05-13 同步成功")
    assert SUCCESS_LINE_RE.match("2026-05-13 同步成功  ")
    assert SUCCESS_LINE_RE.match("2026-05-13 同步成功 extra") is None
    assert (
        SUCCESS_LINE_RE.match("2026-05-13 12:00:00 | ERROR | x | 2026-05-13 同步成功")
        is None
    )


def test_trim_removes_success_lines_when_seven_distinct_days(tmp_path: Path):
    log = tmp_path / "pipeline.log"
    lines = []
    base = date(2026, 1, 1)
    for i in range(7):
        d = base + timedelta(days=i)
        lines.append(f"{d.isoformat()} 同步成功\n")
    lines.append("2026-05-13 12:00:00 | ERROR | something failed\n")
    log.write_text("".join(lines), encoding="utf-8")

    trim_success_records_if_needed(log, min_distinct_days=7)

    body = log.read_text(encoding="utf-8")
    assert "同步成功" not in body
    assert "something failed" in body


def test_trim_noop_below_threshold(tmp_path: Path):
    log = tmp_path / "pipeline.log"
    log.write_text("2026-01-01 同步成功\n2026-01-02 同步成功\n", encoding="utf-8")
    trim_success_records_if_needed(log, min_distinct_days=7)
    assert "2026-01-01 同步成功" in log.read_text(encoding="utf-8")


def test_distinct_success_dates_counts_unique_days(tmp_path: Path):
    log = tmp_path / "pipeline.log"
    log.write_text("2026-01-01 同步成功\n2026-01-01 同步成功\n", encoding="utf-8")
    assert distinct_success_dates_in_file(log) == {"2026-01-01"}


def test_append_plain_success_line(tmp_path: Path):
    log = tmp_path / "logs" / "pipeline.log"
    append_plain_success_line(log, date(2026, 5, 13))
    assert log.read_text(encoding="utf-8") == "2026-05-13 同步成功\n"
