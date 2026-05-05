# SAP HA Functional Testing

Execute high-availability functional tests against SAP Pacemaker clusters on Azure using the SAP Testing Automation Framework (STAF). This skill validates failover behavior, cluster configuration, and resilience of SAP HANA and SAP Central Services deployments.

---

## Test Groups

### DatabaseHighAvailability (HA_DB_HANA) — 15 scenarios

| Test Case | Description | Destructive? | Topology |
|-----------|-------------|--------------|----------|
| ha-config | Online HA configuration validation (Pacemaker, Corosync, SBD, HANA SR) | No | Scale-Up, Scale-Out HSR, Scale-Out Standby |
| ha-config-offline | Offline HA validation using cached CIB files | No | Scale-Up, Scale-Out HSR |
| azure-lb | Azure Load Balancer health probe and backend pool validation | No | Scale-Up, Scale-Out HSR |
| resource-migration | Controlled resource movement between HANA nodes | Yes | Scale-Up, Scale-Out HSR |
| primary-node-crash | Simulate primary node crash via kernel panic | Yes | Scale-Up, Scale-Out HSR |
| primary-node-kill | Kill primary node HANA processes | Yes | Scale-Up, Scale-Out HSR |
| primary-crash-index | Crash primary HANA indexserver process | Yes | Scale-Up, Scale-Out HSR |
| primary-echo-b | Echo b to /proc/sysrq-trigger on primary | Yes | Scale-Up, Scale-Out HSR |
| secondary-node-kill | Kill secondary node HANA processes | Yes | Scale-Up, Scale-Out HSR |
| secondary-crash-index | Crash secondary HANA indexserver process | Yes | Scale-Up, Scale-Out HSR |
| secondary-echo-b | Echo b to /proc/sysrq-trigger on secondary | Yes | Scale-Up, Scale-Out HSR |
| block-network | Block network between cluster nodes | Yes | Scale-Up, Scale-Out HSR |
| block-hana-shared | Block access to HANA shared filesystem | Yes | Scale-Up |
| fs-freeze | Freeze ANF filesystem | Yes | Scale-Up |
| sbd-fencing | Test SBD-based fencing | Yes | Scale-Up |

### SCSHighAvailability (HA_SCS) — 14 scenarios

| Test Case | Description | Destructive? |
|-----------|-------------|--------------|
| ha-config | SCS/ERS online HA configuration validation | No |
| ha-config-offline | SCS/ERS offline HA validation | No |
| azure-lb | SCS Azure Load Balancer validation | No |
| sapcontrol-config | SAP control configuration validation | No |
| ascs-migration | ASCS resource migration to other node | Yes |
| ascs-node-crash | Crash the ASCS node | Yes |
| kill-message-server | Kill SAP message server process | Yes |
| kill-enqueue-server | Kill SAP enqueue server process | Yes |
| kill-enqueue-replication | Kill enqueue replication server | Yes |
| kill-sapstartsrv-process | Kill SAPStartSrv process | Yes |
| manual-restart | Manual restart of SAP services | Yes |
| ha-failover-to-node | Forced failover to specific node | Yes |
| block-network | Block network between SCS nodes | Yes |

---

## Procedure

1. **Select Tests**: Choose test group and specific test cases based on validation objective.
2. **Execute**: `run_staf_test(workspace_id, test_group, test_ids)` — submit the test job.
3. **Monitor**: `get_job_status(job_id)` — poll every 10–15 seconds until the job reaches a terminal state.
4. **Results**: `get_job_results(job_id)` — retrieve structured test outcomes with pass/fail status per test case.
5. **Investigate Failures**: Use the SAP Cluster Triage skill for root cause analysis on any failed test cases.

---

## Safety

- ⚠️ **Destructive tests cause SAP service interruption.** They trigger real failovers, process kills, and network isolation on live cluster nodes.
- Destructive tests must run only during approved maintenance windows.
- The agent **must** obtain explicit user approval before executing any destructive test.
- **Non-destructive tests** (`ha-config`, `ha-config-offline`, `azure-lb`, `sapcontrol-config`) are safe to run at any time — they perform read-only validation.
- All test execution is logged and results are persisted for audit.

---

## When to Use

- **Post-deployment HA validation** — confirm failover works after initial SAP cluster setup.
- **Periodic HA health verification** — schedule weekly non-destructive tests to detect configuration drift.
- **Pre/post-maintenance failover testing** — verify cluster behavior before and after planned maintenance.
- **After cluster configuration changes** — validate that Pacemaker, Corosync, or SBD changes did not break HA.
- **Compliance verification** — produce evidence that HA mechanisms function as documented.
