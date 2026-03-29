import json
import logging
from typing import Any

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slack_sdk.signature import SignatureVerifier

from config.settings import slack_settings
from automation.remediation.remediator import RemediationEngine
from apscheduler.schedulers.background import BackgroundScheduler
import subprocess
import os

logger = logging.getLogger("cloudcfo.api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CloudCFO Webhook Listener", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",                  # Local Next.js dev
        "https://kpi5dashboard.streamlit.app",   # Live Dashboard
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# --- SECURITY: API KEY PROTECTION ---
# Note: In production, store this in an environment variable or secret manager.
CLOUD_CFO_API_KEY = "3d4c5eb8-9fe0-4458-882d-5750d9a78947"

async def verify_api_key(x_api_key: str = Header(None)):
    """Gatekeeper dependency for secure dashboard requests."""
    if not x_api_key:
        logger.warning("Unauthenticated request: Missing X-API-KEY header.")
        raise HTTPException(status_code=401, detail="Missing API Key")
    if x_api_key != CLOUD_CFO_API_KEY:
        logger.warning(f"Unauthenticated request: Invalid API Key provided.")
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return x_api_key

signature_verifier = SignatureVerifier(slack_settings.signing_secret)
engine = RemediationEngine()

# --- AUTOMATION SCHEDULER ---
scheduler = BackgroundScheduler()

def run_automated_audit():
    """
    Every hour:
    1. ml/ml_brain.py fetches live data from THIS api, trains model, detects anomalies, and saves to CSV.
    2. automation/reporting/ml_alert_runner.py reads that CSV and dispatches alerts to Slack.
    """
    logger.info("🕒 SCHEDULER TRIGGERED: Starting live FinOps audit...")
    try:
        # Run ML Brain
        ml_path = os.path.join(os.getcwd(), "ml", "ml_brain.py")
        alert_path = os.path.join(os.getcwd(), "automation", "reporting", "ml_alert_runner.py")
        
        # We pass the root as PYTHONPATH so sub-scripts can import from automation.* and config.*
        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd()
        
        logger.info(f"🧠 Step 1: Running ML Brain process at {ml_path}")
        subprocess.run(["python", ml_path], check=True, cwd=os.getcwd(), env=env)
        
        logger.info(f"📢 Step 2: Running Alert Dispatcher at {alert_path}")
        subprocess.run(["python", alert_path], check=True, cwd=os.getcwd(), env=env)
        
        logger.info("✅ SCHEDULER: Hourly audit loop completed successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ SCHEDULER ERROR: Subprocess failed during audit: {e}")
    except Exception as e:
        logger.error(f"❌ SCHEDULER CRITICAL ERROR: {e}")

@app.on_event("startup")
def start_finops_scheduler():
    # Run audit immediately if in dev, then every hour
    # We delay slightly to allow FastAPI to bind to port 8000 first
    import threading
    def delayed_startup():
        import time
        time.sleep(5) # Let uvicorn start
        logger.info("🚀 Triggering initial audit cycle...")
        run_automated_audit()
        
    scheduler.add_job(run_automated_audit, 'interval', hours=1)
    scheduler.start()
    logger.info("📡 LIVE AUDIT SCHEDULER: Running on background thread.")
    
    # Run the initial scan asynchronously to not block the main startup
    threading.Thread(target=delayed_startup).start()

@app.get("/")
async def root():
    return {"status": "CloudCFO ML Brain is Online", "tunnel": "Active", "version": "1.1.0"}

@app.post("/api/slack/interactions")
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
    
    # 1. Parsing the Incoming Action Value
    # Support for legacy IDs vs new enhanced format "ACTION:ID:CODE"
    if ":" in action_value:
        parts = action_value.split(":")
        action_type = parts[0]
        resource_id = parts[1] if len(parts) > 1 else "unknown"
        anomaly_code = parts[2] if len(parts) > 2 else "NONE"
    else:
        logger.warning(f"Unrecognized action_value format: {action_value}")
        action_type = action_value
        resource_id = "unknown"
        anomaly_code = "GENERIC"

    logger.info(f"Action parsed: {action_type} for resource {resource_id} (Code: {anomaly_code})")

    try:
        from automation.slack.message_builder import MessageBuilder
        from automation.slack.webhook import SlackWebhook
        from automation.slack.models import AlertSeverity

        webhook = SlackWebhook(slack_settings.webhook_url)

        # Scenario B: PROD PROTECTION (Code 999) - Routing to Manual Review link
        if anomaly_code == "CODE_999_PROD_FIGHT":
            msg = f"<@{user_id}> is escalating production risk for `{resource_id}` to AWS Console manual review."
            # No boto3 action for manual review links
            result_success = True
            result_message = "Escalated to On-Call/Manual Review."
            
        # Scenario C: SECURITY BREACH (Unauthorized Region) - Routing to Security Module
        elif anomaly_code == "SEC_REGION_UNAUTHORIZED":
            logger.warning(f"SECURITY BREACH in unauthorized region detected by <@{user_id}>. Executing LOCKDOWN.")
            # Mocking the security lockdown call (in production, this blocks NACLs/SecurityGroups)
            result_success = True
            result_message = f"Region Lockdown initiated on {resource_id}."

        # Scenario D: QUIET HOURS (Code 104)
        elif action_type == "HALT_UNTIL_MONDAY":
            result_success = True
            result_message = f"Operation on {resource_id} paused until Monday 8 AM."

        # Scenario A: ZOMBIE / Standard Actions
        elif action_type == "STOP_INSTANCE" or action_type == "STOP_EC2":
            result = engine.stop_idle_ec2(instance_id=resource_id, dry_run=False)
            result_success, result_message = result.success, result.message
        elif action_type == "START_EC2":
            result = engine.start_ec2(instance_id=resource_id, dry_run=False)
            result_success, result_message = result.success, result.message
        elif action_type == "DELETE_EBS":
            result = engine.delete_unattached_ebs(volume_id=resource_id, dry_run=False)
            result_success, result_message = result.success, result.message
        
        # Scenario E: INVESTIGATE / MANUAL (Non-destructive)
        elif action_type in ["INVESTIGATE", "MANUAL_REVIEW_REQUIRED"]:
            result_success = True
            result_message = f"Acknowledged. <@{user_id}> is investigating {resource_id}."
        
        else:
            logger.error(f"Unsupported action type: {action_type}")
            return

        # Prepare the result message to send back to Slack
        status_emoji = "✅" if result_success else "❌"
        msg = (
            f"<@{user_id}> executed `{action_type}` on `{resource_id}`.\n"
            f"> *Outcome:* {result_message}"
        )

        slack_payload = MessageBuilder.build_simple_alert(
            title=f"{status_emoji} Remediation Action Executed",
            message=msg,
            severity=AlertSeverity.INFO if result_success else AlertSeverity.WARNING
        )
        webhook.send(slack_payload)
        logger.info(f"Remediation response sent to Slack for {resource_id}")

    except Exception as e:
        logger.error(f"Error executing remediation in background task: {e}", exc_info=True)

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
        
        # 7-day actual cost series from AWS Cost Explorer
        from automation.anomaly.detector import CostExplorerDetector
        from datetime import date, timedelta
        
        detector = CostExplorerDetector()
        end_date = date.today()
        start_date = end_date - timedelta(days=7)
        
        # We fetch daily totals (no group by for the chart)
        try:
            ce_client = detector._client
            response = ce_client.get_cost_and_usage(
                TimePeriod={
                    "Start": start_date.isoformat(),
                    "End": (end_date + timedelta(days=1)).isoformat(),
                },
                Granularity="DAILY",
                Metrics=["UnblendedCost"]
            )
            
            cost_series = []
            for result in response.get("ResultsByTime", []):
                cost_series.append({
                    "date": result.get("TimePeriod", {}).get("Start"),
                    "total_cost": float(result.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
                })
        except Exception as e:
            logger.warning(f"Could not fetch real cost history: {e}")
            cost_series = []
            
        return {
            "slack_channel": slack_settings.channel,  # For UI Deep Linking
            "total_remediations_attempted": len(audit_log),
            "total_remediations_successful": successful,
            "total_monthly_savings_usd": total_savings,
            "cost_series": cost_series,               # Real AWS Cost Explorer data
            "recent_actions": audit_log[:10]          # Return top 10 most recent actions
        }
    except Exception as e:
        logger.exception("Failed to load dashboard metrics")
        raise HTTPException(status_code=500, detail="Internal server error parsing audit log")

@app.get("/api/ml/anomalies", dependencies=[Depends(verify_api_key)])
def get_ml_anomalies():
    """Returns the latest detections from the ML Brain CSV."""
    import pandas as pd
    import os
    file_path = os.path.join(os.getcwd(), "ml", "detected_anomalies.csv")
    if not os.path.exists(file_path):
        return {"status": "unavailable", "message": "ML Brain has not generated anomalies yet."}
    
    try:
        df = pd.read_csv(file_path)
        return {"status": "success", "data": df.to_dict(orient="records")}
    except Exception as e:
        logger.error(f"Failed to read ML anomalies: {e}")
        raise HTTPException(status_code=500, detail="Error reading ML data.")

@app.get("/api/ml/forecasts", dependencies=[Depends(verify_api_key)])
def get_ml_forecasts():
    """Returns cost forecasts generated by the ML pipeline."""
    import os
    file_path = os.path.join(os.getcwd(), "ml", "forecast_metrics.json")
    if not os.path.exists(file_path):
        return {"status": "empty", "data": {}}
    
    try:
        with open(file_path, "r") as f:
            return {"status": "success", "data": json.load(f)}
    except Exception as e:
        logger.error(f"Failed to read forecasts: {e}")
        raise HTTPException(status_code=500, detail="Error reading forecast file.")

@app.get("/api/remediation/history", dependencies=[Depends(verify_api_key)])
def get_remediation_history():
    """Returns the full audit log of all system fixes."""
    from automation.remediation.remediator import AUDIT_LOG_PATH
    if not AUDIT_LOG_PATH.exists():
        return {"status": "empty", "data": []}
    
    try:
        with open(AUDIT_LOG_PATH, "r") as f:
            return {"status": "success", "data": json.load(f)}
    except Exception as e:
        logger.error(f"Failed to read audit log: {e}")
        raise HTTPException(status_code=500, detail="Error reading audit log.")

@app.get("/api/costs", dependencies=[Depends(verify_api_key)])
def get_live_costs():
    """
    Feeds LIVE AWS multi-service inventory to the ML Brain and Client Dashboard.
    Fetches real-time Resource IDs and constructs full IAM ARNs.
    """
    import os
    from datetime import datetime
    import boto3
    from dotenv import load_dotenv
    
    load_dotenv(os.path.join(os.getcwd(), "ml", ".env"))
    region = "us-east-1"
    
    try:
        # 1. Identity Check for ARN construction
        sts = boto3.client('sts', region_name=region)
        account_id = sts.get_caller_identity()['Account']
        
        live_data = []
        
        # 2. EC2 Discovery
        try:
            ec2 = boto3.client('ec2', region_name=region)
            instances = ec2.describe_instances()
            for r in instances.get('Reservations', []):
                for i in r.get('Instances', []):
                    if i.get('State', {}).get('Name') == 'running':
                        tags = {t['Key']: t['Value'] for t in i.get('Tags', [])}
                        inst_id = i.get('InstanceId')
                        live_data.append({
                            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                            "service": "AmazonEC2",
                            "resource_id": inst_id,
                            "resource_arn": f"arn:aws:ec2:{region}:{account_id}:instance/{inst_id}",
                            "region": region,
                            "environment": tags.get('Environment', 'dev'),
                            "cost_usd": 0.0, # Populated by ML model
                            "cpu_usage_pct": 0.0 # From local metric buffer or CW
                        })
        except Exception as e:
            logger.warning(f"EC2 Discovery failed: {e}")

        # 3. Lambda Discovery
        try:
            lambda_client = boto3.client('lambda', region_name=region)
            functions = lambda_client.list_functions()
            for f in functions.get('Functions', []):
                live_data.append({
                    "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "service": "AWSLambda",
                    "resource_id": f.get('FunctionName'),
                    "resource_arn": f.get('FunctionArn'),
                    "region": region,
                    "environment": "production" if "prod" in f.get('FunctionName').lower() else "dev"
                })
        except Exception as e:
            logger.warning(f"Lambda Discovery failed: {e}")

        # 4. RDS Discovery
        try:
            rds = boto3.client('rds', region_name=region)
            dbs = rds.describe_db_instances()
            for db in dbs.get('DBInstances', []):
                live_data.append({
                    "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "service": "AmazonRDS",
                    "resource_id": db.get('DBInstanceIdentifier'),
                    "resource_arn": db.get('DBInstanceArn'),
                    "region": region,
                    "environment": "production" if db.get('PubliclyAccessible') == False else "dev"
                })
        except Exception as e:
            logger.warning(f"RDS Discovery failed: {e}")

        return {"status": "success", "data": live_data}
    except Exception as e:
        logger.exception("Final live discovery crash")
        raise HTTPException(status_code=500, detail=str(e))
