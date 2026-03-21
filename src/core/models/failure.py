# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Failure classification enums for triage."""

from enum import Enum


class FailureClass(str, Enum):
    """Classification of SAP cluster failure types.

    Each value represents a distinct failure mode that the triage
    engine can identify. New failure classes are added as the
    knowledge base grows.
    """

    FENCING_NOT_TRIGGERED = "fencing_not_triggered"
    WRONG_FS_TYPE = "wrong_fs_type"
    HSR_SYNC_FAILURE = "hsr_sync_failure"
    HSR_TAKEOVER_FAILURE = "hsr_takeover_failure"
    RESOURCE_NOT_STARTED = "resource_not_started"
    RESOURCE_NOT_PROMOTED = "resource_not_promoted"
    CONSTRAINT_BLOCKING = "constraint_blocking"
    QUORUM_LOSS = "quorum_loss"
    SPLIT_BRAIN = "split_brain"
    SBD_FAILURE = "sbd_failure"
    ENQUEUE_REPLICATION_FAILURE = "enqueue_replication_failure"
    SAPSTARTSRV_FAILURE = "sapstartsrv_failure"
    LOAD_BALANCER_MISCONFIGURED = "load_balancer_misconfigured"
    OS_CONFIG_DRIFT = "os_config_drift"
    STORAGE_THROTTLING = "storage_throttling"
    NETWORK_ISOLATION = "network_isolation"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    """Severity level for triage findings.

    Aligned with the existing ``TestSeverity`` in ``module_utils.enums``
    but used independently by the triage layer.
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
