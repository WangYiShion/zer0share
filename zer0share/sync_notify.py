"""全量 / 调度聚合通知：在抑制单步推送时供 CLI 与 scheduler 发送「每日一条」摘要。"""

from __future__ import annotations

from contextvars import ContextVar

# True 时 Notifier.send 不执行（Pipeline 单表成功摘要等被跳过）
sync_notify_suppressed: ContextVar[bool] = ContextVar(
    "sync_notify_suppressed", default=False
)

LEVEL1_ALL_SUCCESS_MESSAGE = "当日全部 Level1 数据同步成功。"

LEVEL1_FAILURE_HEADER = "以下 Level1 数据接口同步失败："


def format_level1_failure_message(names_and_details: list[tuple[str, str]]) -> str:
    lines = [LEVEL1_FAILURE_HEADER, *[f"- {n}: {d}" for n, d in names_and_details]]
    return "\n".join(lines)
