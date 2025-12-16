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
from src.agents.models.action import ActionJob, ActionPlan
from src.agents.models.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageRole,
)
from src.agents.models.conversation import (
    Conversation,
    ConversationListItem,
    ConversationSummary,
    ConversationWithMessages,
    Message,
)
from src.agents.models.execution import (
    ExecutionRequest,
    ExecutionResult,
    GuardReason,
    GuardResult,
)
from src.agents.models.job import ExecutionJob, JobEvent, JobEventType, JobStatus
from src.agents.models.reasoning import ReasoningStep, ReasoningTrace
from src.agents.models.streaming import (
    StreamEvent,
    StreamEventType,
    ThinkingStep,
    emit_thinking_end,
    emit_thinking_start,
    emit_thinking_step,
    get_stream_callback,
    set_stream_callback,
)
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
    # Action plan models
    "ActionJob",
    "ActionPlan",
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
    "GuardReason",
    "GuardResult",
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
