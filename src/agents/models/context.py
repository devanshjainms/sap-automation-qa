# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Pydantic models for request-scoped context.
"""
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, field


@dataclass
class RequestContextData:
    """Data container for request-scoped context."""

    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    correlation_id: Optional[str] = None
    workspace_id: Optional[str] = None
    sid: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)
