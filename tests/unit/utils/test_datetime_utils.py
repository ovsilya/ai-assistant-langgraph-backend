from datetime import UTC, datetime

import pytest

from ai_assistant.utils.datetime_utils import (
    parse_iso8601_datetime,
    utc_now_iso,
    validate_iso8601_datetime,
)

# ------------------------------------------------------------------
# validate_iso8601_datetime
# ------------------------------------------------------------------


class TestValidateIso8601Datetime:
    def test_accepts_valid_value(self):
        value = "2026-01-01T00:00:00+00:00"

        result = validate_iso8601_datetime(value)

        assert result == value

    def test_accepts_z_suffix(self):
        # Python 3.11+ fromisoformat() handles the Z UTC suffix; ensure it is
        # treated as timezone-aware (UTC) rather than rejected as naive.
        value = "2026-01-01T00:00:00Z"

        result = validate_iso8601_datetime(value)

        assert result == value

    def test_rejects_invalid_value(self):
        with pytest.raises(ValueError, match="ISO 8601"):
            validate_iso8601_datetime("not-a-date")

    @pytest.mark.parametrize(
        "value",
        [
            "2026-01-01",
            "2026-01-01T00:00:00",
        ],
    )
    def test_rejects_naive_value(self, value):
        with pytest.raises(ValueError, match="timezone-aware"):
            validate_iso8601_datetime(value)


# ------------------------------------------------------------------
# parse_iso8601_datetime
# ------------------------------------------------------------------


class TestParseIso8601Datetime:
    def test_returns_datetime_with_tzinfo(self):
        result = parse_iso8601_datetime("2026-01-01T00:00:00+00:00")

        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_z_suffix_is_timezone_aware(self):
        result = parse_iso8601_datetime("2026-01-01T00:00:00Z")

        assert result.tzinfo is not None

    def test_non_utc_offset_is_timezone_aware(self):
        result = parse_iso8601_datetime("2026-01-01T12:00:00+05:30")

        assert result.tzinfo is not None

    def test_compares_timestamps_correctly_across_offsets(self):
        # "2026-12-01T00:00:00+00:00" is later in UTC than
        # "2026-12-01T06:00:00+07:00" (= 2026-11-30T23:00:00 UTC).
        utc_midnight = parse_iso8601_datetime("2026-12-01T00:00:00+00:00")
        ahead_of_utc = parse_iso8601_datetime("2026-12-01T06:00:00+07:00")

        assert utc_midnight > ahead_of_utc

    def test_rejects_invalid_string(self):
        with pytest.raises(ValueError, match="ISO 8601"):
            parse_iso8601_datetime("not-a-date")

    def test_rejects_naive_datetime(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            parse_iso8601_datetime("2026-01-01T00:00:00")


# ------------------------------------------------------------------
# utc_now_iso
# ------------------------------------------------------------------


class TestUtcNowIso:
    def test_result_is_parseable_as_iso8601(self):
        result = utc_now_iso()

        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None

    def test_result_is_close_to_utc_now(self):
        before = datetime.now(UTC)
        result = utc_now_iso()
        after = datetime.now(UTC)

        parsed = datetime.fromisoformat(result)
        assert before <= parsed <= after
