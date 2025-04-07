# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Ansible Python module to check the configuration of the workload system running on Azure
"""

from ansible.module_utils.basic import AnsibleModule

try:
    from ansible.module_utils.configuration_check import ConfigurationCheck

    HAS_CONFIG_CHECK = True
except ImportError:
    from src.module_utils.configuration_check import ConfigurationCheck

    HAS_CONFIG_CHECK = False

DOCUMENTATION = r"""
---
module: configuration_check
short_description: Validates system configurations
description:
  - Executes configuration checks defined in YAML files
  - Validates actual system state against defined requirements
  - Supports filtering by tags and categories
options:
  check_file:
    description: Path to YAML file with check definitions
    type: path
    required: true
  context:
    description: Dictionary with context variables
    type: dict
    required: true
  filter_tags:
    description: Tags to filter checks by
    type: list
    elements: str
    required: false
  filter_categories:
    description: Categories to filter checks by
    type: list
    elements: str
    required: false
  generate_report:
    description: Generate HTML report of results
    type: bool
    default: false
  workspace_directory:
    description: Directory for report output
    type: path
    default: "/var/log/sap-automation-qa"
  hostname:
    description: Override hostname in context
    type: str
    required: false
"""

EXAMPLES = r"""
- configuration_check:
    check_file: /path/to/os_checks.yaml
    context:
      hostname: "{{ inventory_hostname }}"
      os_distribution: "{{ ansible_distribution }}"

- configuration_check:
    check_file: /path/to/hana_checks.yaml
    context:
      hostname: "{{ inventory_hostname }}"
      sap_components: ["HANA"]
    filter_tags: ["storage"]
    generate_report: true
"""

RETURN = r"""
summary:
  description: Results summary
  type: dict
  returned: always
results:
  description: Detailed check results
  type: list
  returned: always
success:
  description: True if all checks passed
  type: bool
  returned: always
report_path:
  description: Path to generated report
  type: str
  returned: when generate_report is true
"""


class ConfigurationCheckModule:
    def __init__(self, module):
        self.module = module
        self.module_params = module.params
        self.config_check = ConfigurationCheck()

    def execute_checks(self):
        """Load and execute checks"""
        check_file_content = self.module_params["check_file_content"]
        filter_tags = self.module_params["filter_tags"]
        filter_categories = self.module_params["filter_categories"]

        self.config_check.load_checks(check_file_content)
        return self.config_check.execute_checks(filter_tags, filter_categories)

    def format_results_for_html_report(self):
        """Format results for use with render_html_report"""
        check_results = []
        for result in self.config_check.result:
            check_results.append(
                {
                    "id": result.check.id,
                    "name": result.check.name,
                    "description": result.check.description,
                    "command": result.check.collector_args.get("command", "N/A"),
                    "output": str(result.collected_data),
                    "expected_output": (
                        str(result.expected_value) if result.expected_value else "N/A"
                    ),
                    "status": result.status.value,
                    "hostname": result.hostname,
                    "type": result.check.category,
                    "report": "check",
                    "references": {
                        "remediation": result.check.remediation,
                        **result.check.references,
                    },
                }
            )
        return check_results

    def run(self):
        """Run the module"""
        try:
            context = self.module_params["context"]
            custom_hostname = self.module_params["hostname"]

            if custom_hostname:
                context["hostname"] = custom_hostname

            self.config_check.set_context(context)
            self.config_check.load_checks(self.module_params["check_file_content"])
            self.config_check.execute_checks(
                self.module_params["filter_tags"], self.module_params["filter_categories"]
            )
            self.module.exit_json(**self.config_check.result)
        except Exception as e:
            self.module.fail_json(msg=f"Error: {str(e)}")


def main():
    module_args = dict(
        check_file_content=dict(type="str", required=True),
        context=dict(type="dict", required=True),
        filter_tags=dict(type="list", elements="str", required=False, default=None),
        filter_categories=dict(type="list", elements="str", required=False, default=None),
        workspace_directory=dict(type="str", required=True),
        hostname=dict(type="str", required=False, default=None),
        test_group_invocation_id=dict(type="str", required=True),
        test_group_name=dict(type="str", required=True),
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    if not HAS_CONFIG_CHECK:
        module.fail_json(msg="Required modules not found")

    runner = ConfigurationCheckModule(module)
    runner.run()


if __name__ == "__main__":
    main()
