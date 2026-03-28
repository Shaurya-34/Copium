import pandas as pd
import matplotlib.pyplot as plt

print("📊 Loading data for visual inspection...")
df = pd.read_csv("aws_billing_with_anomalies.csv")
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Zoom in on the last 72 hours
plot_data = df[df['timestamp'] >= df['timestamp'].max() - pd.Timedelta(hours=72)]

plt.style.use('dark_background')
fig, axes = plt.subplots(3, 1, figsize=(12, 9))
fig.suptitle('Chaos Injection Verification', fontsize=16)

# 1. Runaway Lambda
lambda_data = plot_data[plot_data['service'] == 'AWSLambda']
axes[0].plot(lambda_data['timestamp'], lambda_data['cost_usd'], color='red', marker='o')
axes[0].set_title('Anomaly 1: Runaway Lambda (Cost Multiplier)')
axes[0].set_ylabel('Cost (USD)')

# 2. Zombie EC2
ec2_id = df[df['service'] == 'AmazonEC2']['resource_id'].iloc[0]
zombie_data = plot_data[plot_data['resource_id'] == ec2_id]
axes[1].plot(zombie_data['timestamp'], zombie_data['cpu_usage_pct'], color='orange', marker='x')
axes[1].set_title('Anomaly 2: Zombie EC2 (CPU Drop to 0%)')
axes[1].set_ylabel('CPU Usage (%)')

# 3. S3 Leak
s3_data = plot_data[plot_data['service'] == 'AmazonS3']
axes[2].plot(s3_data['timestamp'], s3_data['cost_usd'], color='cyan')
axes[2].set_title('Anomaly 3: S3 Storage Leak (Steady Creep)')
axes[2].set_ylabel('Cost (USD)')

plt.tight_layout()
plt.show()