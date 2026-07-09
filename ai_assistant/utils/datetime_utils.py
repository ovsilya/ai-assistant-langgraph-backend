from datetime import UTC, datetime


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso8601_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("must be a valid ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError("must be a timezone-aware ISO 8601 datetime")
    return parsed


def validate_iso8601_datetime(value: str) -> str:
    parse_iso8601_datetime(value)
    return value
