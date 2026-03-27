"""
CloudCFO — Slack Alert Data Models
-------------------------------------
Pydantic models for cost anomalies, idle resources, remediation
actions, and composite alert payloads.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Severity Enum ──────────────────────────────────────────────


class AlertSeverity(str, Enum):
    """Alert severity levels with Slack-friendly colours and emoji."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def color(self) -> str:
        return {
            AlertSeverity.INFO: "#36a64f",
            AlertSeverity.WARNING: "#ff9900",
            AlertSeverity.CRITICAL: "#ff0000",
        }[self]

    @property
    def emoji(self) -> str:
        return {
            AlertSeverity.INFO: "ℹ️",
            AlertSeverity.WARNING: "⚠️",
            AlertSeverity.CRITICAL: "🚨",
        }[self]


# ── Domain Models ──────────────────────────────────────────────


class CostAnomaly(BaseModel):
    """A single cost anomaly detected by the anomaly-detection pipeline."""

    service: str
    anomaly_score: float = Field(ge=0.0, le=1.0)
    current_daily_cost: float = Field(ge=0.0)
    expected_daily_cost: float = Field(ge=0.0)
    reason_code: str
    region: str = "us-east-1"
    account_id: Optional[str] = None
    detected_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def cost_increase_pct(self) -> float:
        """Percentage cost increase over expected baseline."""
        if self.expected_daily_cost == 0:
            return 100.0
        return (
            (self.current_daily_cost - self.expected_daily_cost)
            / self.expected_daily_cost
            * 100
        )

    @property
    def severity(self) -> AlertSeverity:
        """Derive severity from anomaly score."""
        if self.anomaly_score >= 0.85:
            return AlertSeverity.CRITICAL
        elif self.anomaly_score >= 0.6:
            return AlertSeverity.WARNING
        return AlertSeverity.INFO


class IdleResource(BaseModel):
    """An AWS resource identified as idle / under-utilised."""

    resource_id: str
    resource_type: str
    avg_cpu_pct: float = Field(ge=0.0)
    hourly_cost: float = Field(ge=0.0)
    idle_hours: int = Field(ge=0)
    region: str = "us-east-1"
    tags: dict[str, str] = Field(default_factory=dict)

    @property
    def wasted_cost(self) -> float:
        """Total wasted cost over the idle period."""
        return self.hourly_cost * self.idle_hours

    @property
    def monthly_waste_estimate(self) -> float:
        """Projected monthly waste (730 hours ≈ 1 month)."""
        return self.hourly_cost * 730


class RemediationAction(BaseModel):
    """A suggested remediation action with an interactive "Fix" button."""

    action_id: str
    action_type: str  # stop_instance | delete_volume | rightsize | ...
    resource_id: str
    estimated_monthly_savings: float = Field(ge=0.0)
    risk_level: str = "low"  # low | medium | high
    description: str = ""


# ── Composite Payload ──────────────────────────────────────────


class AlertPayload(BaseModel):
    """Complete alert payload combining all components."""

    title: str
    summary: str
    severity: AlertSeverity = AlertSeverity.WARNING
    anomalies: list[CostAnomaly] = Field(default_factory=list)
    idle_resources: list[IdleResource] = Field(default_factory=list)
    actions: list[RemediationAction] = Field(default_factory=list)
    total_potential_savings: float = 0.0
    forecast_month_end: Optional[float] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)
