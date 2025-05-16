# bots/agents/config/config_agent.py
import os
import json
import logging
import yaml
from openai import AzureOpenAI
from autogen_agentchat.messages import ChatMessage, TextMessage
from autogen_agentchat.agents import BaseChatAgent
from jinja2 import Environment, FileSystemLoader, select_autoescape
from bots.common.state import StateStore


class ConfigAgent(BaseChatAgent):
    """
    ChatAgent that ensures SAP system configuration: either loads existing hosts.yaml
    and sap-parameters.yaml or creates them via Jinja templates, collecting any missing
    variables interactively (via natural language) before signaling readiness.
    """

    def __init__(self, state_store: StateStore, client: AzureOpenAI):
        super().__init__(name="ConfigAgent", description="Ensures SAP system configuration.")
        self.state = state_store
        self.logger = logging.getLogger(self.__class__.__name__)
        self.workspace_root = os.getenv("STAF_WORKSPACE_ROOT", os.getcwd())
        self.system_base = os.path.join(self.workspace_root, "WORKSPACES", "SYSTEM")
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["j2"])
        )
        self.client = client
        self._context: dict = {}
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    def on_reset(self) -> None:
        """
        Reset internal state for new conversation.
        """
        self._context.clear()

    @property
    def produced_message_types(self) -> list:
        """
        Specify that this agent produces text messages.
        """
        return [TextMessage]

    def on_messages(self, message: str, cancellation_token=None) -> str:
        try:
            ctx = json.loads(message)
        except json.JSONDecodeError:
            self.logger.error("ConfigAgent received invalid JSON: %s", message)
            return json.dumps({"error": "invalid_input"})

        session_id = ctx.get("session_id")
        entities = ctx.setdefault("entities", {})
        stage = ctx.get("stage", "init")
        user_text = ctx.get("text", message)

        if "system" not in entities or stage == "ask_system":
            ctx["stage"] = "ask_system"
            return json.dumps({"prompt": "Which SAP system? e.g. 'DEV-WEEU-SAP01-X00'", **ctx})

        system = entities.get("system")
        system_path = os.path.join(self.system_base, system)
        hosts_yaml = os.path.join(system_path, "hosts.yaml")
        params_yaml = os.path.join(system_path, "sap-parameters.yaml")
        if not os.path.isdir(system_path):
            os.makedirs(system_path, exist_ok=True)

        if not os.path.isfile(hosts_yaml) or not os.path.isfile(params_yaml):
            # Confirm creation
            if stage == "init":
                ctx["stage"] = "confirm"
                return json.dumps(
                    {
                        "prompt": f"Config for '{system}' missing. Create from templates? (yes/no)",
                        **ctx,
                    }
                )
            if stage == "confirm":
                if not user_text.lower().startswith("y"):
                    return json.dumps({"error": "creation_declined"})
                ctx["stage"] = "hosts"
            # Process hosts template
            if stage == "hosts":
                tpl = self.jinja_env.get_template("hosts.j2")
                vars_needed = list(tpl.module.__dict__.keys())
                ctx["stage"] = "collect_hosts_vars"
                return json.dumps(
                    {
                        "prompt": f"Provide values for hosts variables {vars_needed} in natural language.",
                        **ctx,
                    }
                )
            if stage == "collect_hosts_vars":
                tpl = self.jinja_env.get_template("hosts.j2")
                vars_needed = list(tpl.module.__dict__.keys())
                prompt = f"Extract values for {vars_needed} from: '{user_text}' as JSON."
                resp = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=[
                        {"role": "system", "content": "Extract template vars."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                )
                try:
                    var_map = json.loads(resp.choices[0].message.content)
                except json.JSONDecodeError:
                    return json.dumps({"prompt": "Could not parse values. Please rephrase.", **ctx})
                content = tpl.render(**var_map)
                with open(hosts_yaml, "w") as f:
                    f.write(content)
                ctx["stage"] = "params"
                return json.dumps(
                    {"prompt": "hosts.yaml created. Now provide sap-parameters values.", **ctx}
                )
            # Process parameters template
            if stage == "params":
                tpl = self.jinja_env.get_template("sap-parameters.j2")
                vars_needed = list(tpl.module.__dict__.keys())
                ctx["stage"] = "collect_params_vars"
                return json.dumps(
                    {"prompt": f"Provide values for parameters variables {vars_needed}.", **ctx}
                )
            if stage == "collect_params_vars":
                tpl = self.jinja_env.get_template("sap-parameters.j2")
                vars_needed = list(tpl.module.__dict__.keys())
                prompt = f"Extract values for {vars_needed} from: '{user_text}' as JSON."
                resp = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=[
                        {"role": "system", "content": "Extract template vars."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                )
                try:
                    var_map = json.loads(resp.choices[0].message.content)
                except json.JSONDecodeError:
                    return json.dumps({"prompt": "Could not parse values. Please rephrase.", **ctx})
                content = tpl.render(**var_map)
                with open(params_yaml, "w") as f:
                    f.write(content)
                ctx["stage"] = "done"

        # Finally load both YAMLs
        try:
            with open(hosts_yaml) as hf:
                hosts = yaml.safe_load(hf)
            with open(params_yaml) as pf:
                params = yaml.safe_load(pf)
        except Exception as e:
            self.logger.error("YAML load error: %s", e)
            return json.dumps({"error": "yaml_error"})

        # Persist and signal completion
        self.state.save_entities(session_id, {"hosts": hosts, "parameters": params})
        ctx["config_ready"] = True
        ctx["hosts"] = hosts
        ctx["parameters"] = params
        # Indicate done with terminal marker
        payload = json.dumps(ctx) + "DONE"
        return ChatMessage(role="agent", content=payload)

    def on_messages_stream(self, messages, cancellation_token):
        return super().on_messages_stream(messages, cancellation_token)
