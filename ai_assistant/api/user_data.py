import logging

from fastapi import APIRouter
from starlette.responses import JSONResponse

from ai_assistant.services.conversations_service import get_conversations_service

logger = logging.getLogger(__name__)

user_data_router = APIRouter(tags=["user-data"])


@user_data_router.post("/users/{user_id}/deletion-requests", status_code=202)
async def request_user_data_deletion(user_id: str) -> JSONResponse:
    """Enqueue a deletion of all data for *user_id*. Returns 202 with the job id."""
    service = get_conversations_service()
    job_id = await service.request_user_data_deletion(user_id)
    logger.info("queued deletion job %s for user %s", job_id, user_id)
    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "status": "pending"},
    )


@user_data_router.get("/deletion-requests/{job_id}")
async def get_deletion_request(job_id: str) -> JSONResponse:
    """Return the current state of a deletion job, or 404 if it does not exist."""
    service = get_conversations_service()
    job = await service.get_deletion_job(job_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "detail": f"deletion job {job_id} not found"},
        )
    return JSONResponse(
        content={
            "job_id": job.job_id,
            "user_id": job.user_id,
            "status": job.status.value,
            "conversations_deleted": job.conversations_deleted,
            "messages_deleted": job.messages_deleted,
            "pending_conversations": len(job.pending_conversation_ids),
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        },
    )
