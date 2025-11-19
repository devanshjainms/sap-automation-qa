# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Pydantic models for structured SAP HA test planning.

This module defines the contract between the TestPlannerAgent and any test executor.
The models ensure machine-readable test plans with proper metadata, requirements, and safety flags.
"""

from pydantic import BaseModel, Field
from typing import Optional


class ChatMessage(BaseModel):
    """Chat message with role and content."""

    role: str
    content: str


class ChatRequest(BaseModel):
    """Chat request containing a list of messages."""

    messages: list[ChatMessage]
    correlation_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response containing a list of messages."""

    messages: list[ChatMessage]
    test_plan: Optional[dict] = None
    correlation_id: Optional[str] = None
