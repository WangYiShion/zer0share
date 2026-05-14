import pytest
import httpx
from unittest.mock import patch, MagicMock

from zer0share.notifier import Notifier, PUSHPLUS_SEND_URL
from zer0share.sync_notify import sync_notify_suppressed


@pytest.fixture(autouse=True)
def clear_pushplus_token(monkeypatch):
    monkeypatch.delenv("PUSHPLUS_TOKEN", raising=False)


def test_send_suppressed_skips_all_http(monkeypatch):
    monkeypatch.setenv("PUSHPLUS_TOKEN", "pptoken")
    n = Notifier(webhook_url="https://example.com/hook", enabled=True)
    tok = sync_notify_suppressed.set(True)
    try:
        with patch("httpx.post") as mock_post:
            n.send("x")
            mock_post.assert_not_called()
    finally:
        sync_notify_suppressed.reset(tok)


def test_pushplus_uses_custom_title_when_passed(monkeypatch):
    monkeypatch.setenv("PUSHPLUS_TOKEN", "pptoken")
    n = Notifier(webhook_url="https://example.com", enabled=False)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"code": 200}
    with patch("httpx.post", return_value=mock_response) as mock_post:
        n.send("body", pushplus_title="当日全部 Level1 数据同步失败")
    assert mock_post.call_args[1]["json"]["title"] == "当日全部 Level1 数据同步失败"


def test_send_disabled_does_not_call_http():
    n = Notifier(webhook_url="https://example.com", enabled=False)
    with patch("httpx.post") as mock_post:
        n.send("test message")
        mock_post.assert_not_called()


def test_send_enabled_posts_correct_payload():
    n = Notifier(webhook_url="https://example.com/hook", enabled=True)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    with patch("httpx.post", return_value=mock_response) as mock_post:
        n.send("同步完成：成功 5 天")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["msgtype"] == "text"
        assert "同步完成" in payload["text"]["content"]
        assert "[zer0share]" in payload["text"]["content"]


def test_send_request_error_does_not_raise():
    n = Notifier(webhook_url="https://example.com/hook", enabled=True)
    with patch("httpx.post", side_effect=httpx.RequestError("network error", request=MagicMock())):
        n.send("告警消息")  # 不应抛出异常


def test_send_http_error_does_not_raise():
    n = Notifier(webhook_url="https://example.com/hook", enabled=True)
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "400 Bad Request", request=MagicMock(), response=MagicMock(status_code=400)
    )
    with patch("httpx.post", return_value=mock_response):
        n.send("告警消息")  # 不应抛出异常


def test_pushplus_sends_when_token_set(monkeypatch):
    monkeypatch.setenv("PUSHPLUS_TOKEN", "pptoken")
    n = Notifier(webhook_url="https://example.com/hook", enabled=False)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"code": 200}
    with patch("httpx.post", return_value=mock_response) as mock_post:
        n.send("hello")
    mock_post.assert_called_once()
    assert mock_post.call_args[0][0] == PUSHPLUS_SEND_URL
    body = mock_post.call_args[1]["json"]
    assert body["token"] == "pptoken"
    assert body["title"] == "zer0share"
    assert "[zer0share]" in body["content"]
    assert "hello" in body["content"]
    assert body["template"] == "txt"


def test_pushplus_business_error_logged(monkeypatch):
    monkeypatch.setenv("PUSHPLUS_TOKEN", "pptoken")
    n = Notifier(webhook_url="https://example.com/hook", enabled=False)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"code": 500, "msg": "fail"}
    with patch("httpx.post", return_value=mock_response), patch("zer0share.notifier.logger.error") as log_err:
        n.send("x")
    assert log_err.called
    assert "pushplus" in log_err.call_args[0][0]


def test_wecom_and_pushplus_when_both_active(monkeypatch):
    monkeypatch.setenv("PUSHPLUS_TOKEN", "pptoken")
    n = Notifier(webhook_url="https://example.com/hook", enabled=True)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"code": 200}
    with patch("httpx.post", return_value=mock_response) as mock_post:
        n.send("ping")
    assert mock_post.call_count == 2
    urls = [call[0][0] for call in mock_post.call_args_list]
    assert PUSHPLUS_SEND_URL in urls
    assert "https://example.com/hook" in urls


def test_pushplus_invalid_json_logged(monkeypatch):
    monkeypatch.setenv("PUSHPLUS_TOKEN", "pptoken")
    n = Notifier(webhook_url="https://example.com", enabled=False)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.side_effect = ValueError("not json")
    with patch("httpx.post", return_value=mock_response), patch("zer0share.notifier.logger.error") as log_err:
        n.send("x")
    log_err.assert_called()
