"""
CloudCFO - Remediation Engine
--------------------------------
Safe AWS remediation helpers with dry-run support, audit logging,
and operator confirmation flow.
"""

from __future__ import annotations

import json
import logging
from json import JSONDecodeError
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

HOURS_PER_DAY = 24
HOURS_PER_MONTH = 730
AUDIT_LOG_PATH = Path(__file__).with_name("audit_log.json")

# ── Supported action types ────────────────────────────────────────
ACTION_TYPES = [
    "STOP_EC2",
    "START_EC2",
    "DELETE_EBS",
    "SNAPSHOT_AND_DELETE_EBS",
    "RIGHTSIZE_EC2",
]


@dataclass
class RemediationResult:
    """Structured result for a remediation attempt."""

    success: bool
    action: str
    resource_id: str
    mode: str
    message: str
    savings_estimated: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class RemediationEngine:
    """Executes safe AWS remediation actions using boto3."""

    def __init__(
        self,
        region_name: str = "us-east-1",
        audit_log_path: Path | str = AUDIT_LOG_PATH,
        session: Optional[boto3.session.Session] = None,
    ):
        self._session = session or boto3.Session(region_name=region_name)
        self._ec2 = self._session.client("ec2")
        self._audit_log_path = Path(audit_log_path)

    def stop_idle_ec2(
        self,
        instance_id: str,
        dry_run: bool = True,
        estimated_hourly_cost: Optional[float] = None,
    ) -> RemediationResult:
        """Stop an idle EC2 instance."""
        savings = self._format_savings(
            hourly_cost=estimated_hourly_cost,
            unit="day",
            multiplier=HOURS_PER_DAY,
        )

        try:
            response = self._ec2.stop_instances(
                InstanceIds=[instance_id],
                DryRun=dry_run,
            )
            message = self._build_stop_message(response, dry_run)
            result = self._result(
                success=True,
                action="STOP_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                message=message,
                savings_estimated=savings,
                metadata={"response": response},
            )
        except ClientError as exc:
            result = self._handle_client_error(
                exc=exc,
                action="STOP_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                success_message="Dry-run validated stop_instances permissions.",
                savings_estimated=savings,
            )
        except ValueError as exc:
            result = self._result(
                success=False,
                action="STOP_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                message=str(exc),
                savings_estimated=savings,
            )

        self._append_audit_log(result)
        return result

    def delete_unattached_ebs(
        self,
        volume_id: str,
        dry_run: bool = True,
        estimated_monthly_cost: Optional[float] = None,
    ) -> RemediationResult:
        """Delete an unattached EBS volume after confirming it is available."""
        savings = self._format_currency(estimated_monthly_cost, "month")

        try:
            volume = self._describe_volume(volume_id)
            attachments = volume.get("Attachments", [])
            state = volume.get("State", "unknown")

            if attachments or state != "available":
                message = (
                    f"Skipped volume {volume_id}: expected unattached volume in "
                    f"'available' state, found state='{state}' with "
                    f"{len(attachments)} attachment(s)."
                )
                result = self._result(
                    success=False,
                    action="DELETE_EBS",
                    resource_id=volume_id,
                    dry_run=dry_run,
                    message=message,
                    savings_estimated=savings,
                    metadata={"state": state, "attachments": attachments},
                )
            else:
                response = self._ec2.delete_volume(VolumeId=volume_id, DryRun=dry_run)
                message = (
                    f"Validated delete_volume for {volume_id}."
                    if dry_run
                    else f"Deleted unattached EBS volume {volume_id}."
                )
                result = self._result(
                    success=True,
                    action="DELETE_EBS",
                    resource_id=volume_id,
                    dry_run=dry_run,
                    message=message,
                    savings_estimated=savings,
                    metadata={"response": response, "state": state},
                )
        except ClientError as exc:
            result = self._handle_client_error(
                exc=exc,
                action="DELETE_EBS",
                resource_id=volume_id,
                dry_run=dry_run,
                success_message="Dry-run validated delete_volume permissions.",
                savings_estimated=savings,
            )
        except ValueError as exc:
            result = self._result(
                success=False,
                action="DELETE_EBS",
                resource_id=volume_id,
                dry_run=dry_run,
                message=str(exc),
                savings_estimated=savings,
            )

        self._append_audit_log(result)
        return result

    def rightsize_ec2(
        self,
        instance_id: str,
        new_type: str,
        current_hourly_cost: float,
        new_hourly_cost: float,
        dry_run: bool = True,
    ) -> RemediationResult:
        """Resize an EC2 instance and report estimated monthly savings."""
        monthly_savings = max(current_hourly_cost - new_hourly_cost, 0) * HOURS_PER_MONTH
        savings = self._format_currency(monthly_savings, "month")

        try:
            instance = self._describe_instance(instance_id)
            current_type = instance["InstanceType"]
            current_state = instance["State"]["Name"]
        except (ClientError, ValueError) as exc:
            result = self._result(
                success=False,
                action="RIGHTSIZE_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                message=str(exc),
                savings_estimated=savings,
                metadata={"new_type": new_type},
            )
            self._append_audit_log(result)
            return result

        if new_type == current_type:
            result = self._result(
                success=False,
                action="RIGHTSIZE_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                message=(
                    f"Skipped rightsizing for {instance_id}: instance is already "
                    f"type {new_type}."
                ),
                savings_estimated=savings,
                metadata={"current_type": current_type, "new_type": new_type},
            )
            self._append_audit_log(result)
            return result

        try:
            if dry_run:
                self._ec2.modify_instance_attribute(
                    InstanceId=instance_id,
                    InstanceType={"Value": new_type},
                    DryRun=True,
                )
                message = (
                    f"Validated rightsize path for {instance_id}: {current_type} -> "
                    f"{new_type}."
                )
            else:
                was_running = current_state == "running"
                if was_running:
                    self._ec2.stop_instances(InstanceIds=[instance_id], DryRun=False)
                    self._ec2.get_waiter("instance_stopped").wait(InstanceIds=[instance_id])

                self._ec2.modify_instance_attribute(
                    InstanceId=instance_id,
                    InstanceType={"Value": new_type},
                    DryRun=False,
                )

                if was_running:
                    self._ec2.start_instances(InstanceIds=[instance_id], DryRun=False)

                message = (
                    f"Resized EC2 instance {instance_id} from {current_type} to {new_type}."
                )

            result = self._result(
                success=True,
                action="RIGHTSIZE_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                message=message,
                savings_estimated=savings,
                metadata={
                    "current_type": current_type,
                    "new_type": new_type,
                    "current_state": current_state,
                },
            )
        except ClientError as exc:
            result = self._handle_client_error(
                exc=exc,
                action="RIGHTSIZE_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                success_message=(
                    f"Dry-run validated modify_instance_attribute for {instance_id}."
                ),
                savings_estimated=savings,
                metadata={"current_type": current_type, "new_type": new_type},
            )

        self._append_audit_log(result)
        return result

    # ── Start EC2 ──────────────────────────────────────────────

    def start_ec2(
        self,
        instance_id: str,
        dry_run: bool = True,
    ) -> RemediationResult:
        """Start a previously stopped EC2 instance."""
        try:
            response = self._ec2.start_instances(
                InstanceIds=[instance_id],
                DryRun=dry_run,
            )
            message = self._build_start_message(response, dry_run)
            result = self._result(
                success=True,
                action="START_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                message=message,
                metadata={"response": response},
            )
        except ClientError as exc:
            result = self._handle_client_error(
                exc=exc,
                action="START_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                success_message="Dry-run validated start_instances permissions.",
            )
        except ValueError as exc:
            result = self._result(
                success=False,
                action="START_EC2",
                resource_id=instance_id,
                dry_run=dry_run,
                message=str(exc),
            )

        self._append_audit_log(result)
        return result

    # ── Snapshot + Delete EBS ─────────────────────────────────

    def snapshot_and_delete_ebs(
        self,
        volume_id: str,
        dry_run: bool = True,
        estimated_monthly_cost: Optional[float] = None,
    ) -> RemediationResult:
        """Create a snapshot of an EBS volume, then delete the volume.

        This is a safer alternative to `delete_unattached_ebs` — you keep
        a backup snapshot before removing the volume.
        """
        savings = self._format_currency(estimated_monthly_cost, "month")

        try:
            volume = self._describe_volume(volume_id)
            attachments = volume.get("Attachments", [])
            state = volume.get("State", "unknown")

            if attachments or state != "available":
                message = (
                    f"Skipped volume {volume_id}: expected unattached volume in "
                    f"'available' state, found state='{state}' with "
                    f"{len(attachments)} attachment(s)."
                )
                result = self._result(
                    success=False,
                    action="SNAPSHOT_AND_DELETE_EBS",
                    resource_id=volume_id,
                    dry_run=dry_run,
                    message=message,
                    savings_estimated=savings,
                    metadata={"state": state, "attachments": attachments},
                )
                self._append_audit_log(result)
                return result

            # Step 1: create snapshot
            if dry_run:
                self._ec2.create_snapshot(
                    VolumeId=volume_id,
                    Description=f"CloudCFO backup before deleting {volume_id}",
                    DryRun=True,
                )
            else:
                snap_response = self._ec2.create_snapshot(
                    VolumeId=volume_id,
                    Description=f"CloudCFO backup before deleting {volume_id}",
                    DryRun=False,
                )
                snapshot_id = snap_response["SnapshotId"]
                logger.info(
                    "Created snapshot %s for volume %s", snapshot_id, volume_id
                )

                # Wait for snapshot to complete before deleting
                self._ec2.get_waiter("snapshot_completed").wait(
                    SnapshotIds=[snapshot_id]
                )

                # Step 2: delete volume
                self._ec2.delete_volume(VolumeId=volume_id, DryRun=False)
                message = (
                    f"Snapshot {snapshot_id} created and volume {volume_id} deleted."
                )
                result = self._result(
                    success=True,
                    action="SNAPSHOT_AND_DELETE_EBS",
                    resource_id=volume_id,
                    dry_run=False,
                    message=message,
                    savings_estimated=savings,
                    metadata={"snapshot_id": snapshot_id, "state": state},
                )
                self._append_audit_log(result)
                return result

            # If we reach here in dry_run, the snapshot DryRun would have
            # raised DryRunOperation — handled below
            result = self._result(
                success=True,
                action="SNAPSHOT_AND_DELETE_EBS",
                resource_id=volume_id,
                dry_run=True,
                message=f"Validated snapshot + delete path for {volume_id}.",
                savings_estimated=savings,
            )
        except ClientError as exc:
            result = self._handle_client_error(
                exc=exc,
                action="SNAPSHOT_AND_DELETE_EBS",
                resource_id=volume_id,
                dry_run=dry_run,
                success_message=(
                    f"Dry-run validated snapshot + delete for {volume_id}."
                ),
                savings_estimated=savings,
            )
        except ValueError as exc:
            result = self._result(
                success=False,
                action="SNAPSHOT_AND_DELETE_EBS",
                resource_id=volume_id,
                dry_run=dry_run,
                message=str(exc),
                savings_estimated=savings,
            )

        self._append_audit_log(result)
        return result

    # ── List Available Actions ────────────────────────────────

    @staticmethod
    def list_actions() -> list[str]:
        """Return all supported remediation action types."""
        return list(ACTION_TYPES)

    # ── Internal Helpers ──────────────────────────────────────

    def _describe_instance(self, instance_id: str) -> dict[str, Any]:
        response = self._ec2.describe_instances(InstanceIds=[instance_id])
        reservations = response.get("Reservations", [])
        if not reservations or not reservations[0].get("Instances"):
            raise ValueError(f"Instance {instance_id} was not found.")
        return reservations[0]["Instances"][0]

    def _describe_volume(self, volume_id: str) -> dict[str, Any]:
        response = self._ec2.describe_volumes(VolumeIds=[volume_id])
        volumes = response.get("Volumes", [])
        if not volumes:
            raise ValueError(f"Volume {volume_id} was not found.")
        return volumes[0]

    def _append_audit_log(self, result: RemediationResult) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": result.action,
            "resource_id": result.resource_id,
            "mode": result.mode,
            "success": result.success,
            "message": result.message,
            "savings_estimated": result.savings_estimated,
        }
        if result.metadata:
            entry["metadata"] = result.metadata

        existing_entries: list[dict[str, Any]] = []
        if self._audit_log_path.exists():
            with self._audit_log_path.open("r", encoding="utf-8") as file:
                try:
                    existing_entries = json.load(file)
                except JSONDecodeError:
                    existing_entries = []

        existing_entries.append(entry)
        self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._audit_log_path.open("w", encoding="utf-8") as file:
            json.dump(existing_entries, file, indent=2)

    def _build_stop_message(self, response: dict[str, Any], dry_run: bool) -> str:
        if dry_run:
            return "Validated stop_instances request."

        stopping_instances = response.get("StoppingInstances", [])
        if not stopping_instances:
            return "Stop request submitted."

        state_change = stopping_instances[0]
        previous_state = state_change.get("PreviousState", {}).get("Name", "unknown")
        current_state = state_change.get("CurrentState", {}).get("Name", "unknown")
        return (
            f"Stop requested successfully ({previous_state} -> {current_state})."
        )

    def _build_start_message(self, response: dict[str, Any], dry_run: bool) -> str:
        if dry_run:
            return "Validated start_instances request."

        starting_instances = response.get("StartingInstances", [])
        if not starting_instances:
            return "Start request submitted."

        state_change = starting_instances[0]
        previous_state = state_change.get("PreviousState", {}).get("Name", "unknown")
        current_state = state_change.get("CurrentState", {}).get("Name", "unknown")
        return (
            f"Start requested successfully ({previous_state} -> {current_state})."
        )

    def _handle_client_error(
        self,
        exc: ClientError,
        action: str,
        resource_id: str,
        dry_run: bool,
        success_message: str,
        savings_estimated: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RemediationResult:
        error_code = exc.response.get("Error", {}).get("Code")
        if dry_run and error_code == "DryRunOperation":
            return self._result(
                success=True,
                action=action,
                resource_id=resource_id,
                dry_run=True,
                message=success_message,
                savings_estimated=savings_estimated,
                metadata=metadata,
            )

        message = exc.response.get("Error", {}).get("Message", str(exc))
        return self._result(
            success=False,
            action=action,
            resource_id=resource_id,
            dry_run=dry_run,
            message=message,
            savings_estimated=savings_estimated,
            metadata=metadata,
        )

    def _result(
        self,
        success: bool,
        action: str,
        resource_id: str,
        dry_run: bool,
        message: str,
        savings_estimated: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RemediationResult:
        return RemediationResult(
            success=success,
            action=action,
            resource_id=resource_id,
            mode="DRY_RUN" if dry_run else "LIVE",
            message=message,
            savings_estimated=savings_estimated,
            metadata=metadata,
        )

    def _format_savings(
        self,
        hourly_cost: Optional[float],
        unit: str,
        multiplier: int,
    ) -> Optional[str]:
        if hourly_cost is None:
            return None
        return self._format_currency(hourly_cost * multiplier, unit)

    def _format_currency(self, amount: Optional[float], unit: str) -> Optional[str]:
        if amount is None:
            return None
        return f"${amount:,.2f}/{unit}"

    def as_dict(self, result: RemediationResult) -> dict[str, Any]:
        """Convert a remediation result to a serialisable dictionary."""
        return asdict(result)


# ══════════════════════════════════════════════════════════════════
#  Confirmation Gate — operator approval before live execution
# ══════════════════════════════════════════════════════════════════


@dataclass
class PendingAction:
    """An action waiting for operator approval."""

    action_id: str
    action_type: str
    resource_id: str
    description: str
    dry_run_result: RemediationResult
    kwargs: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: str = "pending"  # pending | approved | rejected | executed


class ConfirmationGate:
    """Wraps the RemediationEngine with an approval step.

    Workflow:
        1. Call `propose()` — runs the action in dry_run mode,
           stores it as a pending action.
        2. Call `approve(action_id)` or `reject(action_id)` — operator
           reviews and decides.
        3. On approval, `execute(action_id)` runs the action for real.

    This ensures no live remediation happens without explicit operator
    consent.
    """

    def __init__(self, engine: RemediationEngine):
        self._engine = engine
        self._pending: dict[str, PendingAction] = {}
        self._history: list[PendingAction] = []

    # ── Propose ───────────────────────────────────────────────

    def propose_stop_ec2(
        self,
        instance_id: str,
        estimated_hourly_cost: Optional[float] = None,
    ) -> PendingAction:
        """Dry-run a stop and queue it for approval."""
        dry_result = self._engine.stop_idle_ec2(
            instance_id=instance_id,
            dry_run=True,
            estimated_hourly_cost=estimated_hourly_cost,
        )
        return self._queue(
            action_id=f"stop-{instance_id}-{self._ts()}",
            action_type="STOP_EC2",
            resource_id=instance_id,
            description=f"Stop idle EC2 instance {instance_id}",
            dry_run_result=dry_result,
            kwargs={"estimated_hourly_cost": estimated_hourly_cost},
        )

    def propose_start_ec2(
        self,
        instance_id: str,
    ) -> PendingAction:
        """Dry-run a start and queue it for approval."""
        dry_result = self._engine.start_ec2(
            instance_id=instance_id,
            dry_run=True,
        )
        return self._queue(
            action_id=f"start-{instance_id}-{self._ts()}",
            action_type="START_EC2",
            resource_id=instance_id,
            description=f"Start EC2 instance {instance_id}",
            dry_run_result=dry_result,
        )

    def propose_delete_ebs(
        self,
        volume_id: str,
        estimated_monthly_cost: Optional[float] = None,
    ) -> PendingAction:
        """Dry-run a volume delete and queue it for approval."""
        dry_result = self._engine.delete_unattached_ebs(
            volume_id=volume_id,
            dry_run=True,
            estimated_monthly_cost=estimated_monthly_cost,
        )
        return self._queue(
            action_id=f"delete-ebs-{volume_id}-{self._ts()}",
            action_type="DELETE_EBS",
            resource_id=volume_id,
            description=f"Delete unattached EBS volume {volume_id}",
            dry_run_result=dry_result,
            kwargs={"estimated_monthly_cost": estimated_monthly_cost},
        )

    def propose_snapshot_and_delete_ebs(
        self,
        volume_id: str,
        estimated_monthly_cost: Optional[float] = None,
    ) -> PendingAction:
        """Dry-run snapshot+delete and queue it for approval."""
        dry_result = self._engine.snapshot_and_delete_ebs(
            volume_id=volume_id,
            dry_run=True,
            estimated_monthly_cost=estimated_monthly_cost,
        )
        return self._queue(
            action_id=f"snap-del-{volume_id}-{self._ts()}",
            action_type="SNAPSHOT_AND_DELETE_EBS",
            resource_id=volume_id,
            description=f"Snapshot + delete EBS volume {volume_id}",
            dry_run_result=dry_result,
            kwargs={"estimated_monthly_cost": estimated_monthly_cost},
        )

    def propose_rightsize_ec2(
        self,
        instance_id: str,
        new_type: str,
        current_hourly_cost: float,
        new_hourly_cost: float,
    ) -> PendingAction:
        """Dry-run a rightsize and queue it for approval."""
        dry_result = self._engine.rightsize_ec2(
            instance_id=instance_id,
            new_type=new_type,
            current_hourly_cost=current_hourly_cost,
            new_hourly_cost=new_hourly_cost,
            dry_run=True,
        )
        return self._queue(
            action_id=f"rightsize-{instance_id}-{self._ts()}",
            action_type="RIGHTSIZE_EC2",
            resource_id=instance_id,
            description=f"Rightsize {instance_id} to {new_type}",
            dry_run_result=dry_result,
            kwargs={
                "new_type": new_type,
                "current_hourly_cost": current_hourly_cost,
                "new_hourly_cost": new_hourly_cost,
            },
        )

    # ── Approve / Reject / Execute ────────────────────────────

    def approve(self, action_id: str) -> PendingAction:
        """Mark a pending action as approved."""
        action = self._get_pending(action_id)
        action.status = "approved"
        logger.info("Action %s approved by operator.", action_id)
        return action

    def reject(self, action_id: str, reason: str = "") -> PendingAction:
        """Reject a pending action. It will NOT be executed."""
        action = self._get_pending(action_id)
        action.status = "rejected"
        del self._pending[action_id]
        self._history.append(action)
        logger.info("Action %s rejected. Reason: %s", action_id, reason or "none")
        return action

    def execute(self, action_id: str) -> RemediationResult:
        """Execute an approved action for real (dry_run=False).

        Raises ValueError if the action is not in 'approved' status.
        """
        action = self._get_pending(action_id)
        if action.status != "approved":
            raise ValueError(
                f"Action {action_id} is '{action.status}', not 'approved'. "
                f"Call approve() first."
            )

        result = self._dispatch_live(action)
        action.status = "executed"
        del self._pending[action_id]
        self._history.append(action)
        return result

    # ── Query helpers ─────────────────────────────────────────

    def list_pending(self) -> list[PendingAction]:
        """Return all actions awaiting approval."""
        return list(self._pending.values())

    def list_history(self) -> list[PendingAction]:
        """Return all completed/rejected actions."""
        return list(self._history)

    def get_action(self, action_id: str) -> PendingAction:
        """Look up any action by ID (pending or historical)."""
        if action_id in self._pending:
            return self._pending[action_id]
        for a in self._history:
            if a.action_id == action_id:
                return a
        raise KeyError(f"Action {action_id} not found.")

    # ── Internal ──────────────────────────────────────────────

    def _queue(
        self,
        action_id: str,
        action_type: str,
        resource_id: str,
        description: str,
        dry_run_result: RemediationResult,
        kwargs: Optional[dict[str, Any]] = None,
    ) -> PendingAction:
        pa = PendingAction(
            action_id=action_id,
            action_type=action_type,
            resource_id=resource_id,
            description=description,
            dry_run_result=dry_run_result,
            kwargs=kwargs or {},
        )
        self._pending[action_id] = pa
        logger.info(
            "Queued %s on %s for approval (dry-run %s).",
            action_type,
            resource_id,
            "passed" if dry_run_result.success else "FAILED",
        )
        return pa

    def _get_pending(self, action_id: str) -> PendingAction:
        if action_id not in self._pending:
            raise KeyError(f"No pending action with ID '{action_id}'.")
        return self._pending[action_id]

    def _dispatch_live(self, action: PendingAction) -> RemediationResult:
        """Route an approved action to the right engine method with dry_run=False."""
        kw = action.kwargs
        if action.action_type == "STOP_EC2":
            return self._engine.stop_idle_ec2(
                instance_id=action.resource_id,
                dry_run=False,
                estimated_hourly_cost=kw.get("estimated_hourly_cost"),
            )
        if action.action_type == "START_EC2":
            return self._engine.start_ec2(
                instance_id=action.resource_id,
                dry_run=False,
            )
        if action.action_type == "DELETE_EBS":
            return self._engine.delete_unattached_ebs(
                volume_id=action.resource_id,
                dry_run=False,
                estimated_monthly_cost=kw.get("estimated_monthly_cost"),
            )
        if action.action_type == "SNAPSHOT_AND_DELETE_EBS":
            return self._engine.snapshot_and_delete_ebs(
                volume_id=action.resource_id,
                dry_run=False,
                estimated_monthly_cost=kw.get("estimated_monthly_cost"),
            )
        if action.action_type == "RIGHTSIZE_EC2":
            return self._engine.rightsize_ec2(
                instance_id=action.resource_id,
                new_type=kw["new_type"],
                current_hourly_cost=kw["current_hourly_cost"],
                new_hourly_cost=kw["new_hourly_cost"],
                dry_run=False,
            )
        raise ValueError(f"Unknown action type: {action.action_type}")

    @staticmethod
    def _ts() -> str:
        """Short timestamp for unique action IDs."""
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
