import os
import boto3
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

# Load security credentials from .env
load_dotenv()

app = FastAPI(title="Cloud CFO - Final Master Backend")

# Enable CORS for Member 4 (UI) and Member 3 (Slack/Automation)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURATION & MAPPING ---
# Maps technical region codes to human-friendly names for the UI
GLOBAL_REGION_MAP = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-north-1": "EU (Stockholm)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "eu-central-1": "Europe (Frankfurt)"
}

# --- DATA MODELS ---
class RemediationRequest(BaseModel):
    action: str  # 'stop' or 'terminate'
    instance_id: str
    region: str

# --- HELPER FUNCTIONS ---
def get_client(service, region=None):
    """Helper to initialize AWS clients securely."""
    return boto3.client(
        service, 
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"), 
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"), 
        region_name=region or os.getenv("AWS_REGION", "us-east-1")
    )

async def fetch_all_cloud_resources():
    """Dynamically discovers all regions and audits EC2, S3, and Lambda."""
    rows = []
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        # 1. DYNAMIC REGION DISCOVERY
        ec2_discovery = get_client('ec2', 'us-east-1')
        region_response = ec2_discovery.describe_regions()
        discovered_regions = [r['RegionName'] for r in region_response['Regions']]
        
        print(f"🌍 Auto-Detected {len(discovered_regions)} Regions. Starting Global Audit...")

        for reg in discovered_regions:
            # --- EC2 SCAN ---
            try:
                reg_ec2 = get_client('ec2', reg)
                reg_cw = get_client('cloudwatch', reg)
                instances = reg_ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
                
                for res in instances['Reservations']:
                    for inst in res['Instances']:
                        tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}
                        cpu = reg_cw.get_metric_statistics(
                            Namespace='AWS/EC2', MetricName='CPUUtilization',
                            Dimensions=[{'Name': 'InstanceId', 'Value': inst['InstanceId']}],
                            StartTime=datetime.utcnow() - timedelta(minutes=30),
                            EndTime=datetime.utcnow(), Period=1800, Statistics=['Average']
                        )
                        cpu_val = round(cpu['Datapoints'][0]['Average'], 2) if cpu.get('Datapoints') else 0.0

                        rows.append({
                            "timestamp": timestamp, "service": "AmazonEC2", "region": reg,
                            "resource_id": inst['InstanceId'], "cost_usd": 0.0, 
                            "cpu_usage_pct": cpu_val, "team": tags.get("Team", "Engineering"),
                            "environment": tags.get("Environment", "Production"), "project": tags.get("Project", "Hackathon")
                        })
            except: continue

            # --- LAMBDA SCAN ---
            try:
                reg_lambda = get_client('lambda', reg)
                functions = reg_lambda.list_functions().get('Functions', [])
                for fn in functions:
                    fn_name = fn['FunctionName']
                    try:
                        tags_resp = reg_lambda.list_tags(Resource=fn['FunctionArn'])
                        tags = tags_resp.get('Tags', {})
                    except: tags = {}

                    rows.append({
                        "timestamp": timestamp, "service": "AWSLambda", "region": reg,
                        "resource_id": fn_name, "cost_usd": 0.0, "cpu_usage_pct": 0.0,
                        "team": tags.get("Team", "Engineering"), "environment": tags.get("Environment", "Production"),
                        "project": tags.get("Project", "Hackathon")
                    })
            except: continue

        # 2. SCAN S3 (Global)
        try:
            s3 = get_client('s3')
            buckets = s3.list_buckets().get('Buckets', [])
            for b in buckets:
                b_name = b['Name']
                loc = s3.get_bucket_location(Bucket=b_name).get('LocationConstraint')
                b_region = loc if loc else 'us-east-1'
                try:
                    b_tags = s3.get_bucket_tagging(Bucket=b_name).get('TagSet', [])
                    tags = {t['Key']: t['Value'] for t in b_tags}
                except: tags = {}

                rows.append({
                    "timestamp": timestamp, "service": "AmazonS3", "region": b_region,
                    "resource_id": b_name, "cost_usd": 0.0, "cpu_usage_pct": 0.0,
                    "team": tags.get("Team", "Engineering"), "environment": tags.get("Environment", "Production"),
                    "project": tags.get("Project", "Hackathon")
                })
        except: pass

        return rows
    except Exception as e:
        return {"error": str(e)}

# --- ENDPOINTS ---

@app.get("/")
async def welcome():
    return {
        "status": "online",
        "role": "Cloud Architect (M1)",
        "features": ["Auto-Region Discovery", "Remediation POST", "Multi-Service Scan"]
    }

@app.get("/api/costs")
async def get_report():
    data = await fetch_all_cloud_resources()
    return {"status": "success", "count": len(data), "data": data}

@app.post("/api/remediate")
async def remediate(req: RemediationRequest):
    """Physically stops or terminates instances based on Slack/UI input."""
    try:
        ec2 = get_client('ec2', region=req.region)
        if req.action.lower() == "stop":
            resp = ec2.stop_instances(InstanceIds=[req.instance_id])
            state = resp['StoppingInstances'][0]['CurrentState']['Name']
        elif req.action.lower() == "terminate":
            resp = ec2.terminate_instances(InstanceIds=[req.instance_id])
            state = resp['TerminatingInstances'][0]['CurrentState']['Name']
        else:
            raise HTTPException(status_code=400, detail="Action must be stop or terminate")
        
        return {"status": "success", "resource": req.instance_id, "new_state": state}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/pricing/compare")
async def pricing_compare(base: str, target: str, type: str = "t3.medium"):
    """Advanced pricing logic with Savings % for Member 4's dashboard."""
    try:
        pricing = get_client('pricing', region='us-east-1')
        def fetch_p(r_code, t):
            r_name = GLOBAL_REGION_MAP.get(r_code, "US East (N. Virginia)")
            resp = pricing.get_products(ServiceCode='AmazonEC2', Filters=[
                {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': t},
                {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': r_name},
                {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'},
                {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'}
            ])
            od = json.loads(resp['PriceList'][0])['terms']['OnDemand']
            k1 = list(od.keys())[0]
            k2 = list(od[k1]['priceDimensions'].keys())[0]
            return float(od[k1]['priceDimensions'][k2]['pricePerUnit']['USD'])

        p_base = fetch_p(base, type)
        p_target = fetch_p(target, type)
        delta = p_base - p_target
        savings_pct = (delta / p_base) * 100 if p_base > 0 else 0

        return {
            "instance": type,
            "monthly_savings": round(delta * 730, 2),
            "savings_percent": f"{round(savings_pct, 1)}%",
            "verdict": "High Value Move" if savings_pct > 5 else "Performance Move"
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/status/billing")
async def billing_status():
    return {"is_ready": False, "note": "AWS Cost Explorer Syncing..."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)