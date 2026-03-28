import json
import logging
from typing import Any

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from slack_sdk.signature import SignatureVerifier

from config.settings import slack_settings
from automation.remediation.remediator import RemediationEngine

logger = logging.getLogger("cloudcfo.api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CloudCFO Webhook Listener", version="1.0.0")

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

