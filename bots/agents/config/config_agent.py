# bots/agents/config/config_agent.py
import os
import json
import logging
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from autogen_agentchat import ConversableAgent
from bots.common.state import StateStore
from openai import AzureOpenAI


class ConfigAgent(ConversableAgent):
    """
    ConversableAgent that ensures SAP system configuration: either loads existing hosts.yaml
    and sap-parameters.yaml or creates them via Jinja templates, collecting any missing
    variables interactively (via natural language) before signaling readiness.
    """

    def __init__(self, state_store: StateStore, client: AzureOpenAI):
        super().__init__(name="ConfigAgent")
        self.state = state_store
        self.logger = logging.getLogger(self.__class__.__name__)
        self.workspace_root = os.getenv("STAF_WORKSPACE_ROOT", os.getcwd())
        self.system_base = os.path.join(self.workspace_root, "WORKSPACES", "SYSTEM")
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["j2"])
        )
        self.client = client

    def on_message(self, message: str) -> str:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            self.logger.error("ConfigAgent received invalid JSON: %s", message)
            return json.dumps({"error": "invalid_input"})

        session_id = data.get("session_id")
        entities = data.setdefault("entities", {})
        awaiting = data.get("awaiting")
        user_response = data.get("user_response") or data.get("prompt_response") or message

        if awaiting == "system" or "system" not in entities:
            entities["system"] = user_response.strip()
            data["entities"] = entities

        system = entities.get("system")
        system_path = os.path.join(self.system_base, system)
        hosts_file = os.path.join(system_path, "hosts.yaml")
        params_file = os.path.join(system_path, "sap-parameters.yaml")

        if not os.path.isdir(system_path):
            os.makedirs(system_path, exist_ok=True)

        if not os.path.isfile(hosts_file) or awaiting in ("jinja_vars", "create_confirm"):
            if awaiting == "create_confirm":
                if user_response.lower().startswith("y"):
                    data["template_stage"] = "hosts"
                    data["awaiting"] = "jinja_vars"
                else:
                    return json.dumps({"error": "template_creation_declined"})
            if data.get("awaiting") == "jinja_vars":
                stage = data.get("template_stage", "hosts")
                template = self.jinja_env.get_template(f"{stage}.j2")
                var_names = list(template.module.__dict__.keys())
                prompt = (
                    f"Extract values for variables {var_names} from this user input: '{user_response}'. "
                    "Respond in JSON mapping variable names to their values."
                )
                resp = self.client.chat.completions.create(
                    deployment_id=self.deployment,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful assistant that extracts template variable values.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                )
                try:
                    extracted = json.loads(resp.choices[0].message.content)
                except json.JSONDecodeError:
                    return json.dumps(
                        {"prompt": "Sorry, I couldn't extract the values. Please rephrase.", **data}
                    )
                rendered = template.render(**extracted)
                filepath = hosts_file if stage == "hosts" else params_file
                with open(filepath, "w") as f:
                    f.write(rendered)
                if stage == "hosts":
                    data["template_stage"] = "sap-parameters"
                    data["awaiting"] = "jinja_vars"
                    return json.dumps(
                        {
                            "prompt": "Hosts.yaml created. Now provide values for sap-parameters template.",
                            **data,
                        }
                    )
                else:
                    data["awaiting"] = None

        if os.path.isfile(hosts_file) and os.path.isfile(params_file):
            try:
                with open(hosts_file) as hf:
                    hosts = yaml.safe_load(hf)
                with open(params_file) as pf:
                    params = yaml.safe_load(pf)
            except Exception as e:
                self.logger.error("YAML load error: %s", e)
                return json.dumps({"error": "yaml_load_failed"})
            self.state.save_entities(session_id, {"hosts": hosts, "parameters": params})
            data["config_ready"] = True
            data["hosts"] = hosts
            data["parameters"] = params
            # Signal final
            return json.dumps(data)

        if "system" not in entities:
            return json.dumps({"prompt": "Which SAP system identifier?", "awaiting": "system"})
        return json.dumps(
            {
                "prompt": f"Missing configuration for {system}. Create from templates? (yes/no)",
                "awaiting": "create_confirm",
                **data,
            }
        )
