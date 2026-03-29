import pandas as pd
import numpy as np
import requests
import json
import os
from sklearn.ensemble import IsolationForest

print("🧠 Booting up the ML Brain (Live API Mode)...")

# ==========================================
# --- 1. Load the Data (The Live Handshake) ---
# ==========================================
API_URL = "http://127.0.0.1:8000/api/costs"
API_KEY = "3d4c5eb8-9fe0-4458-882d-5750d9a78947"

print(f"🌐 Fetching live infrastructure vitals from {API_URL}...")
response = requests.get(API_URL, headers={"X-API-KEY": API_KEY})
response.raise_for_status()

# --- THE CRITICAL FIX ---
# Instead of the whole response, we only want the list inside 'data'
raw_payload = response.json()
if not raw_payload.get('data'):
    print("⚠️ No live data available from the API. Ensure your AWS credentials are valid and instances are running.")
    exit(0)

df = pd.DataFrame(raw_payload['data']) 
# ------------------------

print(f"✅ Success! Ingested {len(df)} live records.")
print(f"🔍 Actual columns found: {df.columns.tolist()}")

# ==========================================
# --- 2. Clean NaNs & Feature Engineering ---
# ==========================================
# SAFETY NET: Check if M1 actually sent the CPU column. If not, create it.
# Ensure missing columns exist before math
for col in ['cpu_usage_pct', 'cost_usd', 'team', 'project']:
    if col not in df.columns:
        df[col] = 0.0 if col in ['cpu_usage_pct', 'cost_usd'] else "Unknown"

df['cpu_usage_pct'] = pd.to_numeric(df['cpu_usage_pct'], errors='coerce').fillna(0)

# The "Zombie Hunter" Metric
df['cost_per_cpu'] = df['cost_usd'] / (df['cpu_usage_pct'] + 0.1)
print("🔬 Feature Engineering Complete. 'cost_per_cpu' engineered.")

# ==========================================
# --- 3. Train the Isolation Forest ---
# ==========================================
print("\n🤖 Initializing the AI Hunter (Isolation Forest)...")
features = ['cost_usd', 'cpu_usage_pct', 'cost_per_cpu']
X = df[features]

model = IsolationForest(contamination=0.01, random_state=42)
df['raw_prediction'] = model.fit_predict(X)
df['is_anomaly'] = df['raw_prediction'].map({1: False, -1: True})
print(f"🎯 Training Complete! The AI flagged {df['is_anomaly'].sum()} suspicious events.")

# ==========================================
# --- 4. HYBRID Severity Scoring ---
# ==========================================
print("\n⚖️ Loading User Preferences...")
config_path = os.path.join(os.path.dirname(__file__), 'config.json')
with open(config_path, 'r') as file:
    config = json.load(file)

user_multiplier = config.get("risk_multiplier", 2.0)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df['hour'] = df['timestamp'].dt.hour
df['anomaly_score_raw'] = model.decision_function(X)

# Calculate the dynamic baseline
df['hourly_service_avg'] = df.groupby(['service', 'hour'])['cost_usd'].transform('mean')
df['critical_limit'] = df['hourly_service_avg'] * user_multiplier 
critical_threshold = np.percentile(df['anomaly_score_raw'], 0.1)

# Load the new Guardrail arrays from config
auth_regions = config.get("authorized_regions", [])
quiet_hours = config.get("quiet_hours", [])
service_sens = config.get("service_sensitivity", {})

# ==========================================
# --- 5. THE BUSINESS GUARDRAILS ENGINE ---
# ==========================================
print("\n🛡️ Applying Business Guardrails...")

def apply_guardrails(row):
    # Default State
    severity = "NORMAL"
    reason_code = "CODE_200_NORMAL"
    action = "NONE"
    
    # --- Guardrail 1: Geofencing (Security) ---
    if row['region'] not in auth_regions:
        return pd.Series(["CRITICAL", "SEC_REGION_UNAUTHORIZED", "BLOCK_REGION_ACCESS"])

    # --- Guardrail 2: Environment Hierarchy ---
    # Prod is sacred. Never auto-fix.
    is_prod = True if str(row['environment']).lower() in ['prod', 'production'] else False
    
    # --- Guardrail 3: Service-Relative Thresholding ---
    dynamic_multiplier = service_sens.get(row['service'], user_multiplier)
    is_price_spike = row['cost_usd'] > (row['hourly_service_avg'] * dynamic_multiplier)

    # --- Guardrail 4: Quiet Hours Logic ---
    is_quiet_hour = True if row['hour'] in quiet_hours else False
    
    # --- COMBINING LOGIC ---
    if row['is_anomaly'] or is_price_spike:
        severity = "WARNING"
        reason_code = "CODE_103_SPEND_SPIKE"
        action = "INVESTIGATE"
        
        # Escalate to CRITICAL based on business rules
        if is_prod:
            severity = "CRITICAL"
            reason_code = "CODE_999_PROD_FIGHT"
            action = "MANUAL_REVIEW_REQUIRED" 
            
        elif row['cpu_usage_pct'] < 5:
            severity = "CRITICAL"
            reason_code = "CODE_101_ZOMBIE"
            action = "STOP_INSTANCE"
            
        elif is_quiet_hour:
            severity = "CRITICAL"
            reason_code = "CODE_104_OFF_HOURS_ACTIVITY"
            action = "HALT_UNTIL_MONDAY"

    # Fallback to catch ML outliers that didn't trip the price spike
    if severity == "NORMAL" and row['anomaly_score_raw'] <= critical_threshold:
        severity = "WARNING"
        reason_code = "CODE_105_ML_OUTLIER"
        action = "INVESTIGATE"

    return pd.Series([severity, reason_code, action])

# Apply the guardrails to the dataframe to create our 3 intelligence columns
df[['severity', 'anomaly_code', 'suggested_action']] = df.apply(apply_guardrails, axis=1)
# ==========================================
# --- 6. Final Clean Export ---
# ==========================================
final_columns = [
    'timestamp', 'service', 'region', 'resource_id', 'resource_arn',
    'team', 'environment', 'project', 
    'cost_usd', 'cpu_usage_pct', 'cost_per_cpu',
    'is_anomaly', 'severity', 'anomaly_code', 'suggested_action'
]

output_path = os.path.join(os.path.dirname(__file__), "detected_anomalies.csv")
df[final_columns].to_csv(output_path, index=False)

# --- ADD THIS LOGIC HERE ---
# Calculate the final tally after both ML and Guardrails have run
total_critical = len(df[df['severity'] == "CRITICAL"])
total_warning = len(df[df['severity'] == "WARNING"])

print(f"\n🎯 Final Summary: Found {total_critical} CRITICAL and {total_warning} WARNING alerts.")
print(f"🛡️ Guardrails caught {total_critical + total_warning - df['is_anomaly'].sum()} security/business risks the ML missed!")
print("🚀 Phase 4 COMPLETE: 'detected_anomalies.csv' is ready for the UI.")