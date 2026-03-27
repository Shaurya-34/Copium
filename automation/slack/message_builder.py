"""
CloudCFO — Slack Message Builder
-----------------------------------
Constructs Block Kit JSON payloads for different alert types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import (
    AlertPayload,
    AlertSeverity,
    CostAnomaly,
    IdleResource,
    RemediationAction,
)


class MessageBuilder:
    """Static methods that produce Slack Block Kit JSON dictionaries."""

    # ── Full alert ─────────────────────────────────────────────

    @staticmethod
    def build_alert(payload: AlertPayload) -> dict[str, Any]:
        """Build a comprehensive alert message."""
        blocks: list[dict] = []

        # Header
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{payload.severity.emoji} {payload.title}",
                    "emoji": True,
                },
            }
        )

        # Summary
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": payload.summary},
            }
        )

        blocks.append({"type": "divider"})

        # Anomalies
        if payload.anomalies:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*🔍 Cost Anomalies ({len(payload.anomalies)})*",
                    },
                }
            )
            for a in payload.anomalies:
                blocks.append(MessageBuilder._anomaly_block(a))

        # Idle resources
        if payload.idle_resources:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*💤 Idle Resources ({len(payload.idle_resources)})*",
                    },
                }
            )
            for r in payload.idle_resources:
                blocks.append(MessageBuilder._idle_block(r))

        # Actions
        if payload.actions:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*🔧 Suggested Fixes*",
                    },
                }
            )
            for act in payload.actions:
                blocks.append(MessageBuilder._action_block(act))

        # Savings footer
        if payload.total_potential_savings > 0:
            blocks.append({"type": "divider"})
            savings_text = f"💰 *Total potential savings:* ${payload.total_potential_savings:,.2f}/mo"
            if payload.forecast_month_end:
                savings_text += (
                    f"\n📈 *Forecasted month-end spend:* ${payload.forecast_month_end:,.2f}"
                )
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": savings_text},
                }
            )

        # Context footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"CloudCFO • Generated {payload.generated_at:%Y-%m-%d %H:%M UTC}"
                        ),
                    }
                ],
            }
        )

        return {
            "attachments": [
                {
                    "color": payload.severity.color,
                    "blocks": blocks,
                }
            ]
        }

    # ── Simple alert ───────────────────────────────────────────

    @staticmethod
    def build_simple_alert(
        title: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.INFO,
    ) -> dict[str, Any]:
        """Build a minimal alert with just a title and message."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{severity.emoji} {title}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"CloudCFO • {datetime.utcnow():%Y-%m-%d %H:%M UTC}",
                    }
                ],
            },
        ]
        return {
            "attachments": [
                {
                    "color": severity.color,
                    "blocks": blocks,
                }
            ]
        }

    # ── Daily summary ──────────────────────────────────────────

    @staticmethod
    def build_daily_summary(
        total_cost: float,
        top_services: list[tuple[str, float]],
        anomaly_count: int = 0,
        idle_count: int = 0,
        savings_total: float = 0.0,
    ) -> dict[str, Any]:
        """Build a daily cost summary message."""
        service_lines = "\n".join(
            f"  • *{name}*: ${cost:,.2f}" for name, cost in top_services
        )
        summary_text = (
            f"*Today's spend:* ${total_cost:,.2f}\n\n"
            f"*Top services:*\n{service_lines}\n\n"
            f"*Anomalies detected:* {anomaly_count}\n"
            f"*Idle resources:* {idle_count}\n"
            f"*Potential monthly savings:* ${savings_total:,.2f}"
        )

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "📊 CloudCFO Daily Cost Summary",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": summary_text},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"CloudCFO • {datetime.utcnow():%Y-%m-%d %H:%M UTC}",
                    }
                ],
            },
        ]
        return {
            "attachments": [
                {
                    "color": "#36a64f",
                    "blocks": blocks,
                }
            ]
        }

    # ── Private block builders ─────────────────────────────────

    @staticmethod
    def _anomaly_block(anomaly: CostAnomaly) -> dict:
        return {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{anomaly.severity.emoji} *{anomaly.service}* "
                    f"({anomaly.region})\n"
                    f"  Cost: ${anomaly.current_daily_cost:,.2f}/day "
                    f"(expected ${anomaly.expected_daily_cost:,.2f}  •  "
                    f"+{anomaly.cost_increase_pct:.0f}%)\n"
                    f"  _{anomaly.reason_code}_"
                ),
            },
        }

    @staticmethod
    def _idle_block(resource: IdleResource) -> dict:
        name = resource.tags.get("Name", resource.resource_id)
        return {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"• *{name}* ({resource.resource_type})\n"
                    f"  CPU: {resource.avg_cpu_pct:.1f}%  •  "
                    f"Idle: {resource.idle_hours}h  •  "
                    f"Wasted: ${resource.wasted_cost:,.2f}"
                ),
            },
        }

    @staticmethod
    def _action_block(action: RemediationAction) -> dict:
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(
            action.risk_level, "⚪"
        )
        return {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{risk_emoji} {action.description}\n"
                    f"  Saves ~${action.estimated_monthly_savings:,.2f}/mo  •  "
                    f"Risk: {action.risk_level}"
                ),
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "🔧 Fix",
                    "emoji": True,
                },
                "value": action.action_id,
                "action_id": f"fix_{action.action_id}",
                "style": "primary" if action.risk_level == "low" else "danger",
            },
        }
