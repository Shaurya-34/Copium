#!/usr/bin/env python3
"""
CloudCFO Slack Demo Script
----------------------------
Sends realistic sample alerts to your Slack channel to verify
the integration is working. Run this after configuring your .env file.

Usage:
    python demo_slack.py --test          # Test webhook connection
    python demo_slack.py --anomaly       # Send a sample anomaly alert
    python demo_slack.py --idle          # Send idle resource alerts
    python demo_slack.py --summary       # Send a daily summary
    python demo_slack.py --full          # Send a full alert with everything
    python demo_slack.py --all           # Run all demos
"""

import argparse
import sys
from datetime import datetime

# Allow running from the cloudcfo/ directory
sys.path.insert(0, ".")

from config.settings import slack_settings
from automation.slack.models import (
    AlertPayload,
    AlertSeverity,
    CostAnomaly,
    IdleResource,
    RemediationAction,
)
from automation.slack.alert_service import AlertService


def create_sample_anomalies() -> list[CostAnomaly]:
    """Generate realistic sample anomalies."""
    return [
        CostAnomaly(
            service="EC2",
            anomaly_score=0.94,
            current_daily_cost=487.50,
            expected_daily_cost=125.00,
            reason_code="Sudden spike in c5.2xlarge On-Demand usage",
            region="us-east-1",
            account_id="123456789012",
        ),
        CostAnomaly(
            service="S3",
            anomaly_score=0.82,
            current_daily_cost=78.30,
            expected_daily_cost=15.00,
            reason_code="Unusual PutObject volume in data-lake bucket",
            region="us-east-1",
        ),
        CostAnomaly(
            service="CloudFront",
            anomaly_score=0.71,
            current_daily_cost=210.00,
            expected_daily_cost=95.00,
            reason_code="Traffic surge — possible DDoS or viral content",
            region="global",
        ),
    ]


def create_sample_idle_resources() -> list[IdleResource]:
    """Generate realistic idle resource data."""
    return [
        IdleResource(
            resource_id="i-0a1b2c3d4e5f67890",
            resource_type="EC2 Instance (m5.xlarge)",
            avg_cpu_pct=0.8,
            hourly_cost=0.192,
            idle_hours=168,
            region="us-west-2",
            tags={"Name": "staging-api-server", "Team": "backend"},
        ),
        IdleResource(
            resource_id="vol-0f1e2d3c4b5a6789",
            resource_type="EBS Volume (500 GB gp3)",
            avg_cpu_pct=0.0,
            hourly_cost=0.055,
            idle_hours=720,
            region="us-east-1",
            tags={"Name": "old-db-snapshot-volume"},
        ),
        IdleResource(
            resource_id="i-0deadbeef1234567",
            resource_type="EC2 Instance (t3.medium)",
            avg_cpu_pct=2.1,
            hourly_cost=0.0416,
            idle_hours=336,
            region="eu-west-1",
            tags={"Name": "test-runner-01", "Team": "qa"},
        ),
    ]


def create_sample_actions() -> list[RemediationAction]:
    """Generate realistic remediation actions."""
    return [
        RemediationAction(
            action_id="act-ec2-stop-001",
            action_type="stop_instance",
            resource_id="i-0a1b2c3d4e5f67890",
            estimated_monthly_savings=140.16,
            risk_level="low",
            description="Stop idle staging API server (m5.xlarge)",
        ),
        RemediationAction(
            action_id="act-ebs-del-001",
            action_type="delete_volume",
            resource_id="vol-0f1e2d3c4b5a6789",
            estimated_monthly_savings=40.15,
            risk_level="medium",
            description="Delete orphaned EBS volume (500 GB)",
        ),
        RemediationAction(
            action_id="act-ec2-right-001",
            action_type="rightsize",
            resource_id="i-0deadbeef1234567",
            estimated_monthly_savings=15.33,
            risk_level="low",
            description="Downsize test-runner from t3.medium → t3.micro",
        ),
    ]


def demo_test_connection(service: AlertService):
    """Test the webhook connection."""
    print("🔗 Testing Slack webhook connection...")
    if service.test_connection():
        print("   ✅ Connection successful! Check your Slack channel.")
    else:
        print("   ❌ Connection failed. Check your SLACK_WEBHOOK_URL in .env")
        sys.exit(1)


def demo_anomaly_alert(service: AlertService):
    """Send a sample anomaly alert."""
    print("🔍 Sending anomaly alert...")
    anomaly = create_sample_anomalies()[0]
    if service.send_anomaly_alert(anomaly):
        print("   ✅ Anomaly alert sent!")
    else:
        print("   ❌ Failed to send anomaly alert.")


def demo_idle_resources(service: AlertService):
    """Send idle resource alerts."""
    print("💤 Sending idle resource alert...")
    resources = create_sample_idle_resources()
    if service.send_idle_resource_alert(resources):
        print(f"   ✅ Idle resource alert sent ({len(resources)} resources)!")
    else:
        print("   ❌ Failed to send idle resource alert.")


def demo_daily_summary(service: AlertService):
    """Send a daily summary."""
    print("📊 Sending daily summary...")
    if service.send_daily_summary(
        total_cost=1247.83,
        top_services=[
            ("EC2", 487.50),
            ("RDS", 312.00),
            ("S3", 178.30),
            ("CloudFront", 210.00),
            ("Lambda", 60.03),
        ],
        anomaly_count=3,
        idle_count=5,
        savings_total=645.64,
    ):
        print("   ✅ Daily summary sent!")
    else:
        print("   ❌ Failed to send daily summary.")


def demo_full_alert(service: AlertService):
    """Send a full alert with all components."""
    print("🚨 Sending full alert...")
    payload = AlertPayload(
        title="CloudCFO Alert: Multiple Issues Detected",
        summary=(
            "Your AWS account has *3 cost anomalies*, "
            "*3 idle resources*, and *$645/mo* in potential savings.\n"
            "Review the details below and take action."
        ),
        severity=AlertSeverity.CRITICAL,
        anomalies=create_sample_anomalies(),
        idle_resources=create_sample_idle_resources(),
        actions=create_sample_actions(),
        total_potential_savings=645.64,
        forecast_month_end=4850.00,
    )
    if service.send_alert(payload):
        print("   ✅ Full alert sent!")
    else:
        print("   ❌ Failed to send full alert.")


def main():
    parser = argparse.ArgumentParser(description="CloudCFO Slack Demo")
    parser.add_argument("--test", action="store_true", help="Test connection")
    parser.add_argument("--anomaly", action="store_true", help="Send anomaly alert")
    parser.add_argument("--idle", action="store_true", help="Send idle resource alert")
    parser.add_argument("--summary", action="store_true", help="Send daily summary")
    parser.add_argument("--full", action="store_true", help="Send full alert")
    parser.add_argument("--all", action="store_true", help="Run all demos")
    args = parser.parse_args()

    # Default to --all if no args
    if not any(vars(args).values()):
        args.all = True

    print()
    print("╔════════════════════════════════════════╗")
    print("║   CloudCFO — Slack Integration Demo    ║")
    print("╚════════════════════════════════════════╝")
    print()

    try:
        service = AlertService()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("   → Make sure your .env file is configured correctly.")
        print("   → Copy .env.example to .env and fill in your Slack webhook URL.")
        sys.exit(1)

    if args.all or args.test:
        demo_test_connection(service)
        print()

    if args.all or args.anomaly:
        demo_anomaly_alert(service)
        print()

    if args.all or args.idle:
        demo_idle_resources(service)
        print()

    if args.all or args.summary:
        demo_daily_summary(service)
        print()

    if args.all or args.full:
        demo_full_alert(service)
        print()

    print("✨ Done! Check your Slack channel for the messages.")


if __name__ == "__main__":
    main()
