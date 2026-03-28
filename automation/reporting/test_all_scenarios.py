import logging
from config.settings import slack_settings
from automation.slack.webhook import SlackWebhook
from automation.slack.models import CostAnomaly, AlertSeverity, RemediationAction, AlertPayload
from automation.slack.alert_service import AlertService

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scenario_tester")

def test_all_scenarios():
    logger.info("🚀 Launching Business Guardrail UI Test Suite...")
    
    webhook = SlackWebhook(slack_settings.webhook_url)
    service = AlertService(slack_settings.webhook_url)

    # --- Scenario A: The Zombie (CODE_101_ZOMBIE) ---
    zombie_anomaly = CostAnomaly(
        service="AmazonEC2",
        current_daily_cost=45.00,
        expected_daily_cost=5.00,
        reason_code="CODE_101_ZOMBIE",
        region="us-east-1",
        anomaly_score=0.95
    )
    zombie_action = RemediationAction(
        action_id="STOP_INSTANCE:i-zombie123:CODE_101_ZOMBIE",
        action_type="STOP_INSTANCE",
        resource_id="i-zombie123",
        estimated_monthly_savings=1350.00,
        risk_level="high",
        description="CPU usage < 1% for 72 hours."
    )
    zombie_payload = AlertPayload(
        title="ML Alert: Zombie Resource Detected",
        summary="A non-prod instance is burning budget with near-zero utilization.",
        severity=AlertSeverity.CRITICAL,
        anomalies=[zombie_anomaly],
        actions=[zombie_action]
    )
    service.send_alert(zombie_payload)
    logger.info("Sent Scenario A (Zombie) to Slack.")

    # --- Scenario B: Production Risk (CODE_999_PROD_FIGHT) ---
    prod_anomaly = CostAnomaly(
        service="AmazonRDS",
        current_daily_cost=250.00,
        expected_daily_cost=75.00,
        reason_code="CODE_999_PROD_FIGHT",
        region="us-west-2",
        anomaly_score=1.0
    )
    prod_action = RemediationAction(
        action_id="VIEW_CONSOLE:db-prod-main:CODE_999_PROD_FIGHT",
        action_type="MANUAL_REVIEW_REQUIRED",
        resource_id="db-prod-main",
        estimated_monthly_savings=5250.00,
        risk_level="high",
        description="Massive spike in PRODUCTION database costs. Auto-fix DISABLED."
    )
    prod_payload = AlertPayload(
        title="ML Alert: PRODUCTION COST SPIKE",
        summary="Production environment spend is out of bounds. Human intervention is mandatory.",
        severity=AlertSeverity.CRITICAL,
        anomalies=[prod_anomaly],
        actions=[prod_action]
    )
    service.send_alert(prod_payload)
    logger.info("Sent Scenario B (Production) to Slack.")

    # --- Scenario C: Security Breach (SEC_REGION_UNAUTHORIZED) ---
    sec_anomaly = CostAnomaly(
        service="AmazonEC2",
        current_daily_cost=5.00,
        expected_daily_cost=0.00,
        reason_code="SEC_REGION_UNAUTHORIZED",
        region="ap-southeast-1",
        anomaly_score=1.0
    )
    sec_action = RemediationAction(
        action_id="BLOCK_REGION:ap-southeast-1:SEC_REGION_UNAUTHORIZED",
        action_type="BLOCK_REGION_ACCESS",
        resource_id="ap-southeast-1",
        estimated_monthly_savings=150.00,
        risk_level="high",
        description="Resources detected in geofenced region. Potential account compromise."
    )
    sec_payload = AlertPayload(
        title="SECURITY ALERT: UNAUTHORIZED REGION",
        summary="Compute resources were spun up in a blacklisted region.",
        severity=AlertSeverity.CRITICAL,
        anomalies=[sec_anomaly],
        actions=[sec_action]
    )
    service.send_alert(sec_payload)
    logger.info("Sent Scenario C (Security) to Slack.")

    # --- Scenario D: Quiet Hours (CODE_104_OFF_HOURS_ACTIVITY) ---
    quiet_anomaly = CostAnomaly(
        service="Lambda",
        current_daily_cost=12.00,
        expected_daily_cost=0.50,
        reason_code="CODE_104_OFF_HOURS_ACTIVITY",
        region="us-east-1",
        anomaly_score=0.75
    )
    quiet_action = RemediationAction(
        action_id="HALT_UNTIL_MONDAY:lambda-auto-01:CODE_104_OFF_HOURS_ACTIVITY",
        action_type="HALT_UNTIL_MONDAY",
        resource_id="lambda-auto-01",
        estimated_monthly_savings=360.00,
        risk_level="medium",
        description="Spike detected during weekend quiet hours (Sun 3 AM)."
    )
    quiet_payload = AlertPayload(
        title="ML Alert: Off-Hours Activity",
        summary="Automated activity detected outside of standard business hours.",
        severity=AlertSeverity.WARNING,
        anomalies=[quiet_anomaly],
        actions=[quiet_action]
    )
    service.send_alert(quiet_payload)
    logger.info("Sent Scenario D (Quiet Hours) to Slack.")

    logger.info("\n✅ UI Test Suite Complete. Check your Slack #cloud-costs channel.")

if __name__ == "__main__":
    test_all_scenarios()
