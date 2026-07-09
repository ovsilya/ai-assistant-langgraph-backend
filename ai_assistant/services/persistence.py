"""Conversation persistence placeholder — full DynamoDB implementation lands separately."""

import logging

logger = logging.getLogger(__name__)


def persist_turn(state: dict, user_message: str) -> None:
    """No-op until conversation storage merges.

    The chat route still calls this hook so wiring stays stable when persistence lands.
    """
    logger.debug(
        "persist_turn skipped (not implemented in this PR) conversation_id=%s",
        state.get("conversation_id"),
    )
