# misc

Shared utility tasks for SAP HA testing — pre/post validation, telemetry, cluster reports, and HTML report rendering.

## Tasks

| Task File | Description |
|-----------|-------------|
| test-case-setup.yml | Common test case initialization |
| pre-validations-db.yml | Pre-test validation for HANA DB |
| pre-validations-scs.yml | Pre-test validation for SCS |
| pre-validations-scaleout-hsr.yml | Pre-test validation for Scale-Out HSR |
| post-validations.yml | Post-test validation and log parsing |
| post-telemetry-data.yml | Send telemetry data to ADX/Log Analytics |
| rescue.yml | Error handling and recovery |
| cluster-report.yml | Generate cluster status report |
| render-html-report.yml | Render HTML test report |
| display-test-summary.yml | Display test execution summary |
| loadbalancer.yml | Azure Load Balancer validation |
| offline-validation.yml | Offline HA configuration validation |
| get-saphanasr-provider.yml | Detect SAPHanaSR provider |
| var-log-messages.yml | Parse /var/log/messages |
