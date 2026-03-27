"""
CloudCFO — Slack Webhook Client
----------------------------------
Thin wrapper around Slack Incoming Webhooks with retry logic,
rate-limit handling, and URL validation.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class SlackWebhookError(Exception):
    """Raised when a Slack webhook request fails."""

    def __init__(self, status_code: int, response_text: str):
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(
            f"Slack webhook error (HTTP {status_code}): {response_text}"
        )


class SlackWebhook:
    """Sends JSON payloads to a Slack Incoming Webhook URL."""

    VALID_URL_PREFIX = "https://hooks.slack.com/"

    def __init__(
        self,
        webhook_url: str,
        timeout: int = 10,
        max_retries: int = 3,
    ):
        if not webhook_url or not webhook_url.startswith(self.VALID_URL_PREFIX):
            raise ValueError(
                f"Invalid Slack webhook URL. Must start with {self.VALID_URL_PREFIX}"
            )

        self._url = webhook_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ── Public API ─────────────────────────────────────────────

    def send(self, payload: dict[str, Any]) -> bool:
        """Send a JSON payload. Returns True on success. Raises on hard errors."""
        attempt = 0
        while attempt < self._max_retries:
            attempt += 1
            try:
                response = self._session.post(
                    self._url,
                    json=payload,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                logger.warning("Slack request failed (attempt %d): %s", attempt, exc)
                if attempt >= self._max_retries:
                    raise SlackWebhookError(0, str(exc)) from exc
                time.sleep(1)
                continue

            if response.status_code == 200:
                return True

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "1"))
                logger.info(
                    "Rate limited by Slack. Retrying in %ds (attempt %d)",
                    retry_after,
                    attempt,
                )
                time.sleep(retry_after)
                continue

            # Non-retryable error
            raise SlackWebhookError(response.status_code, response.text)

        raise SlackWebhookError(0, "Max retries exceeded")

    def test(self) -> bool:
        """Send a lightweight test message. Returns True on success."""
        try:
            return self.send({"text": "✅ CloudCFO webhook test — connection OK!"})
        except SlackWebhookError:
            return False
