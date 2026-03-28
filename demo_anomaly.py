import logging
from automation.anomaly.runner import run_daily_scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting live End-to-End Cost Explorer anomaly scan...")
    try:
        count = run_daily_scan()
        logger.info(f"Scan finished successfully! Detected {count} anomaly/anomalies.")
        if count > 0:
            logger.info("Check your Slack channel for the alerts!")
        else:
            logger.info("No anomalies crossed the thresholds today. (Slack is quiet).")
    except Exception as e:
        logger.error(f"Scan failed: {e}", exc_info=True)

if __name__ == "__main__":
    main()
