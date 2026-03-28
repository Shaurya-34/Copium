"""Helpers to run scheduled cost anomaly scans."""

from __future__ import annotations

from typing import Optional

from automation.slack.alert_service import AlertService

from .detector import CostExplorerDetector


def run_daily_scan(
    detector: Optional[CostExplorerDetector] = None,
    alert_service: Optional[AlertService] = None,
) -> int:
    """Run one anomaly scan and send alerts. Returns anomaly count."""
    detector = detector or CostExplorerDetector()
    alert_service = alert_service or AlertService()

    anomalies = detector.detect_anomalies()
    for anomaly in anomalies:
        alert_service.send_anomaly_alert(anomaly)

    return len(anomalies)
