from ai_assistant.state import AgentState


async def stream_output(state: AgentState) -> dict:
    """Terminal graph node — response is read from state by the API layer."""
    return {}
