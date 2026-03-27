"""
Tests for CloudCFO Slack Integration (Phase 1)
-----------------------------------------------
Tests models, message building, and webhook behavior.
Run with: pytest automation/tests/ -v
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from automation.slack.models import (
    AlertPayload,
    AlertSeverity,
    CostAnomaly,
    IdleResource,
    RemediationAction,
)
from automation.slack.message_builder import MessageBuilder
from automation.slack.webhook import SlackWebhook, SlackWebhookError


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def sample_anomaly() -> CostAnomaly:
    return CostAnomaly(
        service="EC2",
        anomaly_score=0.92,
        current_daily_cost=450.00,
        expected_daily_cost=120.00,
        reason_code="Sudden spike in c5.2xlarge On-Demand usage",
        region="us-east-1",
        account_id="123456789012",
    )


@pytest.fixture
def sample_idle_resource() -> IdleResource:
    return IdleResource(
        resource_id="i-0abc123def456",
        resource_type="EC2 Instance",
        avg_cpu_pct=1.2,
        hourly_cost=0.34,
        idle_hours=72,
        region="us-west-2",
        tags={"Name": "test-server", "Team": "backend"},
    )


@pytest.fixture
def sample_action() -> RemediationAction:
    return RemediationAction(
        action_id="act-001",
        action_type="stop_instance",
        resource_id="i-0abc123def456",
        estimated_monthly_savings=248.20,
        risk_level="low",
        description="Stop idle EC2 instance i-0abc123def456",
    )


@pytest.fixture
def sample_payload(sample_anomaly, sample_idle_resource, sample_action):
    return AlertPayload(
        title="CloudCFO Alert: Cost Spike Detected",
        summary="Multiple cost anomalies detected in your AWS account.",
        severity=AlertSeverity.CRITICAL,
        anomalies=[sample_anomaly],
        idle_resources=[sample_idle_resource],
        actions=[sample_action],
        total_potential_savings=248.20,
        forecast_month_end=4500.00,
    )


# ── Model Tests ─────────────────────────────────────────────


class TestCostAnomaly:
    def test_cost_increase_pct(self, sample_anomaly):
        # (450 - 120) / 120 * 100 = 275%
        assert abs(sample_anomaly.cost_increase_pct - 275.0) < 0.1

    def test_severity_critical(self, sample_anomaly):
        assert sample_anomaly.severity == AlertSeverity.CRITICAL

    def test_severity_warning(self):
        anomaly = CostAnomaly(
            service="S3",
            anomaly_score=0.75,
            current_daily_cost=50.0,
            expected_daily_cost=30.0,
            reason_code="Increased PutObject calls",
        )
        assert anomaly.severity == AlertSeverity.WARNING

    def test_severity_info(self):
        anomaly = CostAnomaly(
            service="S3",
            anomaly_score=0.3,
            current_daily_cost=35.0,
            expected_daily_cost=30.0,
            reason_code="Normal fluctuation",
        )
        assert anomaly.severity == AlertSeverity.INFO

    def test_zero_expected_cost(self):
        anomaly = CostAnomaly(
            service="Lambda",
            anomaly_score=0.95,
            current_daily_cost=50.0,
            expected_daily_cost=0.0,
            reason_code="New service with no baseline",
        )
        assert anomaly.cost_increase_pct == 100.0


class TestIdleResource:
    def test_wasted_cost(self, sample_idle_resource):
        assert sample_idle_resource.wasted_cost == 0.34 * 72

    def test_monthly_waste_estimate(self, sample_idle_resource):
        assert sample_idle_resource.monthly_waste_estimate == 0.34 * 730


class TestAlertSeverity:
    def test_colors(self):
        assert AlertSeverity.INFO.color == "#36a64f"
        assert AlertSeverity.WARNING.color == "#ff9900"
        assert AlertSeverity.CRITICAL.color == "#ff0000"

    def test_emojis(self):
        assert AlertSeverity.INFO.emoji == "ℹ️"
        assert AlertSeverity.WARNING.emoji == "⚠️"
        assert AlertSeverity.CRITICAL.emoji == "🚨"


# ── Message Builder Tests ───────────────────────────────────


class TestMessageBuilder:
    def test_build_alert_has_attachments(self, sample_payload):
        msg = MessageBuilder.build_alert(sample_payload)
        assert "attachments" in msg
        assert len(msg["attachments"]) == 1
        assert msg["attachments"][0]["color"] == AlertSeverity.CRITICAL.color

    def test_build_alert_has_blocks(self, sample_payload):
        msg = MessageBuilder.build_alert(sample_payload)
        blocks = msg["attachments"][0]["blocks"]
        assert len(blocks) > 0
        # First block should be the header
        assert blocks[0]["type"] == "header"
        assert "Cost Spike" in blocks[0]["text"]["text"]

    def test_build_simple_alert(self):
        msg = MessageBuilder.build_simple_alert(
            "Test Alert",
            "This is a test.",
            AlertSeverity.INFO,
        )
        assert "attachments" in msg
        blocks = msg["attachments"][0]["blocks"]
        assert any("Test Alert" in str(b) for b in blocks)

    def test_build_daily_summary(self):
        msg = MessageBuilder.build_daily_summary(
            total_cost=142.50,
            top_services=[("EC2", 80.0), ("S3", 40.0), ("Lambda", 22.5)],
            anomaly_count=2,
            idle_count=3,
            savings_total=320.0,
        )
        assert "attachments" in msg
        blocks = msg["attachments"][0]["blocks"]
        content = json.dumps(blocks)
        assert "$142.50" in content
        assert "EC2" in content

    def test_action_block_has_button(self, sample_action):
        block = MessageBuilder._action_block(sample_action)
        assert "accessory" in block
        assert block["accessory"]["type"] == "button"
        assert block["accessory"]["value"] == "act-001"


# ── Webhook Tests ───────────────────────────────────────────


class TestSlackWebhook:
    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Invalid Slack webhook URL"):
            SlackWebhook("https://example.com/not-slack")

    def test_empty_url_raises(self):
        with pytest.raises(ValueError):
            SlackWebhook("")

    @patch("automation.slack.webhook.requests.Session.post")
    def test_send_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_post.return_value = mock_response

        webhook = SlackWebhook("https://hooks.slack.com/services/T/B/X")
        assert webhook.send({"text": "test"}) is True

    @patch("automation.slack.webhook.requests.Session.post")
    def test_send_error_raises(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_payload"
        mock_post.return_value = mock_response

        webhook = SlackWebhook("https://hooks.slack.com/services/T/B/X")
        with pytest.raises(SlackWebhookError):
            webhook.send({"text": "test"})

    @patch("automation.slack.webhook.requests.Session.post")
    def test_rate_limit_retry(self, mock_post):
        # First call: rate limited, second call: success
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "1"}
        rate_limited.text = "rate_limited"

        success = MagicMock()
        success.status_code = 200
        success.text = "ok"

        mock_post.side_effect = [rate_limited, success]

        webhook = SlackWebhook("https://hooks.slack.com/services/T/B/X")
        assert webhook.send({"text": "test"}) is True
        assert mock_post.call_count == 2
