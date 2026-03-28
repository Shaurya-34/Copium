import boto3

def try_getting(name, func):
    print(f"\n=== {name} ===")
    try:
        func()
    except Exception as e:
        print(f"Could not load {name}: {e}")

def check_ec2():
    ec2 = boto3.client("ec2")
    res = ec2.describe_instances()
    instances = [i for r in res.get("Reservations", []) for i in r.get("Instances", [])]
    if not instances:
        print("No EC2 instances found.")
    for i in instances:
        name = next((tag["Value"] for tag in i.get("Tags", []) if tag["Key"] == "Name"), "Unnamed")
        print(f"- {i['InstanceId']} ({name}) | State: {i['State']['Name']} | Type: {i['InstanceType']}")

def check_volumes():
    ec2 = boto3.client("ec2")
    res = ec2.describe_volumes()
    volumes = res.get("Volumes", [])
    if not volumes:
        print("No EBS volumes found.")
    for v in volumes:
        print(f"- {v['VolumeId']} | Size: {v['Size']}GB | State: {v['State']}")

def check_s3():
    s3 = boto3.client("s3")
    res = s3.list_buckets()
    buckets = res.get("Buckets", [])
    if not buckets:
        print("No S3 buckets found.")
    for b in buckets:
        print(f"- {b['Name']}")

def check_rds():
    rds = boto3.client("rds")
    res = rds.describe_db_instances()
    dbs = res.get("DBInstances", [])
    if not dbs:
        print("No RDS databases found.")
    for db in dbs:
        print(f"- {db['DBInstanceIdentifier']} | Status: {db['DBInstanceStatus']} | Engine: {db['Engine']}")

if __name__ == "__main__":
    print("Checking your active AWS Region: " + boto3.Session().region_name)
    try_getting("EC2 Instances", check_ec2)
    try_getting("EBS Volumes", check_volumes)
    try_getting("RDS Databases", check_rds)
    try_getting("S3 Buckets (Global)", check_s3)
