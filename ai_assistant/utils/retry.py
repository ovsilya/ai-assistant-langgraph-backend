import asyncio
import functools
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_UNSET = object()


def retry_if_error(
    number_of_tries: int = 3,
    delay: float = 0.5,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    default_result: Any = _UNSET,
    error_callback: Callable[[Exception], None] | None = None,
) -> Callable:
    """Retry a function on specified exceptions with optional delay between attempts.

    Args:
        number_of_tries: Maximum number of attempts (including the first call).
        delay: Seconds to wait between retries. Set to 0 for no delay.
        exceptions: Tuple of exception types that should trigger a retry.
                    Exceptions not in this tuple propagate immediately.
        default_result: If provided, return this value instead of re-raising when all
                        retries are exhausted. Supports None as a legitimate value.
        error_callback: Optional callable invoked with each caught exception,
                        e.g. for logging or metrics.

    Example::

        @retry_if_error(number_of_tries=3, delay=0.5, exceptions=(httpx.ConnectError,))
        def call_external_service():
            ...
    """

    if number_of_tries < 1:
        raise ValueError(f"number_of_tries must be at least 1, got {number_of_tries}")

    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            raise TypeError(
                f"retry_if_error does not support async functions ({func.__qualname__}). "
                "Use an async-aware retry library or wrap the await site manually."
            )

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, number_of_tries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    logger.warning(
                        "retry_if_error: %s.%s attempt %d/%d failed: %s",
                        func.__module__,
                        func.__qualname__,
                        attempt,
                        number_of_tries,
                        exc,
                    )
                    if error_callback is not None:
                        error_callback(exc)
                    if attempt < number_of_tries and delay:
                        time.sleep(delay)
            if default_result is not _UNSET:
                return default_result
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
