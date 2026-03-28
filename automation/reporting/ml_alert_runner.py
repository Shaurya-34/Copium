import csv
import logging
import os
from dotenv import load_dotenv

from config.settings import slack_settings
from automation.slack.webhook import SlackWebhook
from automation.slack.models import CostAnomaly, AlertSeverity, RemediationAction, AlertPayload
from automation.slack.alert_service import AlertService

# Load access keys if the ML team added them
load_dotenv(os.path.join(os.getcwd(), "ml", ".env"))

logger = logging.getLogger("ml_alert_runner")
logging.basicConfig(level=logging.INFO)

def run_ml_alerts():
    logger.info("Starting ML Anomaly Slack Dispatcher...")
    
    anomalies_file = os.path.join(os.getcwd(), "ml", "detected_anomalies.csv")
    if not os.path.exists(anomalies_file):
        logger.error(f"Cannot find {anomalies_file}. Did ml_brain.py run?")
        return
        
    service = AlertService(slack_settings.webhook_url)
    
    alert_count = 0
    max_alerts = 3 # Prevent spamming the channel with hundreds of mock anomalies
    
    with open(anomalies_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            severity = row.get("severity", "NORMAL")
            
            # We only alert on actual ML hits
            if severity in ["CRITICAL", "WARNING"]:
                
                if alert_count >= max_alerts:
                    logger.info("Reached maximum MVP alert threshold. Stopping further dispatches.")
                    break
                    
                alert_count += 1
                
                # Assemble the CostAnomaly object
                service_name = row.get("service", "Unknown AWS Service")
                anomaly_code = row.get("anomaly_code", "GENERIC_ANOMALY")
                suggested_action = row.get("suggested_action", "INVESTIGATE")
                
                # Combine codes into the action ID for the UI logic to catch
                action_value = f"{suggested_action}:{row.get('resource_id')}:{anomaly_code}"
                cost_usd = float(row.get("cost_usd", "0.0") or 0.0)
                
                # Dynamic severity mapping
                mapped_severity = AlertSeverity.CRITICAL if severity == "CRITICAL" else AlertSeverity.WARNING
                
                anomaly = CostAnomaly(
                    service=f"🤖 ML BRAIN: {service_name}",
                    current_daily_cost=cost_usd,
                    expected_daily_cost=0.0, # Baseline lookback is handled by the ML Brain internally
                    reason_code=f"{anomaly_code}",
                    region=row.get("region", "us-east-1"),
                    anomaly_score=1.0 if severity == "CRITICAL" else 0.7
                )
                
                action = RemediationAction(
                    action_id=action_value,
                    action_type=suggested_action,
                    resource_id=row.get('resource_id', 'unknown'),
                    estimated_monthly_savings=cost_usd, # Use full cost until real rightsize logic is built
                    risk_level="medium" if severity == "CRITICAL" else "low",
                    description=f"AI suggests: {suggested_action} on {row.get('resource_id')}"
                )
                
                payload = AlertPayload(
                    title=f"ML Anomaly detected in {service_name}",
                    summary=f"AI Hunter identified an unusual spend pattern in {row.get('environment')} environment.",
                    severity=mapped_severity,
                    anomalies=[anomaly],
                    actions=[action],
                    total_potential_savings=cost_usd * 0.5
                )
                
                logger.info(f"Dispatching ML Alert -> {service_name} Resource: {row.get('resource_id')}")
                service.send_alert(payload)

if __name__ == "__main__":
    run_ml_alerts()
