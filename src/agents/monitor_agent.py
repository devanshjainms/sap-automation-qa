# monitor_agent.py

import subprocess
from src.agents.base_agent import BaseAgent


class MonitorAgentFactory:
    @staticmethod
    def create():
        system_message = (
            "You are the Monitor agent. Your job is to:\n"
            "- Read system logs for the last 5 minutes (journalctl, SAP logs)\n"
            "- Parse errors and warnings\n"
            "- Summarize failures or warnings\n"
            "- Check SAP cluster and application health using system commands\n\n"
            "When asked to summarize logs, you may read from journalctl or /var/log/sap or custom logs.\n"
            "Output should be in bullet points or brief report format."
        )

        return BaseAgent(
            name="MonitorAgent", role="monitor", system_message=system_message, is_conversable=True
        ).get_agent()

    @staticmethod
    def get_recent_logs():
        try:
            result = subprocess.run(
                ["journalctl", "--since", "5 minutes ago"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            return f"Failed to read logs: {e.stderr}"

    @staticmethod
    def get_cluster_status():
        try:
            result = subprocess.run(["crm", "status"], capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            return f"Cluster status command failed: {e.stderr}"

    @staticmethod
    def get_sap_health():
        try:
            result = subprocess.run(
                ["/usr/sap/hostctrl/exe/sapcontrol", "-nr", "00", "-function", "GetProcessList"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            return f"SAP health check failed: {e.stderr}"
