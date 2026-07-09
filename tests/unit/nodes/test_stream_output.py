"""Unit tests for stream_output node."""

import pytest

from ai_assistant.nodes.stream_output import stream_output


@pytest.mark.asyncio
async def test_stream_output_is_no_op():
    assert await stream_output({"response": "hello"}) == {}
