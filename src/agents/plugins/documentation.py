"""
Documentation Plugin for Semantic Kernel.

Provides kernel functions to access and search framework documentation.
Used by EchoAgentSK to answer questions about the SAP Testing Automation Framework.
"""

import json
import logging
import os
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Annotated, Optional

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

        self.bing_api_key = os.environ.get("BING_SEARCH_API_KEY")
        self.bing_endpoint = os.environ.get(
            "BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search"
        )

        logger.info(
            f"DocumentationPlugin initialized with docs_dir: {self.docs_dir}, "
            f"src_dir: {self.src_dir}, web_search_enabled={self.bing_api_key is not None}"
        )

    @kernel_function(
        name="web_search",
        description="Search the internet for SAP, Azure, Pacemaker, or Linux documentation. "
        "Use this for OS-specific commands, latest best practices, or when local docs don't have the answer. "
        "Automatically focuses on Microsoft Learn, SAP Help, and SUSE/Red Hat documentation.",
    )
    def web_search(
        self,
        query: Annotated[
            str,
            "The search query (e.g., 'pacemaker cluster status RHEL 9', 'SAP HANA system replication')",
        ],
        site_filter: Annotated[
            Optional[str],
            "Optional site filter: 'microsoft', 'sap', 'suse', 'redhat', or None for all",
        ] = None,
    ) -> Annotated[str, "JSON with search results including titles, snippets, and URLs"]:
        """
        Search the web for SAP/Azure/Linux documentation.

        Falls back to curated knowledge base if Bing API is not configured.

        :param query: Search query
        :param site_filter: Optional site restriction
        :return: JSON string with search results
        """
        logger.info(f"Web search: '{query}' (site_filter={site_filter})")
        site_queries = {
            "microsoft": "site:learn.microsoft.com OR site:docs.microsoft.com",
            "sap": "site:help.sap.com OR site:community.sap.com",
            "suse": "site:documentation.suse.com",
            "redhat": "site:access.redhat.com OR site:docs.redhat.com",
        }

        full_query = query
        if site_filter and site_filter.lower() in site_queries:
            full_query = f"{query} {site_queries[site_filter.lower()]}"
        else:
            full_query = f"{query} (site:learn.microsoft.com OR site:help.sap.com OR site:documentation.suse.com OR site:access.redhat.com)"

        if self.bing_api_key:
            try:
                return self._bing_search(full_query)
            except Exception as e:
                logger.warning(f"Bing search failed: {e}, falling back to curated knowledge")
        return self._curated_knowledge_search(query)

    def _bing_search(self, query: str) -> str:
        """Execute Bing Web Search API request."""
        params = urllib.parse.urlencode(
            {
                "q": query,
                "count": 5,
                "responseFilter": "Webpages",
                "textDecorations": False,
                "textFormat": "Raw",
            }
        )

        url = f"{self.bing_endpoint}?{params}"
        headers = {"Ocp-Apim-Subscription-Key": self.bing_api_key or ""}

        request = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.error(f"Bing API error: {e.code} {e.reason}")
            return json.dumps({"error": f"Search API error: {e.code}", "fallback": True})
        except urllib.error.URLError as e:
            logger.error(f"Bing API connection error: {e.reason}")
            return json.dumps({"error": "Search API unavailable", "fallback": True})

        results = []
        for page in data.get("webPages", {}).get("value", []):
            results.append(
                {
                    "title": page.get("name", ""),
                    "url": page.get("url", ""),
                    "snippet": page.get("snippet", ""),
                }
            )

        return json.dumps(
            {
                "query": query,
                "results": results,
                "source": "bing_api",
            },
            indent=2,
        )

    def _curated_knowledge_search(self, query: str) -> str:
        """Return curated knowledge for common SAP/Azure/cluster queries."""
        query_lower = query.lower()

        knowledge_base = {
            "cluster status": {
                "topic": "Checking Pacemaker Cluster Status",
                "content": {
                    "SLES (SUSE)": [
                        "crm status - Show cluster status overview",
                        "crm_mon -1 - One-shot cluster monitor",
                        "crm_mon -r - Show inactive resources",
                        "SAPHanaSR-showAttr - Show HANA SR attributes",
                        "cs_clusterstate - Show cluster state summary",
                    ],
                    "RHEL (Red Hat)": [
                        "pcs status - Show cluster status",
                        "pcs status --full - Detailed status",
                        "pcs resource show - List resources",
                        "pcs stonith show - Show fencing devices",
                        "pcs constraint show - Show constraints",
                    ],
                },
                "references": [
                    "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-suse-pacemaker",
                    "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-rhel-pacemaker",
                ],
            },
            "hana system replication": {
                "topic": "SAP HANA System Replication",
                "content": {
                    "Check replication status": [
                        "hdbnsutil -sr_state - Show SR state on current node",
                        "python /usr/sap/<SID>/HDB<NR>/exe/python_support/systemReplicationStatus.py",
                        "SAPHanaSR-showAttr - Show SR attributes in cluster",
                    ],
                    "Replication modes": [
                        "sync - Synchronous (zero data loss)",
                        "syncmem - Synchronous in-memory",
                        "async - Asynchronous (minimal latency impact)",
                    ],
                },
                "references": [
                    "https://help.sap.com/docs/SAP_HANA_PLATFORM/6b94445c94ae495c83a19646e7c3fd56/676844172c2442f0bf6c8b080db05ae7.html",
                ],
            },
            "stonith": {
                "topic": "STONITH/Fencing in Azure",
                "content": {
                    "Azure Fence Agent": [
                        "fence_azure_arm - Azure Resource Manager fence agent",
                        "Requires managed identity or service principal",
                        "crm resource show stonith-sbd - Check SBD status (SLES)",
                        "pcs stonith show - Check fencing (RHEL)",
                    ],
                    "SBD (STONITH Block Device)": [
                        "sbd -d /dev/disk/by-id/<device> list - List SBD nodes",
                        "sbd -d /dev/disk/by-id/<device> dump - Dump SBD header",
                        "systemctl status sbd - Check SBD service",
                    ],
                },
                "references": [
                    "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-suse-pacemaker#create-a-fencing-device",
                ],
            },
            "azure load balancer": {
                "topic": "Azure Load Balancer for SAP HA",
                "content": {
                    "Health probe configuration": [
                        "Default port: 62500 (HANA), 62000 (SCS)",
                        "socat creates the health probe listener",
                        "nc -l -k <port> - Alternative listener",
                    ],
                    "Verify health probe": [
                        "ss -tlnp | grep <probe_port>",
                        "netstat -tlnp | grep <probe_port>",
                    ],
                },
                "references": [
                    "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-standard-load-balancer-outbound-connections",
                ],
            },
        }
        for key, knowledge in knowledge_base.items():
            if key in query_lower or any(word in query_lower for word in key.split()):
                return json.dumps(
                    {
                        "query": query,
                        "source": "curated_knowledge",
                        "note": "Based on curated SAP/Azure documentation. For latest info, configure BING_SEARCH_API_KEY.",
                        **knowledge,
                    },
                    indent=2,
                )
        return json.dumps(
            {
                "query": query,
                "source": "curated_knowledge",
                "message": "No curated knowledge found for this query.",
                "suggestions": [
                    "Try searching local documentation with search_documentation()",
                    "Check specific terms with lookup_term() from glossary",
                    "Configure BING_SEARCH_API_KEY for live web search",
                ],
                "useful_references": [
                    "https://learn.microsoft.com/en-us/azure/sap/workloads/",
                    "https://help.sap.com/docs/SAP_HANA_PLATFORM",
                    "https://documentation.suse.com/sles-sap/",
                ],
            },
            indent=2,
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
