import logging
from automation.anomaly.runner import run_daily_scan

# Configure logging for AWS CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    AWS Lambda entry point for daily Cost Explorer anomaly scans.
    Trigger this via Amazon EventBridge (e.g., cron(0 14 * * ? *)).
    """
    logger.info("Starting CloudCFO daily anomaly scan...")
    try:
        anomaly_count = run_daily_scan()
        logger.info(f"Scan complete. Detected and alerted on {anomaly_count} anomalies.")
        return {
            "statusCode": 200,
            "body": f"Successfully processed {anomaly_count} anomalies.",
            "anomalies_detected": anomaly_count
        }
    except Exception as e:
        logger.error(f"Error during CloudCFO anomaly scan: {e}", exc_info=True)
        raise
