import json
import logging
from typing import Any

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slack_sdk.signature import SignatureVerifier

from config.settings import slack_settings
from automation.remediation.remediator import RemediationEngine

logger = logging.getLogger("cloudcfo.api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CloudCFO Webhook Listener", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow UI frontend to connect during integration tests
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

signature_verifier = SignatureVerifier(slack_settings.signing_secret)
engine = RemediationEngine()

@app.post("/slack/interactions")
async def slack_interactions(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint for handling interactive elements from Slack (e.g. "Fix" buttons).
    """
    body = await request.body()
    headers = request.headers

    # Validate that this request actually came from Slack
    if slack_settings.signing_secret:
        if not signature_verifier.is_valid_request(body, headers):
            logger.warning("Invalid signature on incoming webhook request.")
            raise HTTPException(status_code=403, detail="Invalid Slack Signature")
    else:
        logger.warning("SLACK_SIGNING_SECRET is empty - skipping signature verification (DEV MODE ONLY)")

    form_data = await request.form()
    payload_str = form_data.get("payload")
    if not payload_str:
        return JSONResponse(content={"status": "error", "message": "Missing payload"}, status_code=400)

    payload = json.loads(str(payload_str))
    
    # We only care about block_actions (button clicks)
    if payload.get("type") != "block_actions":
        return JSONResponse(content={"status": "ignored"})

    actions = payload.get("actions", [])
    if not actions:
        return JSONResponse(content={"status": "ignored"})

    action = actions[0]
    action_value = action.get("value")      # E.g. "stop_ec2|i-12345678" 
    action_id = action.get("action_id")     # "fix_action_xyz"
    user_id = payload.get("user", {}).get("id", "Unknown User")
    
    logger.info(f"Received action: {action_id} with value {action_value} from user <@{user_id}>")

    # In a real scenario, we would instantly reply 200 OK so Slack doesn't timeout,
    # and use background_tasks to actually perform the aws remediation.
    background_tasks.add_task(process_remediation, action_value, user_id)
    
    return JSONResponse(content={"status": "received"})


def process_remediation(action_value: str, user_id: str):
    """
    Background worker that runs the AWS boto3 remediation after the HTTP response closes.
    """
    logger.info(f"Running background remediation task for {action_value} triggered by {user_id}...")
    
    # Support for demo values used in demo_slack.py, or parsing production "TYPE:ID" formats
    if action_value == "act-ec2-stop-001":
        action_type = "STOP_EC2"
        resource_id = "i-0abcd1234efgh5678"
    elif action_value == "act-ebs-del-001":
        action_type = "DELETE_EBS"
        resource_id = "vol-0xyz98765uvw43210"
    elif ":" in action_value:
        parts = action_value.split(":", 1)
        action_type = parts[0]
        resource_id = parts[1]
    else:
        logger.error(f"Unknown action_value format: {action_value}")
        return

    logger.info(f"Action parsed: {action_type} for resource {resource_id}")

    try:
        from automation.slack.message_builder import MessageBuilder
        from automation.slack.webhook import SlackWebhook
        from automation.slack.models import AlertSeverity

        webhook = SlackWebhook(slack_settings.webhook_url)

        # Execute remediation using the engine (dry_run=False because clicking 'Fix' IS the approval)
        if action_type == "STOP_EC2":
            result = engine.stop_idle_ec2(instance_id=resource_id, dry_run=False)
        elif action_type == "START_EC2":
            result = engine.start_ec2(instance_id=resource_id, dry_run=False)
        elif action_type == "DELETE_EBS":
            result = engine.delete_unattached_ebs(volume_id=resource_id, dry_run=False)
        else:
            logger.error(f"Unsupported action type: {action_type}")
            return

        # Prepare the result message to send back to Slack
        status_emoji = "✅" if result.success else "❌"
        msg = (
            f"<@{user_id}> executed `{action_type}` on `{resource_id}`.\n"
            f"> *Outcome:* {result.message}"
        )

        slack_payload = MessageBuilder.build_simple_alert(
            title=f"Remediation Result {status_emoji}",
            message=msg,
            severity=AlertSeverity.INFO if result.success else AlertSeverity.WARNING
        )
        webhook.send(slack_payload)
        logger.info(f"Remediation outcome sent to Slack channel successfully.")

    except Exception as e:
        logger.exception("Error executing remediation in background task")

@app.get("/api/dashboard")
def get_dashboard_metrics():
    """
    Phase 5: Aggregate the audit_log.json to provide live savings and operation counts for the UI frontend.
    """
    from automation.remediation.remediator import AUDIT_LOG_PATH
    import re
    
    if not AUDIT_LOG_PATH.exists():
        return {
            "total_remediations_attempted": 0,
            "total_remediations_successful": 0,
            "total_monthly_savings_usd": 0.0,
            "recent_actions": []
        }
        
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as file:
            audit_log = json.load(file)
            
        successful = 0
        total_savings = 0.0
        
        for entry in audit_log:
            if entry.get("success"):
                successful += 1
                
            savings_str = entry.get("savings_estimated")
            if savings_str and "$" in savings_str:
                # E.g. "$25.00/month"
                match = re.search(r'\$([\d\.\,]+)', savings_str)
                if match:
                    val = match.group(1).replace(",", "")
                    try:
                        total_savings += float(val)
                    except ValueError:
                        pass
                        
        # Sort logs newest first
        audit_log.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        
        # 7-day mock cost series for UI charting (until AWS Organizations is fully enabled)
        # In a production environment this would call CostExplorerDetector._client.get_cost_and_usage
        import datetime
        base_date = datetime.date.today()
        cost_series = [
            {"date": str(base_date - datetime.timedelta(days=i)), "total_cost": round(150.0 + (i * 12.5), 2)}
            for i in range(6, -1, -1)
        ]
        
        return {
            "slack_channel": slack_settings.channel,  # For UI Deep Linking
            "total_remediations_attempted": len(audit_log),
            "total_remediations_successful": successful,
            "total_monthly_savings_usd": total_savings,
            "cost_series": cost_series,               # For UI Chart rendering
            "recent_actions": audit_log[:10]          # Return top 10 most recent actions
        }
    except Exception as e:
        logger.exception("Failed to load dashboard metrics")
        raise HTTPException(status_code=500, detail="Internal server error parsing audit log")

