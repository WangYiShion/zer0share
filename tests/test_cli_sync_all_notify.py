from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from zer0share.cli import cli
from zer0share.sync_notify import (
    LEVEL1_ALL_SUCCESS_MESSAGE,
    LEVEL1_PUSHPLUS_TITLE_FAILURE,
    LEVEL1_PUSHPLUS_TITLE_SUCCESS,
    format_level1_failure_message,
)


def test_format_level1_failure_message_joins_lines():
    s = format_level1_failure_message([("a", "boom"), ("b", "x")])
    assert "a" in s and "boom" in s and "b" in s and "x" in s
    assert s.count("\n") >= 2


def test_sync_all_sends_single_success_notify():
    runner = CliRunner()
    pipeline = MagicMock()
    pipeline._cfg.log_path = MagicMock()
    pipeline._cfg.log_path.parent.mkdir = MagicMock()
    pipeline._cfg.log_path.is_file.return_value = False
    pipeline.__enter__.return_value = pipeline
    pipeline.__exit__.return_value = False

    with (
        patch("zer0share.cli._make_pipeline", return_value=pipeline),
        patch("zer0share.cli.trim_success_records_if_needed"),
        patch("zer0share.cli.today_plain_success_exists", return_value=False),
        patch("zer0share.cli.append_plain_success_line") as mock_append,
    ):
        result = runner.invoke(cli, ["sync", "--all"])

    assert result.exit_code == 0
    pipeline.sync_trade_cal.assert_called_once()
    mock_append.assert_called_once()
    pipeline._notifier.send.assert_called_once_with(
        LEVEL1_ALL_SUCCESS_MESSAGE,
        pushplus_title=LEVEL1_PUSHPLUS_TITLE_SUCCESS,
    )


def test_sync_all_sends_aggregated_failure_notify():
    runner = CliRunner()
    pipeline = MagicMock()
    pipeline._cfg.log_path = MagicMock()
    pipeline.__enter__.return_value = pipeline
    pipeline.__exit__.return_value = False

    def boom():
        raise RuntimeError("nope")

    pipeline.sync_trade_cal.side_effect = boom

    with (
        patch("zer0share.cli._make_pipeline", return_value=pipeline),
        patch("zer0share.cli.trim_success_records_if_needed"),
    ):
        result = runner.invoke(cli, ["sync", "--all"])

    assert result.exit_code != 0
    pipeline._notifier.send.assert_called_once()
    assert (
        pipeline._notifier.send.call_args.kwargs.get("pushplus_title")
        == LEVEL1_PUSHPLUS_TITLE_FAILURE
    )
    msg = pipeline._notifier.send.call_args[0][0]
    assert "trade_cal" in msg
    assert "nope" in msg
