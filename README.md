# SAP Testing Automation Framework

![SAP Testing Automation Framework](./docs/images/sap-automation-qa.svg)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Azure](https://img.shields.io/badge/Microsoft-SAP%20on%20Azure-0078D4?logo=microsoft)](https://docs.microsoft.com/azure/sap)
[![Python Coverage](https://img.shields.io/badge/Code%20Coverage-85%25-success?logo=python&logoColor=white)](https://github.com/Azure/sap-automation-qa/actions/workflows/github-actions-code-coverage.yml)
[![Ansible Lint](https://github.com/Azure/sap-automation-qa/actions/workflows/github-actions-ansible-lint.yml/badge.svg)](https://github.com/Azure/sap-automation-qa/actions/workflows/github-actions-ansible-lint.yml)
[![OpenSSF Scorecard](https://img.shields.io/ossf-scorecard/github.com/Azure/sap-automation-qa)](https://scorecard.dev/viewer/?uri=github.com/Azure/sap-automation-qa)
[![GitHub Issues](https://img.shields.io/github/issues/Azure/sap-automation-qa)](https://github.com/Azure/sap-automation-qa/issues)

## 🔍 Overview

The SAP Testing Automation Framework is an open-source orchestration tool designed to validate SAP deployments on Microsoft Azure. It enables you to assess system configurations against SAP on Azure best practices and guidelines, and facilitates automation for various testing scenarios.

> **NOTE**: This repository is currently in public preview and is intended for testing and feedback purposes. As this is an early release, it is not yet production-ready, and breaking changes can be introduced at any time.

![SAP Testing Automation Framework](./docs/images/sap-testing-automation-framework.png)

## 📊 Key Features

- **High Availability Testing** - Thorough validation of the SAP HANA scale-up and SAP Central Services failover mechanism in a two node pacemaker cluster, ensuring the system operates correctly across various test cases.
  - **Configuration Validation** - Ensures that SAP HANA scale-up and SAP Central Services configurations comply with SAP on Azure best practices and guidelines.
  - **Functional Testing** - Executes test scenarios on the high availability setup to identify potential issues, whether during a new system deployment or before implementing cluster changes in a production environment.
- **Configuration Checks** - Validates OS parameters, database settings, Azure resources, and storage configurations against SAP and Azure best practices for supported databases. Performs comprehensive validation including kernel parameters, filesystem mounts, VM sizing, and network setup to ensure compliance with recommended guidelines.
- **Detailed Reporting** - Generates comprehensive reports, highlighting configuration mismatch or deviations from recommended best practices. Includes failover test outcomes, any failures encountered, and logs with insights to aid in troubleshooting identified issues.

## 🏆 Purpose

Testing is crucial for keeping SAP systems running smoothly, especially for critical business operations. This framework helps by addressing key challenges:

- **Preventing Risks** - Identifies configuration issues and validates system behavior before problems affect production operations. It simulates system failures like node crashes, network issues, and storage failures to check if recovery mechanisms work properly, helping to catch potential issues early.
- **Meeting Compliance Requirements** - Provides detailed reports and logs that help with audits and ensure compliance with internal and regulatory standards.
- **Ensuring Quality** - The framework runs automated tests to verify whether the failover behavior of SAP components functions as expected on Azure across various test scenarios. It also ensures that the cluster and resource configurations are set up correctly, helping to maintain system reliability.
- **Automating Testing** - Automates validation processes from configuration checks to reporting, saving time and ensuring consistent results.

## 🚦 Get Started

There are two primary ways to get started with the SAP Testing Automated Framework. Choose the path that best fits your current environment and objectives:

### Option 1: Integration with SAP Deployment Automation Framework (SDAF)

If you already have [SDAF](https://github.com/Azure/sap-automation) environment set up, integrating the SAP Testing Automation Framework is a natural extension that allows you to leverage existing deployment pipelines and configurations.

### Option 2: Getting Started with High Availability Testing (Standalone)

For users focused solely on validating SAP functionality and configurations, the standalone approach offers a streamlined process to test critical SAP components without the complexity of full deployment integration.
 - For High Availability testing details, see the [High Availability documentation](./docs/HIGH_AVAILABILITY.md).
 - For Configuration Checks and Testing details, see the [Configuration Checks documentation](./docs/CONFIGURATION_CHECKS.md).

## 🏗️ Architecture and Components

To learn how the framework works, refer to the [architecture and components](./docs/ARCHITECTURE.md) documentation.

## 🆘Support

For support and questions, please:

1. Check [existing issues](https://github.com/Azure/sap-automation-qa/issues/)
2. Create new issue if needed and provide detailed information about the problem

## 📚 Additional Resources

- [Azure SAP Documentation](https://docs.microsoft.com/azure/sap)
- [Configuration Checks Guide](./docs/CONFIGURATION_CHECKS.md)
- [High Availability Testing Guide](./docs/HIGH_AVAILABILITY.md)

## 🤝 Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us the rights to use your contribution. For details, visit <https://cla.opensource.microsoft.com>.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## ⚖️ Legal

### License

> Copyright (c) Microsoft Corporation. Licensed under the MIT License.

### Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos are subject to those third-party's policies.
