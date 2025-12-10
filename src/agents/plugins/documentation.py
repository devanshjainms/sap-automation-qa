"""
Documentation Plugin for Semantic Kernel.

Provides kernel functions to access and search framework documentation.
Used by EchoAgentSK to answer questions about the SAP Testing Automation Framework.
"""

import logging
from pathlib import Path
from typing import Annotated

from semantic_kernel.functions import kernel_function

logger = logging.getLogger(__name__)


class DocumentationPlugin:
    """Plugin providing documentation access functions for the SAP Testing Automation Framework."""

    def __init__(self, docs_dir: str = "docs", src_dir: str = "src"):
        """
        Initialize the documentation plugin.

        :param docs_dir: Path to the documentation directory (relative to project root).
        :type docs_dir: str
        :param src_dir: Path to the source directory (relative to project root).
        :type src_dir: str
        """
        self.docs_dir = Path(docs_dir)
        self.src_dir = Path(src_dir)

        project_root = Path(__file__).parent.parent.parent.parent

        if not self.docs_dir.is_absolute():
            self.docs_dir = project_root / docs_dir

        if not self.src_dir.is_absolute():
            self.src_dir = project_root / src_dir

        logger.info(
            f"DocumentationPlugin initialized with docs_dir: {self.docs_dir}, src_dir: {self.src_dir}"
        )

    @kernel_function(
        name="get_all_documentation",
        description="Retrieves ALL documentation files from the framework. Use this when you need "
        + "comprehensive context about the entire framework, or when the user's question is broad "
        + "and doesn't specify a particular topic.",
    )
    def get_all_documentation(self) -> Annotated[str, "All documentation content concatenated"]:
        """
        Load all documentation files and return their contents.

        :return: String containing all documentation with file markers.
        :rtype: str
        """
        logger.info("Loading all documentation files")

        if not self.docs_dir.exists():
            error_msg = f"Documentation directory not found: {self.docs_dir}"
            logger.error(error_msg)
            return error_msg

        all_docs = []
        md_files = sorted(self.docs_dir.rglob("*.md"))

        if not md_files:
            warning_msg = f"No markdown files found in {self.docs_dir}"
            logger.warning(warning_msg)
            return warning_msg

        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
                relative_path = md_file.relative_to(self.docs_dir.parent)
                all_docs.append(f"--- {relative_path} ---\n{content}\n")
            except Exception as e:
                logger.error(f"Error reading {md_file}: {e}")
                continue

        result = "\n".join(all_docs)
        logger.info(f"Loaded {len(md_files)} documentation files ({len(result)} chars)")
        return result

    @kernel_function(
        name="search_documentation",
        description="Searches for specific keywords or topics in the documentation. Use this when "
        + "the user asks about a specific topic, feature, component, or concept "
        + "(e.g., 'high availability', 'Pacemaker', 'configuration checks', 'SDAF integration').",
    )
    def search_documentation(
        self,
        query: Annotated[
            str, "The search term or topic to find in documentation (e.g., 'HA testing', 'cluster')"
        ],
    ) -> Annotated[str, "Matching documentation excerpts with context"]:
        """
        Search documentation for a specific query and return relevant excerpts.

        :param query: The search term to find in documentation.
        :type query: str
        :return: Relevant documentation excerpts containing the query.
        :rtype: str
        """
        logger.info(f"Searching documentation for: {query}")

        if not self.docs_dir.exists():
            error_msg = f"Documentation directory not found: {self.docs_dir}"
            logger.error(error_msg)
            return error_msg

        results = []
        query_lower = query.lower()

        md_files = sorted(self.docs_dir.rglob("*.md"))
        if md_files:
            for md_file in md_files:
                try:
                    content = md_file.read_text(encoding="utf-8")
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if query_lower in line.lower():
                            start_idx = max(0, i - 2)
                            end_idx = min(len(lines), i + 3)
                            context_lines = lines[start_idx:end_idx]

                            relative_path = md_file.relative_to(self.docs_dir.parent)
                            excerpt = "\n".join(context_lines)
                            results.append(f"--- {relative_path} (line {i+1}) ---\n{excerpt}\n")
                            if len(results) > 20:
                                break

                except Exception as e:
                    logger.error(f"Error searching {md_file}: {e}")
                    continue

        if not results:
            return f"No documentation found matching '{query}'."

        return "\n".join(results[:15])

    @kernel_function(
        name="search_codebase",
        description="Searches the source code and configuration files for keywords. "
        + "Useful for finding default values, constants, error messages, or implementation details "
        + "that might not be in the high-level documentation.",
    )
    def search_codebase(
        self,
        query: Annotated[str, "The keyword or phrase to search for"],
    ) -> Annotated[str, "Matching code snippets"]:
        """
        Search the codebase for a specific query.

        :param query: The search term to find in the codebase.
        :type query: str
        :return: Relevant code snippets containing the query.
        :rtype: str
        """
        logger.info(f"Searching codebase for: {query}")

        if not self.src_dir.exists():
            return f"Source directory not found: {self.src_dir}"

        results = []
        query_lower = query.lower()

        extensions = ["*.py", "*.yml", "*.yaml", "*.sh", "*.j2"]

        for ext in extensions:
            files = sorted(self.src_dir.rglob(ext))
            for file_path in files:
                if ".venv" in str(file_path) or "__pycache__" in str(file_path):
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8")
                    if query_lower in content.lower():
                        lines = content.splitlines()
                        for i, line in enumerate(lines):
                            if query_lower in line.lower():
                                start = max(0, i - 3)
                                end = min(len(lines), i + 4)
                                context = "\n".join(lines[start:end])
                                relative_path = file_path.relative_to(self.src_dir.parent)
                                results.append(f"--- {relative_path} (line {i+1}) ---\n{context}\n")

                                if len(results) > 30:
                                    break
                except Exception:
                    continue

            if len(results) > 30:
                break

        if not results:
            return f"No code matches found for '{query}'."

        return "\n".join(results[:20])

    @kernel_function(
        name="list_documentation_files",
        description="Lists all available documentation files in the framework. Use this when the "
        + "user wants to know what documentation is available or asks 'what docs exist?'",
    )
    def list_documentation_files(self) -> Annotated[str, "List of available documentation files"]:
        """
        List all available documentation files.

        :return: Formatted list of documentation files with paths.
        :rtype: str
        """
        logger.info("Listing all documentation files")

        if not self.docs_dir.exists():
            error_msg = f"Documentation directory not found: {self.docs_dir}"
            logger.error(error_msg)
            return error_msg

        md_files = sorted(self.docs_dir.rglob("*.md"))

        if not md_files:
            return f"No documentation files found in {self.docs_dir}"

        file_list = []
        for md_file in md_files:
            relative_path = md_file.relative_to(self.docs_dir.parent)
            file_size = md_file.stat().st_size
            file_list.append(f"- {relative_path} ({file_size:,} bytes)")

        result = "Available documentation files:\n" + "\n".join(file_list)
        logger.info(f"Listed {len(md_files)} documentation files")
        return result

    @kernel_function(
        name="get_document_by_name",
        description="Retrieves a specific documentation file by its filename or path. Use this when"
        + " the user asks for a specific document (e.g., 'show me ARCHITECTURE.md', "
        + "'get the HA testing doc').",
    )
    def get_document_by_name(
        self,
        filename: Annotated[
            str,
            "The filename or path of the document to retrieve (e.g., 'ARCHITECTURE.md', "
            + "'high_availability/DB_HIGH_AVAILABILITY.md')",
        ],
    ) -> Annotated[str, "Content of the requested documentation file"]:
        """
        Retrieve a specific documentation file by name.

        :param filename: The name or relative path of the documentation file.
        :type filename: str
        :return: Content of the requested file.
        :rtype: str
        """
        logger.info(f"Retrieving document: {filename}")

        if not self.docs_dir.exists():
            error_msg = f"Documentation directory not found: {self.docs_dir}"
            logger.error(error_msg)
            return error_msg

        md_files = list(self.docs_dir.rglob("*.md"))
        filename_lower = filename.lower()
        for md_file in md_files:
            if md_file.name.lower() == filename_lower:
                try:
                    content = md_file.read_text(encoding="utf-8")
                    relative_path = md_file.relative_to(self.docs_dir.parent)
                    logger.info(f"Found exact match: {relative_path}")
                    return f"--- {relative_path} ---\n{content}"
                except Exception as e:
                    error_msg = f"Error reading {md_file}: {e}"
                    logger.error(error_msg)
                    return error_msg

        for md_file in md_files:
            relative_path = str(md_file.relative_to(self.docs_dir.parent))
            if filename_lower in relative_path.lower():
                try:
                    content = md_file.read_text(encoding="utf-8")
                    logger.info(f"Found partial match: {relative_path}")
                    return f"--- {relative_path} ---\n{content}"
                except Exception as e:
                    error_msg = f"Error reading {md_file}: {e}"
                    logger.error(error_msg)
                    return error_msg

        available_files = "\n".join(
            f"  - {md_file.relative_to(self.docs_dir.parent)}" for md_file in md_files[:10]
        )
        error_msg = f"Document '{filename}' not found.\n\nAvailable documents:\n{available_files}"
        if len(md_files) > 10:
            error_msg += f"\n  ... and {len(md_files) - 10} more"

        logger.warning(f"Document not found: {filename}")
        return error_msg
