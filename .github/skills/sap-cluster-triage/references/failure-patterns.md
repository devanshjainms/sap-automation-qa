# Common Failure Patterns

Reference material for SAP cluster triage. Use these patterns to match symptoms
against known root causes during incident investigation.

## Pattern 1: HSR Sync Failure After Takeover

**Symptoms:**

- Takeover completed but former primary cannot register as secondary
- `hdbnsutil -sr_state` shows `SFAIL` or registration error
- Pacemaker shows resource in `Failed` or `Stopped` state on one node

**Root Causes:**

1. **`AUTOMATED_REGISTER` is `false`** — manual `hdbnsutil -sr_register` required
2. **Network partition healed** — former primary came back as a second primary (duplicate primary)
3. **Data divergence** — log positions incompatible; HANA refuses to register
4. **`DUPLICATE_PRIMARY_TIMEOUT` too short** — secondary was fenced before old primary surrendered

**Investigation:**

```
1. Check AUTOMATED_REGISTER:
   crm_resource --resource <SAPHana_rsc> --get-parameter=AUTOMATED_REGISTER

2. Check for duplicate primary in logs:
   grep "DUPLICATE_PRIMARY" /var/log/messages

3. Verify replication state on both nodes:
   su - <sid>adm -c "hdbnsutil -sr_state"

4. Check if HANA trace shows registration errors:
   grep -i "sr_register\|replication" /usr/sap/<SID>/HDB<inst>/trace/nameserver_*.trc
```

## Pattern 2: Fencing Not Triggered During Node Failure

**Symptoms:**

- Node became unresponsive but was never fenced
- Resources stuck in `Started` state on the dead node
- No `pacemaker-fenced` entries in logs

**Root Causes:**

1. **`stonith-enabled` is `false`** — fencing entirely disabled
2. **`maintenance-mode` is `true`** — all automated actions suspended
3. **SBD device unreachable** — if ISCSI, check iSCSI target connectivity
4. **Azure Fence Agent auth failure** — MSI token expired or RBAC missing
5. **`stonith-timeout` too short** — fencing timed out before Azure completed the VM restart
6. **`have-watchdog` mismatch** — set to `true` without SBD, or `false` with SBD

**Investigation:**

```
1. Verify STONITH is enabled:
   cibadmin --query --scope crm_config | grep stonith-enabled

2. Check maintenance mode:
   crm_attribute --type crm_config --name maintenance-mode --query

3. Test fence agent manually:
   fence_azure_arm --action=status --plug=<vm_name> --resourceGroup=<rg> \
     --subscriptionId=<sub> --msi

4. For SBD, verify device health:
   sbd -d /dev/disk/by-id/<device> list
```

## Pattern 3: ANF Volume Throttling During Backup

**Symptoms:**

- HANA backup or log shipping slows dramatically
- `SWAIT` replication state persists for hours
- ANF metrics show throughput at tier ceiling

**Root Causes:**

1. **Service level mismatch** — Standard tier (16 MiB/s per TiB) insufficient for backup throughput
2. **Volume size too small** — ANF throughput scales with volume capacity
3. **Concurrent workload** — production queries compete with backup I/O

**Investigation:**

```
1. Get filesystem details (STAF FileSystemCollector):
   - NFS type: ANF vs AFS
   - Service level: Standard / Premium / Ultra
   - max_mbps and max_iops from Azure metadata

2. Check Azure Monitor:
   - ANF volume throughput (read + write) over incident window
   - Compare against tier limits

3. Verify mountpoint options:
   findmnt -t nfs,nfs4    # Check mount options (nconnect, rsize, wsize)
```

## Pattern 4: Enqueue Replication Server Failover Failure (ENSA2)

**Symptoms:**

- ASCS migrated but enqueue locks were lost
- ERS did not replicate lock table before failover
- SAP application servers report `EnqueueException`

**Root Causes:**

1. **ERS not running** — resource was in `Stopped` or `Failed` state before the ASCS failure
2. **`AUTOMATIC_RECOVER` set to `true`** — ASCS restarted locally before Pacemaker could migrate it, losing the enqueue table
3. **Monitor timeout too short** — Pacemaker declared resource dead before SAP finished graceful shutdown
4. **Colocation constraint incorrect** — ASCS and ERS placed on the same node

**Investigation:**

```
1. Check ASCS/ERS resource state before incident:
   crm_mon -1rR | grep -E "ASCS|ERS"

2. Verify AUTOMATIC_RECOVER:
   cibadmin --query --scope resources | grep AUTOMATIC_RECOVER
   Expected: false

3. Check colocation constraint:
   cibadmin --query --scope constraints | grep rsc_colocation
   Score should be -5000 (anti-colocation)

4. Verify ERS MINIMAL_PROBE:
   Expected: false (ERS needs full monitoring)
```

## Pattern 5: Network Isolation Causes Split Brain

**Symptoms:**

- Both nodes believe they are primary
- Pacemaker logs show `cannot run anywhere` or quorum loss
- Corosync ring errors visible in `corosync-cfgtool -s`

**Root Causes:**

1. **Corosync ring failure** — single ring with no redundancy
2. **NSG rule change** — Azure NSG blocking Corosync UDP ports (5405)
3. **Azure accelerated networking driver issue** — transient network stack failure
4. **`concurrent-fencing` is `false`** — only one fence operation at a time, delaying resolution
5. **`priority-fencing-delay` not set** — both nodes race to fence each other

**Investigation:**

```
1. Check corosync ring status:
   corosync-cfgtool -s
   Look for: "ring 0 active with no faults"

2. Check quorum state:
   corosync-quorumtool
   Expected: "Quorate: Yes" or explicit two_node quorum

3. Review Azure NSG rules:
   az network nsg rule list --nsg-name <nsg> -g <rg> -o table
   Port 5405/UDP must be allowed between cluster nodes

4. Check priority-fencing-delay:
   crm_attribute --type crm_config --name priority-fencing-delay --quiet
   Expected: 30s (SUSE) or 15s (RHEL)

5. Review Azure Activity Log for network events:
   az monitor activity-log list --resource-group <rg> \
     --start-time <incident_time> --offset 1h
```
