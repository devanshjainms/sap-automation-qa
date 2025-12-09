"""Pydantic models for SAP QA agents."""

from src.agents.models.api import (
    AgentInfo,
    AgentListResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    CreateConversationRequest,
    DebugEnvResponse,
    HealthResponse,
    MessageListResponse,
    MessageResponse,
    SendMessageRequest,
    StatusResponse,
    UpdateConversationRequest,
)
from src.agents.models.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageRole,
)
from src.agents.models.conversation import (
    Conversation,
    ConversationSummary,
    ConversationWithMessages,
    Message,
)
from src.agents.models.execution import ExecutionRequest, ExecutionResult
from src.agents.models.job import ExecutionJob, JobEvent, JobEventType, JobStatus
from src.agents.models.reasoning import ReasoningStep, ReasoningTrace
from src.agents.models.test import PlannedTest, TestPlan
from src.agents.models.workspace import WorkspaceMetadata

__all__ = [
    # API request/response models
    "AgentInfo",
    "AgentListResponse",
    "ConversationDetailResponse",
    "ConversationListResponse",
    "ConversationResponse",
    "CreateConversationRequest",
    "DebugEnvResponse",
    "HealthResponse",
    "MessageListResponse",
    "MessageResponse",
    "SendMessageRequest",
    "StatusResponse",
    "UpdateConversationRequest",
    # Chat models
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "MessageRole",
    # Conversation persistence models
    "Conversation",
    "ConversationSummary",
    "ConversationWithMessages",
    "Message",
    # Execution models
    "ExecutionRequest",
    "ExecutionResult",
    # Job execution models
    "ExecutionJob",
    "JobEvent",
    "JobEventType",
    "JobStatus",
    # Reasoning models
    "ReasoningStep",
    "ReasoningTrace",
    # Test models
    "PlannedTest",
    "TestPlan",
    # Workspace models
    "WorkspaceMetadata",
]
