# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Help agent that provides information about SAP QA capabilities using documentation context.
"""

from pathlib import Path
from typing import Optional

from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.agents.base import Agent
from src.agents.llm_client import call_llm
from src.agents.prompts import ECHO_AGENT_SYSTEM_PROMPT
from src.agents.logging_config import get_logger

logger = get_logger(__name__)


class EchoAgent(Agent):
    """
    Agent that provides helpful information about SAP QA assistant capabilities using documentation.
    """

    def __init__(self) -> None:
        """Initialize EchoAgent with helpful description."""
        super().__init__(
            name="echo",
            description="Provides general help and information about the SAP QA assistant using "
            + "documentation context. Use for greetings, general questions, or when user intent is unclear.",
        )
        self.docs_dir = Path(__file__).parent.parent.parent.parent / "docs"
        logger.info(f"EchoAgent initialized with docs directory: {self.docs_dir}")

    def _load_documentation_context(self) -> str:
        """Load all markdown documentation files recursively from the docs directory.

        Includes main docs and subdirectories like high_availability/.
        Also lists available images for reference.

        :returns: Concatenated documentation content
        :rtype: str
        """
        docs_content = []

        if not self.docs_dir.exists():
            logger.warning(f"Documentation directory not found: {self.docs_dir}")
            return ""
        md_files = sorted(self.docs_dir.rglob("*.md"))

        for md_file in md_files:
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    relative_path = md_file.relative_to(self.docs_dir)
                    docs_content.append(f"# Documentation: {relative_path}\n\n{content}")
                logger.info(f"Loaded documentation file: {relative_path}")
            except Exception as e:
                logger.error(f"Error reading {md_file}: {e}")
                continue
        images_dir = self.docs_dir / "images"
        if images_dir.exists():
            image_files = sorted(images_dir.glob("*"))
            if image_files:
                image_list = "\n".join([f"- {img.name}" for img in image_files])
                docs_content.append(
                    f"""# Available Documentation Images

The following images are available in docs/images/ to illustrate the framework:
{image_list}

These images provide visual references for the SAP QA automation framework architecture and execution flows."""
                )

        full_context = "\n\n---\n\n".join(docs_content)
        logger.info(
            f"Loaded {len(md_files)} documentation files, total length: {len(full_context)} chars"
        )
        return full_context

    async def run(
        self,
        messages: list[ChatMessage],
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Provide helpful information using LLM with documentation context.

        :param messages: Full conversation history
        :type messages: list[ChatMessage]
        :param context: Optional metadata (unused)
        :type context: Optional[dict]
        :returns: ChatResponse with helpful information
        :rtype: ChatResponse
        :raises Exception: Re-raises any exception from LLM call
        """
        logger.info("EchoAgent processing request with documentation context")

        docs_context = self._load_documentation_context()
        system_prompt = ECHO_AGENT_SYSTEM_PROMPT.format(docs_context=docs_context)
        llm_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            llm_messages.append({"role": msg.role, "content": msg.content})
        logger.info("Calling LLM with documentation context")
        response = await call_llm(llm_messages)

        response_content = response.choices[0].message.content
        logger.info(f"LLM response received, length: {len(response_content)} chars")

        return ChatResponse(messages=[ChatMessage(role="assistant", content=response_content)])
