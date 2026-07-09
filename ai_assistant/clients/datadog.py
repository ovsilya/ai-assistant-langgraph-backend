import ddtrace

from config import APP_NAME, APP_VERSION, DATADOG_ENABLED, ENABLE_DD_FASTAPI_INTEGRATION


def configure_datadog() -> None:
    if not DATADOG_ENABLED:
        return

    ddtrace.config.fastapi["service_name"] = APP_NAME
    ddtrace.config.fastapi["request_span_name"] = f"{APP_NAME}.request"
    ddtrace.config.version = APP_VERSION
    ddtrace.patch(fastapi=ENABLE_DD_FASTAPI_INTEGRATION)
