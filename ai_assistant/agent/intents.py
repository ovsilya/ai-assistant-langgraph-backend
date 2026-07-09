"""Canonical intent labels and guardrail signals.

Intents are control flow — the router (`route_after_input_guardrail`) and graph
edges branch on these exact values — so they live in code, not brand config.
Brand config owns *data* (topics, domains, prompt wording); this module owns the
*behavior contract* shared by the classifier, the node, the state, and the router.

`Intent` is purely a content-routing category (which downstream node handles the
message). Whether the message is *safe to answer at all* is a separate decision,
signaled independently via `guardrail_triggered` — keeping "is this allowed" out
of the same enum as "what kind of message is this" so the two can't be confused
or crowd each other out of a single classification slot.
"""

from enum import StrEnum


class Intent(StrEnum):
    SMALL_TALK = "small_talk"
    CONTENT_QUESTION = "content_question"
    OFF_TOPIC = "off_topic"


VALID_INTENTS: frozenset[str] = frozenset(i.value for i in Intent)

# Default when the classifier returns an unknown/malformed intent. content_question
# is the safe default: it routes through retrieval + grounding rather than answering ungrounded.
DEFAULT_INTENT: Intent = Intent.CONTENT_QUESTION

# guardrail_triggered signals (surfaced on the API response).
GUARDRAIL_INPUT_TOPIC_BLOCK = "input_topic_block"
GUARDRAIL_EMPTY_INPUT = "empty_input"

# Static reply for an empty/whitespace-only message. Not brand-voiced — it's a
# mechanical nudge — so it stays a constant instead of a per-brand prompt.
EMPTY_INPUT_MESSAGE = "It looks like your message was empty — please type a question and I'll help."
