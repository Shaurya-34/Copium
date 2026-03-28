"""
CloudCFO - Cost anomaly detection
---------------------------------
Detects daily AWS spend spikes from Cost Explorer and returns CostAnomaly models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import logging
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

from automation.slack.models import CostAnomaly
from config.settings import anomaly_settings


@dataclass
class ServiceCostSnapshot:
    """Aggregated service spend over a date window."""

    service: str
    amount: float


class CostExplorerDetector:
    """Detect cost anomalies using AWS Cost Explorer daily grouped costs."""

    def __init__(
        self,
        session: Optional[boto3.session.Session] = None,
        region_name: Optional[str] = None,
    ):
        self._settings = anomaly_settings
        self._session = session or boto3.Session(
            region_name=region_name or self._settings.aws_region,
        )
        self._client = self._session.client("ce", region_name="us-east-1")

    def detect_anomalies(self, reference_date: Optional[date] = None) -> list[CostAnomaly]:
        """Return service-level daily anomalies for the reference date."""
        today = reference_date or date.today()
        target_day = today - timedelta(days=self._settings.data_lag_days)
        baseline_end = target_day - timedelta(days=1)
        baseline_start = baseline_end - timedelta(days=self._settings.baseline_days - 1)

        if baseline_start >= target_day:
            raise ValueError("Baseline window must end before the target day.")

        current_costs = self._fetch_grouped_daily_costs(target_day, target_day)
        baseline_costs = self._fetch_grouped_daily_costs(baseline_start, baseline_end)
        baseline_lookup = {snapshot.service: snapshot.amount for snapshot in baseline_costs}

        anomalies: list[CostAnomaly] = []
        for snapshot in current_costs:
            expected_cost = baseline_lookup.get(snapshot.service, 0.0)
            if not self._is_anomaly(snapshot.amount, expected_cost):
                continue

            anomalies.append(
                CostAnomaly(
                    service=snapshot.service,
                    anomaly_score=self._score_anomaly(snapshot.amount, expected_cost),
                    current_daily_cost=snapshot.amount,
                    expected_daily_cost=expected_cost,
                    reason_code=self._reason_code(snapshot.amount, expected_cost),
                    region=self._settings.aws_region,
                )
            )

        return sorted(anomalies, key=lambda item: item.anomaly_score, reverse=True)

    def _fetch_grouped_daily_costs(
        self,
        start_date: date,
        end_date: date,
    ) -> list[ServiceCostSnapshot]:
        try:
            response = self._client.get_cost_and_usage(
                TimePeriod={
                    "Start": start_date.isoformat(),
                    "End": (end_date + timedelta(days=1)).isoformat(),
                },
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DataUnavailableException":
                logger.warning(f"Cost Explorer data unavailable for {start_date} to {end_date}. Returning zero costs.")
                return []
            raise

        aggregated_costs: dict[str, float] = {}
        periods = response.get("ResultsByTime", [])
        for period in periods:
            for group in period.get("Groups", []):
                service = self._service_name(group.get("Keys", []))
                amount = self._metric_amount(group.get("Metrics", {}))
                aggregated_costs[service] = aggregated_costs.get(service, 0.0) + amount

        day_count = max((end_date - start_date).days + 1, 1)
        snapshots = [
            ServiceCostSnapshot(service=service, amount=amount / day_count)
            for service, amount in aggregated_costs.items()
            if amount > 0
        ]
        return sorted(snapshots, key=lambda item: item.amount, reverse=True)

    def _is_anomaly(self, current_cost: float, expected_cost: float) -> bool:
        if current_cost < self._settings.minimum_daily_cost:
            return False

        absolute_delta = current_cost - expected_cost
        if absolute_delta < self._settings.minimum_cost_increase:
            return False

        if expected_cost <= 0:
            return True

        ratio = current_cost / expected_cost
        return ratio >= self._settings.spike_multiplier_threshold

    def _score_anomaly(self, current_cost: float, expected_cost: float) -> float:
        if expected_cost <= 0:
            return 1.0

        ratio_score = min(current_cost / expected_cost, 3.0) / 3.0
        absolute_score = min(
            (current_cost - expected_cost) / self._settings.score_scale_dollars,
            1.0,
        )
        return round(min((ratio_score * 0.7) + (absolute_score * 0.3), 1.0), 2)

    def _reason_code(self, current_cost: float, expected_cost: float) -> str:
        if expected_cost <= 0:
            return "NEW_SERVICE_SPEND"

        increase_pct = ((current_cost - expected_cost) / expected_cost) * 100
        if increase_pct >= 200:
            return "SEVERE_COST_SPIKE"
        if increase_pct >= 100:
            return "MAJOR_COST_SPIKE"
        return "ELEVATED_COST_TREND"

    def _metric_amount(self, metrics: dict[str, Any]) -> float:
        amount = metrics.get("UnblendedCost", {}).get("Amount", "0")
        return float(amount)

    def _service_name(self, keys: list[str]) -> str:
        if not keys:
            return "Unknown Service"
        return keys[0].strip() or "Unknown Service"
