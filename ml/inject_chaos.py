import pandas as pd
import numpy as np
from datetime import timedelta

print("☣️ Loading baseline data for Chaos Injection...")
df = pd.read_csv("aws_billing_baseline.csv")
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Find the exact end of our timeline to inject chaos at the very end
end_time = df['timestamp'].max()

# ==========================================
# 💥 ANOMALY 1: The "Runaway Lambda"
# ==========================================
lambda_id = df[df['service'] == 'AWSLambda']['resource_id'].iloc
spike_start = end_time - pd.Timedelta(hours=30)
spike_end = spike_start + pd.Timedelta(hours=4)

spike_mask = (df['resource_id'] == lambda_id) & (df['timestamp'] >= spike_start) & (df['timestamp'] <= spike_end)
df.loc[spike_mask, 'cost_usd'] *= 15.0

# ==========================================
# 🧟‍♂️ ANOMALY 2: The "Zombie EC2"
# ==========================================
ec2_id = df[df['service'] == 'AmazonEC2']['resource_id'].iloc
zombie_start = end_time - pd.Timedelta(hours=24)

zombie_mask = (df['resource_id'] == ec2_id) & (df['timestamp'] >= zombie_start)
# Tank the CPU to near-zero, but leave the cost alone
df.loc[zombie_mask, 'cpu_usage_pct'] = np.random.uniform(0.1, 1.5, size=zombie_mask.sum())

# ==========================================
# 🚰 ANOMALY 3: The "S3 Leak"
# ==========================================
s3_id = df[df['service'] == 'AmazonS3']['resource_id'].iloc
leak_start = end_time - pd.Timedelta(hours=48)

leak_mask = (df['resource_id'] == s3_id) & (df['timestamp'] >= leak_start)
leak_indices = df[leak_mask].index

# Compound growth: cost * 1.05^hour
for i, idx in enumerate(leak_indices):
    df.at[idx, 'cost_usd'] *= (1.05 ** i)

# ==========================================
# 💾 EXPORT
# ==========================================
output_file = "aws_billing_with_anomalies.csv"
df.to_csv(output_file, index=False)
print(f"✅ Chaos successfully injected! Final dataset saved as '{output_file}'")