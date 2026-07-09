import sentry_sdk
from fastapi import APIRouter
from starlette.responses import JSONResponse

sentry_test_router = APIRouter(
    tags=["sentry"],
    responses={404: {"description": "Not Found"}},
)


@sentry_test_router.get("/sentry-test")
def test_sentry() -> JSONResponse:
    error = RuntimeError("AI Assistant test Sentry event")
    event_id = sentry_sdk.capture_exception(error)
    sentry_sdk.flush(timeout=2.0)

    return JSONResponse(
        content={
            "event_id": event_id,
            "status": "captured",
        },
        status_code=200,
    )
