from unittest.mock import Mock, patch

import pytest

from ai_assistant.utils import retry_if_error

MODULE = "ai_assistant.utils.retry"


class _RetryableError(Exception):
    pass


class _OtherError(Exception):
    pass


class TestRetryIfError:
    def test_returns_on_first_success(self):
        call_count = [0]

        @retry_if_error(number_of_tries=3, delay=0, exceptions=(_RetryableError,))
        def succeed():
            call_count[0] += 1
            return "ok"

        assert succeed() == "ok"
        assert call_count[0] == 1

    @patch(f"{MODULE}.time.sleep")
    def test_retries_then_succeeds(self, mock_sleep):
        call_count = [0]

        @retry_if_error(number_of_tries=3, delay=0.5, exceptions=(_RetryableError,))
        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise _RetryableError("transient")
            return "ok"

        assert flaky() == "ok"
        assert call_count[0] == 3
        assert mock_sleep.call_count == 2

    @patch(f"{MODULE}.time.sleep")
    def test_reraises_after_exhausting_retries(self, mock_sleep):
        @retry_if_error(number_of_tries=2, delay=0.1, exceptions=(_RetryableError,))
        def always_fails():
            raise _RetryableError("still failing")

        with pytest.raises(_RetryableError, match="still failing"):
            always_fails()

        # With 2 tries there is exactly 1 inter-attempt sleep.
        mock_sleep.assert_called_once_with(0.1)

    @patch(f"{MODULE}.time.sleep")
    def test_returns_default_result_when_exhausted(self, mock_sleep):
        @retry_if_error(
            number_of_tries=2,
            delay=0,
            exceptions=(_RetryableError,),
            default_result="fallback",
        )
        def always_fails():
            raise _RetryableError("still failing")

        assert always_fails() == "fallback"

    @patch(f"{MODULE}.time.sleep")
    def test_returns_none_default_result_when_exhausted(self, mock_sleep):
        @retry_if_error(
            number_of_tries=2,
            delay=0,
            exceptions=(_RetryableError,),
            default_result=None,
        )
        def always_fails():
            raise _RetryableError("still failing")

        assert always_fails() is None

    def test_propagates_unlisted_exceptions_immediately(self):
        call_count = [0]

        @retry_if_error(number_of_tries=3, delay=0, exceptions=(_RetryableError,))
        def raises_other():
            call_count[0] += 1
            raise _OtherError("not retryable")

        with pytest.raises(_OtherError, match="not retryable"):
            raises_other()
        assert call_count[0] == 1

    @patch(f"{MODULE}.time.sleep")
    def test_invokes_error_callback(self, mock_sleep):
        callback = Mock()

        @retry_if_error(
            number_of_tries=2,
            delay=0,
            exceptions=(_RetryableError,),
            error_callback=callback,
        )
        def always_fails():
            raise _RetryableError("boom")

        with pytest.raises(_RetryableError):
            always_fails()

        assert callback.call_count == 2
        for call in callback.call_args_list:
            assert isinstance(call.args[0], _RetryableError)
