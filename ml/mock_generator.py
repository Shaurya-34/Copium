import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import string

# --- 1. ID Generator (From Checkpoint 1) ---
def generate_resource_id(service):
    if service == "AmazonEC2": return f"i-0{''.join(random.choices(string.digits + 'abcdef', k=16))}"
    elif service == "AmazonRDS": return f"prod-db-{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"
    elif service == "AmazonS3": return f"corp-assets-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"
    else: return f"res-{''.join(random.choices(string.ascii_lowercase + string.digits, k=10))}"

# --- 2. The "World" Setup ---
DAYS = 30
HOURS = DAYS * 24
start_date = datetime.now() - timedelta(days=DAYS)
timestamps = [start_date + timedelta(hours=i) for i in range(HOURS)]

# We define 5 static resources that will live for the whole 30 days
resources = [
    {"service": "AmazonEC2", "id": generate_resource_id("AmazonEC2"), "base_cost": 0.45, "region": "us-east-1", "is_compute": True},
    {"service": "AmazonEC2", "id": generate_resource_id("AmazonEC2"), "base_cost": 1.20, "region": "us-west-2", "is_compute": True},
    {"service": "AmazonRDS", "id": generate_resource_id("AmazonRDS"), "base_cost": 2.50, "region": "us-east-1", "is_compute": True},
    {"service": "AmazonS3",  "id": generate_resource_id("AmazonS3"),  "base_cost": 0.15, "region": "us-east-1", "is_compute": False},
    {"service": "AWSLambda", "id": generate_resource_id("AWSLambda"), "base_cost": 0.05, "region": "us-east-1", "is_compute": False}
]

# --- 3. The Data Engine ---
print("⚙️ Generating 30 days of baseline cloud traffic...")
data = []

for i, ts in enumerate(timestamps):
    # Math: Create a daily wave that peaks mid-day and dips at night
    hour_of_day = ts.hour
    daily_wave = 1.0 + 0.4 * np.sin(2 * np.pi * (hour_of_day - 8) / 24)
    
    # Math: Simulate a company growing by adding a 10% upward trend over the month
    growth_trend = 1.0 + (0.10 * (i / HOURS))
    
    for res in resources:
        # Add 5% random noise so it doesn't look completely artificial
        noise = np.random.uniform(0.95, 1.05)
        
        # Calculate final cost for this hour
        current_cost = res["base_cost"] * daily_wave * growth_trend * noise
        
        # Calculate CPU (Only applies to servers/databases, not S3 buckets)
        cpu_usage = None
        if res["is_compute"]:
            base_cpu = 45.0 * daily_wave * noise
            # Cap CPU between 5% and 100%
            cpu_usage = round(min(max(base_cpu, 5.0), 100.0), 2)
            
        data.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:00:00"),
            "service": res["service"],
            "region": res["region"],
            "resource_id": res["id"],
            "cost_usd": round(current_cost, 4),
            "cpu_usage_pct": cpu_usage
        })

# --- 4. Export ---
df = pd.DataFrame(data)
df.to_csv("aws_billing_baseline.csv", index=False)
print(f"✅ Success! Generated {len(df)} rows. Saved to aws_billing_baseline.csv.")