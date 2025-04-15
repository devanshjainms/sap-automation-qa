# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Python script to get and validate the status of an SCS cluster.
"""

import xml.etree.ElementTree as ET
from typing import Dict, Any
from ansible.module_utils.basic import AnsibleModule

try:
    from ansible.module_utils.get_cluster_status import BaseClusterStatusChecker
except ImportError:
    from src.module_utils.get_cluster_status import BaseClusterStatusChecker


DOCUMENTATION = r"""
---
module: get_cluster_status_scs
short_description: Checks the status of a SAP SCS cluster
description:
    - This module checks the status of a pacemaker cluster in a SAP SCS environment
    - Identifies ASCS and ERS nodes in the cluster
    - Validates if the cluster is ready and stable
options:
    sap_sid:
        description:
            - SAP System ID (SID)
        type: str
        required: true
    ansible_os_family:
        description:
            - Operating system family (redhat, suse, etc.)
        type: str
        required: false
author:
    - Microsoft Corporation
notes:
    - This module requires root privileges to access pacemaker cluster information
    - Depends on crm_mon command being available
    - Validates the cluster status by checking node attributes for ASCS and ERS
requirements:
    - python >= 3.6
    - pacemaker cluster environment
"""

EXAMPLES = r"""
- name: Check SAP SCS cluster status
  get_cluster_status_scs:
    sap_sid: "S4D"
    ansible_os_family: "{{ ansible_os_family|lower }}"
  register: cluster_result

- name: Display SCS cluster status
  debug:
    msg: "ASCS node: {{ cluster_result.ascs_node }}, ERS node: {{ cluster_result.ers_node }}"

- name: Fail if SCS cluster is not stable
  fail:
    msg: "SAP SCS cluster is not properly configured"
  when: cluster_result.ascs_node == '' or cluster_result.ers_node == ''
"""

RETURN = r"""
status:
    description: Status of the cluster check
    returned: always
    type: str
    sample: "SUCCESS"
message:
    description: Descriptive message about the cluster status
    returned: always
    type: str
    sample: "Cluster is stable and ready"
ascs_node:
    description: Name of the node running the ASCS instance
    returned: always
    type: str
    sample: "sapapp1"
ers_node:
    description: Name of the node running the ERS instance
    returned: always
    type: str
    sample: "sapapp2"
"""


class SCSClusterStatusChecker(BaseClusterStatusChecker):
    """
    Class to check the status of a pacemaker cluster in an SAP SCS environment.
    """

    def __init__(
        self,
        sap_sid: str,
        ansible_os_family: str = "",
        ascs_instance_number: str = "00",
        ers_instance_number: str = "01",
    ):
        super().__init__(ansible_os_family)
        self.sap_sid = sap_sid
        self.ascs_instance_number = ascs_instance_number
        self.ers_instance_number = ers_instance_number
        self.result.update(
            {
                "ascs_node": "",
                "ers_node": "",
            }
        )

    def _process_node_attributes(self, cluster_status_xml: ET.Element) -> Dict[str, Any]:
        """
        Processes node attributes and identifies ASCS and ERS nodes.

        :param cluster_status_xml: XML element containing node attributes.
        :type cluster_status_xml: ET.Element
        :return: Dictionary with ASCS and ERS node information.
        :rtype: Dict[str, Any]
        """
        resources = cluster_status_xml.find("resources")
        node_attributes = cluster_status_xml.find("node_attributes")
        ascs_resource_id = f"rsc_sap_{self.sap_sid.upper()}_ASCS{self.ascs_instance_number}"
        ers_resource_id = f"rsc_sap_{self.sap_sid.upper()}_ERS{self.ers_instance_number}"

        all_nodes = [node.attrib.get("name") for node in node_attributes]
        for node in node_attributes:
            node_name = node.attrib["name"]
            for attribute in node:
                if attribute.attrib["name"] == f"runs_ers_{self.sap_sid.upper()}":
                    if attribute.attrib["value"] == "1":
                        self.result["ers_node"] = node_name
                    else:
                        self.result["ascs_node"] = node_name

        if resources is not None:
            ascs_resource = resources.find(f"./resource[@id='{ascs_resource_id}']")
            ers_resource = resources.find(f"./resource[@id='{ers_resource_id}']")

            if ascs_resource is not None:
                is_failed = ascs_resource.attrib.get("is_failed", "false").lower() == "true"
                if not is_failed:
                    node_element = ascs_resource.find("node")
                    if node_element is not None:
                        self.result["ascs_node"] = node_element.attrib.get(
                            "name", self.result["ascs_node"]
                        )
                else:
                    self.result["ascs_node"] = ""

            if ers_resource is not None:
                is_failed = ers_resource.attrib.get("is_failed", "false").lower() == "true"
                if not is_failed:
                    node_element = ers_resource.find("node")
                    if node_element is not None:
                        self.result["ers_node"] = node_element.attrib.get(
                            "name", self.result["ers_node"]
                        )
                else:
                    self.result["ers_node"] = ""

        return self.result

    def _is_cluster_ready(self) -> bool:
        """
        Check if the cluster is ready by verifying at least one of ASCS or ERS nodes.

        :return: True if either ASCS or ERS node is available, False otherwise.
        :rtype: bool
        """
        return self.result["ascs_node"] != "" or self.result["ers_node"] != ""

    def _is_cluster_stable(self) -> bool:
        """
        Check if the cluster is stable by verifying both ASCS and ERS nodes.

        :return: True if the cluster is stable, False otherwise.
        :rtype: bool
        """
        return self.result["ascs_node"] != "" and self.result["ers_node"] != ""


def run_module() -> None:
    """
    Entry point of the module.
    """
    module_args = dict(
        sap_sid=dict(type="str", required=True),
        ascs_instance_number=dict(type="str", required=False),
        ers_instance_number=dict(type="str", required=False),
        ansible_os_family=dict(type="str", required=False),
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    checker = SCSClusterStatusChecker(
        sap_sid=module.params["sap_sid"],
        ansible_os_family=module.params["ansible_os_family"],
    )
    checker.run()

    module.exit_json(**checker.get_result())


def main() -> None:
    """
    Entry point of the script.
    """
    run_module()


if __name__ == "__main__":
    main()
