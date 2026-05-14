import os

import httpx
from loguru import logger

from zer0share.sync_notify import sync_notify_suppressed

PUSHPLUS_SEND_URL = "https://www.pushplus.plus/send"


PUSHPLUS_DEFAULT_TITLE = "zer0share"


class Notifier:
    def __init__(self, webhook_url: str, enabled: bool):
        self._url = webhook_url
        self._enabled = enabled
        self._pushplus_token = os.environ.get("PUSHPLUS_TOKEN", "").strip()

    def send(self, message: str, *, pushplus_title: str | None = None) -> None:
        if sync_notify_suppressed.get():
            return
        text = f"[zer0share] {message}"
        if self._enabled:
            payload = {
                "msgtype": "text",
                "text": {"content": text},
            }
            try:
                resp = httpx.post(self._url, json=payload, timeout=10)
                resp.raise_for_status()
            except httpx.RequestError as e:
                logger.error(f"企业微信推送失败: {e}")
            except httpx.HTTPStatusError as e:
                logger.error(f"企业微信返回错误: {e.response.status_code}")
        self._send_pushplus(text, title=pushplus_title or PUSHPLUS_DEFAULT_TITLE)

    def _send_pushplus(self, content: str, *, title: str) -> None:
        if not self._pushplus_token:
            return
        body = {
            "token": self._pushplus_token,
            "title": title,
            "content": content,
            "template": "txt",
        }
        try:
            resp = httpx.post(PUSHPLUS_SEND_URL, json=body, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 200:
                logger.error(f"pushplus 推送失败：{payload}")
        except ValueError as e:
            logger.error(f"pushplus 响应非 JSON：{e}")
        except httpx.RequestError as e:
            logger.error(f"pushplus 请求失败: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"pushplus 返回错误: {e.response.status_code}")
