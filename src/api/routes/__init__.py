# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""API routes package."""

from src.api.routes.health import router as health_router, set_health_service
from src.api.routes.jobs import router as jobs_router, set_job_store, set_job_worker
from src.api.routes.schedules import (
    router as schedules_router,
    set_schedule_store,
    set_scheduler_service,
)
from src.api.routes.workspaces import router as workspaces_router, set_workspace_loader
from src.api.routes.chat import router as chat_router, set_conversation_store

__all__ = [
    "health_router",
    "jobs_router",
    "schedules_router",
    "workspaces_router",
    "chat_router",
    "set_job_store",
    "set_job_worker",
    "set_schedule_store",
    "set_scheduler_service",
    "set_workspace_loader",
    "set_conversation_store",
    "set_health_service",
]
