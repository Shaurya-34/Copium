"""
CloudCFO — Alert Service
--------------------------
High-level API that combines the webhook client and message builder.
This is the primary interface used by the demo script and future
automation pipelines.
"""

from __future__ import annotations

import logging
from typing import Optional

from config.settings import slack_settings
from .message_builder import MessageBuilder
from .models import (
    AlertPayload,
    AlertSeverity,
    CostAnomaly,
    IdleResource,
)
from .webhook import SlackWebhook, SlackWebhookError

logger = logging.getLogger(__name__)


class AlertService:
    """Orchestrates building and sending Slack alerts."""

    def __init__(self, webhook_url: Optional[str] = None):
        url = webhook_url or slack_settings.webhook_url
        self._webhook = SlackWebhook(
            webhook_url=url,
            timeout=slack_settings.timeout_seconds,
            max_retries=slack_settings.max_retries,
        )

    # ── Public API ─────────────────────────────────────────────

    def test_connection(self) -> bool:
        """Test that the webhook is reachable."""
        return self._webhook.test()

    def send_alert(self, payload: AlertPayload) -> bool:
        """Send a full composite alert."""
        msg = MessageBuilder.build_alert(payload)
        return self._safe_send(msg)

    def send_anomaly_alert(self, anomaly: CostAnomaly) -> bool:
        """Send a single anomaly alert."""
        msg = MessageBuilder.build_simple_alert(
            title=f"Cost Anomaly: {anomaly.service}",
            message=(
                f"*{anomaly.service}* ({anomaly.region}) cost spiked "
                f"*+{anomaly.cost_increase_pct:.0f}%*\n"
                f"Current: ${anomaly.current_daily_cost:,.2f}/day  •  "
                f"Expected: ${anomaly.expected_daily_cost:,.2f}/day\n"
                f"_{anomaly.reason_code}_"
            ),
            severity=anomaly.severity,
        )
        return self._safe_send(msg)

    def send_idle_resource_alert(self, resources: list[IdleResource]) -> bool:
        """Send an idle-resource digest."""
        total_waste = sum(r.monthly_waste_estimate for r in resources)
        lines = [
            f"Found *{len(resources)}* idle resources "
            f"wasting an estimated *${total_waste:,.2f}/mo*.\n"
        ]
        for r in resources:
            name = r.tags.get("Name", r.resource_id)
            lines.append(
                f"• *{name}* ({r.resource_type}) — "
                f"{r.avg_cpu_pct:.1f}% CPU, idle {r.idle_hours}h, "
                f"~${r.monthly_waste_estimate:,.2f}/mo"
            )

        msg = MessageBuilder.build_simple_alert(
            title="Idle Resources Detected",
            message="\n".join(lines),
            severity=AlertSeverity.WARNING,
        )
        return self._safe_send(msg)

    def send_daily_summary(
        self,
        total_cost: float,
        top_services: list[tuple[str, float]],
        anomaly_count: int = 0,
        idle_count: int = 0,
        savings_total: float = 0.0,
    ) -> bool:
        """Send a daily cost summary."""
        msg = MessageBuilder.build_daily_summary(
            total_cost=total_cost,
            top_services=top_services,
            anomaly_count=anomaly_count,
            idle_count=idle_count,
            savings_total=savings_total,
        )
        return self._safe_send(msg)

    # ── Internal ───────────────────────────────────────────────

    def _safe_send(self, payload: dict) -> bool:
        """Send with error handling. Returns False instead of raising."""
        try:
            return self._webhook.send(payload)
        except SlackWebhookError as exc:
            logger.error("Failed to send Slack alert: %s", exc)
            return False
