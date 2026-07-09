from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from ai_assistant.agent.routing import route_after_assemble, route_after_input_guardrail
from ai_assistant.nodes.assemble_response import assemble_response
from ai_assistant.nodes.build_fallback import build_fallback
from ai_assistant.nodes.generate_response import generate_response
from ai_assistant.nodes.get_related import get_related_node
from ai_assistant.nodes.input_guardrail import input_guardrail
from ai_assistant.nodes.load_context import load_context
from ai_assistant.nodes.output_guardrail import output_guardrail
from ai_assistant.nodes.query_index import query_index_node
from ai_assistant.nodes.stream_output import stream_output
from ai_assistant.state import AgentState


@lru_cache
def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("load_context", load_context)
    builder.add_node("input_guardrail", input_guardrail)
    builder.add_node("query_index", query_index_node)
    builder.add_node("get_related", get_related_node)
    builder.add_node("generate_response", generate_response)
    builder.add_node("output_guardrail", output_guardrail)
    builder.add_node("assemble_response", assemble_response)
    builder.add_node("build_fallback", build_fallback)
    builder.add_node("stream_output", stream_output)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "input_guardrail")

    builder.add_conditional_edges(
        "input_guardrail",
        route_after_input_guardrail,
        ["build_fallback", "generate_response", "query_index", "get_related"],
    )

    builder.add_edge("query_index", "generate_response")
    builder.add_edge("get_related", "generate_response")

    builder.add_edge("generate_response", "output_guardrail")
    builder.add_edge("output_guardrail", "assemble_response")

    builder.add_conditional_edges(
        "assemble_response",
        route_after_assemble,
        {
            "stream_output": "stream_output",
            "generate_response": "generate_response",
            "build_fallback": "build_fallback",
        },
    )

    builder.add_edge("build_fallback", "stream_output")
    builder.add_edge("stream_output", END)

    return builder.compile()


graph = build_graph()
