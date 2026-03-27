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
        """
        Create a RemediationEngine configured for a specific AWS region, with an EC2 client and audit log path.
        
        Parameters:
            region_name (str): AWS region to target for the EC2 client (default "us-east-1").
            audit_log_path (Path | str): Filesystem path to the JSON audit log file; will be converted to a Path.
            session (boto3.session.Session | None): Optional boto3 session to use; if omitted a new session is created for `region_name`.
        """
        self._session = session or boto3.Session(region_name=region_name)
        self._ec2 = self._session.client("ec2")
        self._audit_log_path = Path(audit_log_path)

    def stop_idle_ec2(
        self,
        instance_id: str,
        dry_run: bool = True,
        estimated_hourly_cost: Optional[float] = None,
    ) -> RemediationResult:
        """
        Attempt to stop the specified EC2 instance (dry-run by default) and record the outcome to the audit log.
        
        Parameters:
            instance_id (str): The ID of the EC2 instance to stop.
            dry_run (bool): If True, validate permissions and request without making changes.
            estimated_hourly_cost (Optional[float]): Hourly cost in USD used to compute estimated daily savings; pass None to omit savings.
        
        Returns:
            RemediationResult: Result object containing success status, action ("STOP_EC2"), resource id, mode ("DRY_RUN" or "LIVE"), a human-readable message, optional `savings_estimated`, and optional `metadata` with API response details.
        """
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
        """
        Delete an unattached EBS volume after validating it is in the `available` state.
        
        Parameters:
            volume_id (str): The ID of the EBS volume to delete.
            dry_run (bool): If True, validate permissions without performing deletion.
            estimated_monthly_cost (Optional[float]): Monthly cost used to compute an estimated savings string; if None no savings are recorded.
        
        Returns:
            RemediationResult: Result of the attempted deletion. `success` is `True` when the delete (or dry-run validation) succeeded. If the volume was skipped because it was attached or not `available`, `success` is `False` and `metadata` contains the volume `state` and `attachments`. On success `metadata` includes the service `response` (for live or dry-run) and the `state`.
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
        """
        Resize an EC2 instance to a target instance type (or validate the change in dry-run) and record an estimated monthly savings.
        
        Parameters:
            instance_id: EC2 instance identifier to resize.
            new_type: Target EC2 instance type to apply.
            current_hourly_cost: Current instance hourly cost used to estimate savings.
            new_hourly_cost: Proposed instance hourly cost used to estimate savings.
            dry_run: If True, validate permissions and API calls without performing changes; if False, perform the live resize (stopping and restarting the instance if needed).
        
        Returns:
            RemediationResult: Summary of the operation. `success` indicates whether the validation or live action succeeded; `mode` is set to `DRY_RUN` or `LIVE`; `savings_estimated` contains a formatted monthly savings string when cost inputs are provided.
        """
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
        """
        Start a previously stopped EC2 instance.
        
        Parameters:
            dry_run (bool): If True, validate permissions and call the API with DryRun (no state change); if False, perform the live start.
        
        Returns:
            RemediationResult: The operation outcome; `success` is `true` for a successful start or for a dry-run validation, `false` otherwise. The `mode` field will be set to `DRY_RUN` or `LIVE` accordingly and `metadata` may include the raw AWS response.
        """
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
        """
        Create a snapshot of an unattached, available EBS volume and then delete the volume.
        
        If the volume has attachments or is not in the "available" state, the operation is skipped and a failed result is returned with metadata describing the volume's state and attachments. In dry-run mode, the snapshot+delete path and required permissions are validated without making any changes. In live mode, a snapshot is created and waited on to complete before the volume is deleted; on success the result's metadata includes the created `snapshot_id` and the volume `state`.
        
        Returns:
            RemediationResult: Outcome of the operation including `success`, `action`, `resource_id`, `mode` (`"DRY_RUN"` or `"LIVE"`), a human-readable `message`, optional `savings_estimated`, and optional `metadata` (e.g., `{"snapshot_id": ..., "state": ...}` on success).
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
        """
        List supported remediation action type identifiers.
        
        Returns:
            list[str]: Supported action type strings.
        """
        return list(ACTION_TYPES)

    # ── Internal Helpers ──────────────────────────────────────

    def _describe_instance(self, instance_id: str) -> dict[str, Any]:
        """
        Retrieve the EC2 instance description for the given instance ID.
        
        Parameters:
            instance_id (str): The EC2 instance identifier to describe.
        
        Returns:
            dict: The instance dictionary for the first matching instance as returned by boto3's describe_instances.
        
        Raises:
            ValueError: If no matching instance is found for the provided instance_id.
        """
        response = self._ec2.describe_instances(InstanceIds=[instance_id])
        reservations = response.get("Reservations", [])
        if not reservations or not reservations[0].get("Instances"):
            raise ValueError(f"Instance {instance_id} was not found.")
        return reservations[0]["Instances"][0]

    def _describe_volume(self, volume_id: str) -> dict[str, Any]:
        """
        Return the described EBS volume information for the given volume ID.
        
        Parameters:
            volume_id (str): The ID of the EBS volume to describe.
        
        Returns:
            dict: The volume dictionary returned by EC2 for the specified volume.
        
        Raises:
            ValueError: If no volume matching `volume_id` is found.
        """
        response = self._ec2.describe_volumes(VolumeIds=[volume_id])
        volumes = response.get("Volumes", [])
        if not volumes:
            raise ValueError(f"Volume {volume_id} was not found.")
        return volumes[0]

    def _append_audit_log(self, result: RemediationResult) -> None:
        """
        Append a remediation result to the engine's JSON audit log on disk.
        
        Adds an entry containing timestamp, action, resource_id, mode, success, message, optional savings_estimated, and optional metadata to the configured audit_log.json file. If the file exists and contains valid JSON, the new entry is appended to the existing list; if the file exists but contains invalid JSON, the file is treated as empty and overwritten. Ensures the audit directory exists before writing.
        
        Parameters:
            result (RemediationResult): The remediation outcome to record.
        
        """
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
        """
        Builds a human-readable message describing the outcome of an EC2 stop_instances call.
        
        Parameters:
            response (dict): The raw AWS EC2 `stop_instances` response dictionary.
            dry_run (bool): If True, indicates the call was a dry-run validation.
        
        Returns:
            str: A message summarizing the result. Possible forms:
                - "Validated stop_instances request." when `dry_run` is True.
                - "Stop request submitted." when response lacks instance state details.
                - "Stop requested successfully (PreviousState -> CurrentState)." when state change information is present.
        """
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
        """
        Builds a human-readable message describing the outcome of an EC2 `start_instances` call.
        
        Parameters:
            response (dict[str, Any]): The raw response returned by the EC2 `start_instances` API call; may contain a `"StartingInstances"` list with state transitions.
            dry_run (bool): If True, indicates the call was a dry-run validation.
        
        Returns:
            str: A message summarizing the outcome. Possible messages:
                - "Validated start_instances request." (when dry_run is True)
                - "Start requested successfully (<PreviousState> -> <CurrentState>)." (when a state transition is present)
                - "Start request submitted." (when no instance state details are available)
        """
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
        """
        Convert an AWS ClientError into a RemediationResult, treating a dry-run `DryRunOperation` as success.
        
        If `exc` indicates a dry-run permission check (`Error.Code == "DryRunOperation"`) and `dry_run` is True, returns a successful result using `success_message`. Otherwise returns a failed result using the AWS error message extracted from the exception.
        
        Parameters:
            exc (ClientError): The caught boto3 ClientError.
            dry_run (bool): Whether the original operation was a dry-run; enables DryRunOperation handling.
            success_message (str): Message to use when a dry-run validation is accepted.
            savings_estimated (Optional[str]): Optional formatted savings estimate to include in the result.
            metadata (Optional[dict[str, Any]]): Optional additional metadata to include in the result.
        
        Returns:
            RemediationResult: `success=True` with `success_message` when dry-run validation passes; otherwise `success=False` with the AWS error message.
        """
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
        """
        Create a RemediationResult representing the outcome of an attempted remediation and set its mode to either "DRY_RUN" or "LIVE".
        
        Returns:
            RemediationResult: The result object containing success, action, resource_id, mode ("DRY_RUN" when `dry_run` is True, otherwise "LIVE"), message, and optional savings_estimated and metadata.
        """
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
        """
        Format an estimated savings amount by scaling an hourly cost and returning it as a currency string for a given unit.
        
        Parameters:
        	hourly_cost (Optional[float]): Hourly cost to scale. If `None`, no savings are available.
        	unit (str): Unit label to include in the formatted result (e.g., "month", "day").
        	multiplier (int): Factor to multiply `hourly_cost` by (for example, hours per month).
        
        Returns:
        	(Optional[str]): Formatted currency string like "$X.XX/{unit}", or `None` if `hourly_cost` is `None`.
        """
        if hourly_cost is None:
            return None
        return self._format_currency(hourly_cost * multiplier, unit)

    def _format_currency(self, amount: Optional[float], unit: str) -> Optional[str]:
        """
        Format a monetary amount as a currency string with a unit suffix.
        
        Parameters:
            amount (Optional[float]): The numeric amount to format; if None, no string is produced.
            unit (str): Unit label appended after the currency (e.g., "hour", "month", "hr").
        
        Returns:
            Optional[str]: A string like "$1,234.56/{unit}" when amount is provided, or `None` when amount is `None`.
        """
        if amount is None:
            return None
        return f"${amount:,.2f}/{unit}"

    def as_dict(self, result: RemediationResult) -> dict[str, Any]:
        """
        Convert a RemediationResult into a JSON-serializable dictionary.
        
        Returns:
            dict: A dictionary representation of `result` suitable for JSON serialization.
        """
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
        """
        Initialize the ConfirmationGate with a RemediationEngine and empty in-memory queues for pending and historical actions.
        
        Parameters:
        	engine (RemediationEngine): Engine used to perform dry-run proposals and live remediation executions.
        """
        self._engine = engine
        self._pending: dict[str, PendingAction] = {}
        self._history: list[PendingAction] = []

    # ── Propose ───────────────────────────────────────────────

    def propose_stop_ec2(
        self,
        instance_id: str,
        estimated_hourly_cost: Optional[float] = None,
    ) -> PendingAction:
        """
        Create and queue a proposed stop action after performing a dry-run stop of the specified EC2 instance.
        
        Parameters:
            instance_id (str): The ID of the EC2 instance to propose stopping.
            estimated_hourly_cost (Optional[float]): Hourly cost used to compute a savings estimate; may be None.
        
        Returns:
            PendingAction: A pending action record containing the dry-run result and execution kwargs.
        """
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
        """
        Queue a start-EC2 action for operator approval after validating the operation with a dry-run.
        
        Returns:
            PendingAction: The queued pending action for the start request, containing the dry-run `RemediationResult` and initial status `"pending"`.
        """
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
        """
        Create a pending delete action for an unattached EBS volume by performing a dry-run and queuing the result for operator approval.
        
        Parameters:
            volume_id (str): The ID of the EBS volume to delete.
            estimated_monthly_cost (Optional[float]): Estimated monthly cost savings used for messaging and audit records.
        
        Returns:
            PendingAction: A pending action record containing the dry-run RemediationResult and execution kwargs.
        """
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
        """
        Create a pending action by performing a dry-run snapshot-and-delete of an EBS volume and queuing it for operator approval.
        
        Parameters:
            volume_id (str): The ID of the EBS volume to snapshot and delete.
            estimated_monthly_cost (Optional[float]): Optional monthly cost used to compute and attach a savings estimate to the dry-run result.
        
        Returns:
            PendingAction: A queued pending action containing the dry-run RemediationResult and the execution kwargs required to perform the live snapshot-and-delete.
        """
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
        """
        Create a pending rightsize action by performing a dry-run resize and queuing it for operator approval.
        
        Parameters:
            instance_id (str): EC2 instance identifier to rightsize.
            new_type (str): Target instance type to apply if approved.
            current_hourly_cost (float): Current instance hourly cost used to estimate savings.
            new_hourly_cost (float): Proposed instance hourly cost used to estimate savings.
        
        Returns:
            PendingAction: The queued pending action containing the dry-run RemediationResult and execution kwargs.
        """
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
        """
        Approve the pending action identified by `action_id`, marking it ready for execution.
        
        Parameters:
            action_id (str): The unique identifier of the pending action to approve.
        
        Returns:
            PendingAction: The updated pending action with its `status` set to `"approved"`.
        
        Raises:
            KeyError: If no pending action exists for the given `action_id`.
        """
        action = self._get_pending(action_id)
        action.status = "approved"
        logger.info("Action %s approved by operator.", action_id)
        return action

    def reject(self, action_id: str, reason: str = "") -> PendingAction:
        """
        Mark a pending action as rejected and move it from the pending queue into history.
        
        Parameters:
        	action_id (str): Identifier of the pending action to reject.
        	reason (str): Optional textual reason for the rejection; used for logging.
        
        Returns:
        	PendingAction: The rejected action with its status set to `"rejected"`.
        """
        action = self._get_pending(action_id)
        action.status = "rejected"
        del self._pending[action_id]
        self._history.append(action)
        logger.info("Action %s rejected. Reason: %s", action_id, reason or "none")
        return action

    def execute(self, action_id: str) -> RemediationResult:
        """
        Execute a previously approved pending action in live mode and record its execution.
        
        Dispatches the pending action to the engine with live execution (no dry-run), updates the action's status to "executed", moves it from pending to history, and returns the remediation result.
        
        Returns:
            RemediationResult: The outcome of performing the action.
        
        Raises:
            ValueError: If the action is not in "approved" status.
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
        """
        List all pending actions awaiting operator decision.
        
        Returns:
            pending_actions (list[PendingAction]): List of PendingAction objects currently queued for approval.
        """
        return list(self._pending.values())

    def list_history(self) -> list[PendingAction]:
        """
        Return the list of actions that have been executed or rejected.
        
        Returns:
            list[PendingAction]: A copy of historical `PendingAction` records with status `executed` or `rejected`.
        """
        return list(self._history)

    def get_action(self, action_id: str) -> PendingAction:
        """
        Look up a pending or historical action by its action ID.
        
        Returns:
            action (PendingAction): The matching pending or historical action.
        
        Raises:
            KeyError: If no action with the given ID exists.
        """
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
        """
        Create and store a PendingAction for operator approval and return it.
        
        Parameters:
        	action_id (str): Unique identifier for the pending action.
        	action_type (str): Action category string (e.g., "STOP_EC2", "DELETE_EBS").
        	resource_id (str): Target resource identifier (instance or volume ID).
        	description (str): Human-readable description of the proposed action.
        	dry_run_result (RemediationResult): Result produced by executing the action in dry-run mode.
        	kwargs (dict[str, Any], optional): Execution parameters to be used if the action is approved.
        
        Returns:
        	PendingAction: The pending action object that was created and stored in the gate's pending queue.
        """
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
        """
        Retrieve a pending PendingAction by its action identifier.
        
        Parameters:
        	action_id (str): Identifier of the pending action to fetch.
        
        Returns:
        	PendingAction: The matching pending action.
        
        Raises:
        	KeyError: If no pending action exists with the given `action_id`.
        """
        if action_id not in self._pending:
            raise KeyError(f"No pending action with ID '{action_id}'.")
        return self._pending[action_id]

    def _dispatch_live(self, action: PendingAction) -> RemediationResult:
        """
        Execute the given pending action against the underlying RemediationEngine in live mode.
        
        Returns:
            RemediationResult: The result produced by the engine call for the dispatched action.
        
        Raises:
            ValueError: If the action's `action_type` is not recognized.
        """
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
        """
        Produce a UTC timestamp string suitable for use in unique action IDs.
        
        Returns:
            timestamp (str): UTC timestamp formatted as YYYYmmddHHMMSS.
        """
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
