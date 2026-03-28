import pandas as pd
import json

# 1. Load the data we verified in Checkpoint 3
df = pd.read_csv("aws_billing_with_anomalies.csv")

# 2. Rename to the official team filename
df.to_csv("aws_mock_data.csv", index=False)
print("📦 Created: aws_mock_data.csv")

# 3. Generate Summary Metrics for the Dashboard
# This helps Member 4 (UI) show "Big Numbers" immediately
summary = {
    "total_monthly_spend": round(df['cost_usd'].sum(), 2),
    "average_daily_spend": round(df.groupby(df.index // 24)['cost_usd'].sum().mean(), 2),
    "potential_savings": round(df[df['cpu_usage_pct'] < 2]['cost_usd'].sum(), 2), # Calculating "Zombie" waste
    "active_resources": int(df['resource_id'].nunique()),
    "anomaly_count_detected": "Pending ML Phase 2" 
}

# 4. Save to JSON
with open("summary_metrics.json", "w") as f:
    json.dump(summary, f, indent=4)

print("📊 Created: summary_metrics.json")
print("\n🚀 READY FOR HANDOFF!")
print("Files to share: 'aws_mock_data.csv' and 'summary_metrics.json'")