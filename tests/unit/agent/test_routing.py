from langgraph.types import Send

from ai_assistant.agent.routing import route_after_assemble, route_after_input_guardrail


class TestRouteAfterInputGuardrail:
    def test_blocked_goes_to_fallback(self):
        state = {"intent": "content_question", "guardrail_triggered": "input_topic_block"}
        assert route_after_input_guardrail(state) == "build_fallback"

    def test_small_talk_skips_concorde(self):
        assert route_after_input_guardrail({"intent": "small_talk"}) == "generate_response"

    def test_off_topic_skips_concorde(self):
        assert route_after_input_guardrail({"intent": "off_topic"}) == "generate_response"

    def test_content_question_fans_out_to_concorde_nodes(self):
        result = route_after_input_guardrail({"intent": "content_question"})
        assert isinstance(result, list)
        assert len(result) == 2
        node_names = {s.node for s in result if isinstance(s, Send)}
        assert node_names == {"query_index", "get_related"}


class TestRouteAfterAssemble:
    def test_passed_goes_to_stream(self):
        assert route_after_assemble({"guardrail_passed": True}) == "stream_output"

    def test_retry_once_then_stream(self):
        state = {"guardrail_passed": False, "guardrail_retry_count": 0}
        assert route_after_assemble(state) == "generate_response"

    def test_exhausted_retries_fallback(self):
        state = {"guardrail_passed": False, "guardrail_retry_count": 1}
        assert route_after_assemble(state) == "build_fallback"

    def test_after_assemble_queues_retry_while_count_still_zero(self):
        """assemble_response no longer increments before routing."""
        state = {
            "guardrail_passed": False,
            "guardrail_retry_count": 0,
            "response": "draft that failed review",
        }
        assert route_after_assemble(state) == "generate_response"
