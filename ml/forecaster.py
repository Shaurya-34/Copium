import pandas as pd
import requests
import json
from datetime import datetime

print("📈 Booting up the Financial Forecaster...")

# ==========================================
# --- 1. Fetch Live Infrastructure Data ---
# ==========================================
API_URL = "http://127.0.0.1:8000/api/costs"

try:
    print(f"🌐 Pulling live billing metrics from {API_URL}...")
    response = requests.get(f"{API_URL}?mode=demo")
    response.raise_for_status()
    raw_payload = response.json()
    df = pd.DataFrame(raw_payload['data'])
except Exception as e:
    print(f"❌ API Connection Failed: {e}")
    exit()

# ==========================================
# --- 2. Calculate the "Burn Rate" ---
# ==========================================
df['timestamp'] = pd.to_datetime(df['timestamp'])
total_cost_so_far = df['cost_usd'].sum()

# Calculate how many hours of data we actually have
min_time = df['timestamp'].min()
max_time = df['timestamp'].max()
hours_elapsed = (max_time - min_time).total_seconds() / 3600.0

# Safety net: If M1 only sent a 1-second snapshot, assume 1 hour to prevent division by zero
if hours_elapsed < 1:
    hours_elapsed = 1.0

current_hourly_burn = total_cost_so_far / hours_elapsed
HOURS_IN_MONTH = 730  # Standard AWS month

# The raw trajectory if nobody does anything
projected_month_end = current_hourly_burn * HOURS_IN_MONTH

# ==========================================
# --- 3. The "Optimization" Engine ---
# ==========================================
# We check the ML Brain's homework to see how much we can save
print("🛡️ Calculating potential optimization savings...")
try:
    anomalies_df = pd.read_csv("detected_anomalies.csv")
    
    # Filter only for actionable waste (Zombies, Over-provisioned, etc.)
    waste_df = anomalies_df[anomalies_df['suggested_action'] != "NONE"]
    
    # Calculate the burn rate of JUST the garbage resources
    wasted_hourly_burn = waste_df['cost_usd'].sum() / hours_elapsed
    
    # The optimized trajectory if DevOps clicks the "Fix" buttons
    optimized_month_end = (current_hourly_burn - wasted_hourly_burn) * HOURS_IN_MONTH

except FileNotFoundError:
    print("⚠️ 'detected_anomalies.csv' not found. Run ml_brain.py first!")
    optimized_month_end = projected_month_end

# ==========================================
# --- 4. Export for M4's CFO Dashboard ---
# ==========================================
potential_savings = projected_month_end - optimized_month_end

print("\n📊 --- MONTH-END PROJECTION ---")
print(f"💸 Current Hourly Burn:  ${current_hourly_burn:.2f}")
print(f"🔮 Unmanaged Month-End:  ${projected_month_end:,.2f}")
print(f"✨ Optimized Month-End:  ${optimized_month_end:,.2f}")
print(f"💰 Total Preventable Waste: ${potential_savings:,.2f}")

output_metrics = {
    "current_hourly_burn": round(current_hourly_burn, 2),
    "projected_spend": round(projected_month_end, 2),
    "optimized_spend": round(optimized_month_end, 2),
    "potential_savings": round(potential_savings, 2)
}

# Save as JSON so M4's Streamlit Dashboard can easily display the big numbers
with open("forecast_metrics.json", "w") as f:
    json.dump(output_metrics, f, indent=4)

print("\n✅ Pipeline Complete: 'forecast_metrics.json' generated for the UI.")