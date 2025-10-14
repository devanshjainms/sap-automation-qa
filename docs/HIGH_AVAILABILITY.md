# SAP High Availability Testing

A key component of the SAP Testing Automation framework is the SAP High Availability (HA) Testing. This helps in ensuring that an SAP system deployment complies to SAP on Azure best practices and guidelines.

The SAP High Availability Testing scenario executes a series of tests designed to simulate real-world failures, ensuring the system's recovery capabilities. Leveraging Ansible, the framework orchestrates various test cases, including node crashes, network disruptions, and storage failures, to validate the effectiveness of recovery mechanisms. Additionally, the framework captures comprehensive logs and generates detailed reports on the test outcomes.

## Supported Configurations

### Linux distribution

Currently SAP Testing Automation Framework is supported for below Linux distros and version.

| Distribution | Supported Release |  
|--------------|-------------------|
| SUSE Linux Enterpise Server (SLES) | 15 SP4, 15 SP5, 15 SP6 |
| Red Hat Enterprise Linux (RHEL) | 8.8, 8.10, 9.2, 9.4 |

### High Availability configuration pattern

| Component | Type | Cluster Type | Storage |
|-----------|------|--------------|---------|
| SAP Central Services | ENSA1 or ENSA2 | Azure Fencing Agent | Azure Files or ANF |
| SAP Central Services | ENSA1 or ENSA2 | ISCSI (SBD device) | Azure Files or ANF |
| SAP Central Services | ENSA1 or ENSA2 | Azure Shared Disks (SBD device) | Azure Files or ANF |
| SAP HANA | Scale-up | Azure Fencing Agent | Azure Managed Disk or ANF |
| SAP HANA | Scale-up | ISCSI (SBD device) | Azure Managed Disk or ANF |
| SAP HANA | Scale-up | Azure Shared Disks (SBD device) | Azure Managed Disk or ANF |

For SAP Central Services on SLES, both the simple mount approach and the classic method are supported.


### Enabling Cluster Services on Boot

Before executing the tests, ensure that the cluster services are configured to start automatically during system boot. Run the following command on one of the cluster nodes to enable this setting. The `--all` option ensures that the cluster services are enabled on all nodes within the cluster.

```bash
crm cluster enable --all  # for SUSE virtual machines
pcs cluster enable --all  # for RedHat virtual machine
```

### 1. Setup Configuration

Follow the steps (1.1 - 1.5) in [Setup Guide for SAP Testing Automation Framework](./SETUP.MD) to set up the framework on a management server.

### 2. System Configuration

Update the `TEST_TYPE` parameter in [`vars.yaml`](./../vars.yaml) file to `SAPFunctionalTests` to enable the High Availability test scenarios.

Follow the steps (2.1 - 2.2) in [Setup Guide for SAP Testing Automation Framework](./SETUP.MD#2-system-configuration) to configure your system details.


### 3. Test Execution

To execute the script, run following command:

```bash
# Run all the tests with default parameters
./scripts/sap_automation_qa.sh

# Run specific test cases from HA_DB_HANA group
./scripts/sap_automation_qa.sh --test_groups=HA_DB_HANA --test_cases=[ha-config,primary-node-crash]

# Run specific test cases from HA_SCS group
./scripts/sap_automation_qa.sh --test_groups=HA_SCS --test_cases=[ha-config]

# Run with verbose output
./scripts/sap_automation_qa.sh --test_groups=HA_DB_HANA --test_cases=[primary-node-crash] -vvv
```

### 4. Viewing Test Results

After the test execution completes, a detailed HTML report is generated that summarizes the PASS/FAIL status of each test case and includes detailed execution logs for every step of the automation run.

**To locate and view your test report:**

1. **Navigate to your SAP system’s workspace directory:**

   Replace `<SYSTEM_CONFIG_NAME>` with the name of your SAP system configuration (for example, `DEV-WEEU-SAP01-X00`):

   ```bash
   cd WORKSPACES/SYSTEM/<SYSTEM_CONFIG_NAME>/quality_assurance/
   ```
2. **Find your report file:**

   The report file is named using the following format:

   ```
   HA_{SAP_TIER}_{DATABASE_TYPE}_{OS_DISTRO_NAME}_{INVOCATION_ID}.html
   ```

   - `SAP_TIER`: The SAP tier tested (e.g., DB, SCS)
   - `DATABASE_TYPE`: The database type (e.g., HANA)
   - `OS_DISTRO_NAME`: The operating system distribution (e.g., SLES15SP4)
   - `INVOCATION_ID`: A unique identifier (Group invocation ID) for the test run which is logged at the end of test execution. Find example screenshot below:

      ![Test Execution Completion Screenshot](./images/execution_screenshot.png)

3. **View the report**

   You can open the HTML report in any web browser to review the results and logs.
