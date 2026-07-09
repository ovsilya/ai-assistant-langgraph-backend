#!/usr/bin/env python3
# ruff: noqa: E402
"""Message-only LangGraph demo — live node trace + response summary.

Run from the ai-assistant repo root (VPN + .env with AI_GATEWAY_API_KEY required):

    uv run python scripts/demo_chat.py --demo
    uv run python scripts/demo_chat.py --scenario blocked_medical
    uv run python scripts/demo_chat.py --message "Hello!" --url https://www.meridian.example.com/
    uv run python scripts/demo_chat.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from langchain_core.messages import HumanMessage

from ai_assistant.agent.graph import graph

TRAJECTORY_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "trajectory_tests.json"

DEMO_SCENARIO_NAMES = (
    "small_talk",
    "blocked_medical",
    "off_topic",
    "content_question",
)

NODE_HINTS: dict[str, str] = {
    "load_context": "brand config + conversation history",
    "input_guardrail": "classify intent · input safety (haiku)",
    "query_index": "Concorde semantic search",
    "get_related": "CDN related articles",
    "generate_response": "main LLM reply + topics/follow-ups",
    "output_guardrail": "grounding + safety review (haiku)",
    "assemble_response": "merge · pass / retry / fallback",
    "build_fallback": "safe fallback message",
    "stream_output": "finalize (no token streaming yet)",
}

GRAPH_NODES = frozenset(NODE_HINTS)


def load_scenarios() -> list[dict]:
    return json.loads(TRAJECTORY_FIXTURE.read_text())


def build_state(
    *,
    message: str,
    url: str = "https://www.meridian.example.com/",
    site_id: str = "brand_alpha_us",
    content_id: str | None = None,
) -> dict:
    state: dict = {
        "user_id": "demo_user",
        "conversation_id": None,
        "site_id": site_id,
        "url": url,
        "messages": [HumanMessage(content=message)],
    }
    if content_id:
        state["content_id"] = content_id
    return state


def state_from_scenario(case: dict) -> dict:
    return build_state(
        message=case["message"],
        url=case.get("url") or "https://www.meridian.example.com/",
        content_id=case.get("content_id"),
    )


def print_banner(case: dict | None, message: str) -> None:
    print()
    print("=" * 72)
    if case:
        expected = case.get("expected_intent", "?")
        print(f"  {case['name']}  (expected intent: {expected})")
    print(f'  User: "{message}"')
    print("=" * 72)
    print("  Graph path:")


def print_node(node: str) -> None:
    hint = NODE_HINTS.get(node, "")
    suffix = f" — {hint}" if hint else ""
    print(f"    → {node}{suffix}")


def print_summary(state: dict) -> None:
    response = (state.get("response") or "").strip()
    preview = response[:320] + ("…" if len(response) > 320 else "")

    related = state.get("related_articles") or []
    query_index = state.get("query_index_articles") or []
    topics = state.get("topics") or []
    follow_ups = state.get("follow_up_suggestions") or []

    print()
    print("  Result:")
    print(f"    intent:              {state.get('intent')}")
    print(f"    guardrail_triggered:   {state.get('guardrail_triggered')}")
    print(f"    guardrail_passed:      {state.get('guardrail_passed')}")
    print(f"    guardrail_retry_count: {state.get('guardrail_retry_count', 0)}")
    print(f"    model_used:            {state.get('model_used')}")
    print(f"    recommendations:       related={len(related)}, query_index={len(query_index)}")
    if related or query_index:
        print("    articles for LLM context:")
        for i, article in enumerate(related[:5], 1):
            title = (article.get("title") or "(untitled)")[:70]
            print(f"      related [{i}] {title}")
        for i, article in enumerate(query_index[:5], 1):
            title = (article.get("title") or "(untitled)")[:70]
            print(f"      search  [{i}] {title}")
    print(f"    topics / follow-ups:   {len(topics)} / {len(follow_ups)}")
    if topics:
        print(f"    topics:                {topics[:4]}")
    if follow_ups:
        print(f"    follow_up_suggestions: {follow_ups[:3]}")
    print(f'    response preview:      "{preview}"')
    print()


async def run_turn(state: dict, case: dict | None = None) -> dict:
    message = state["messages"][0].content
    print_banner(case, message)

    final_state: dict = {}

    async for mode, chunk in graph.astream(state, stream_mode=["updates", "values"]):
        if mode == "updates":
            for node in chunk:
                if node in GRAPH_NODES:
                    print_node(node)
        elif mode == "values":
            final_state = chunk

    return final_state


async def run_demo(scenarios: list[dict]) -> int:
    errors = 0
    for name in DEMO_SCENARIO_NAMES:
        case = next((s for s in scenarios if s["name"] == name), None)
        if case is None:
            print(f"Missing scenario {name!r} in {TRAJECTORY_FIXTURE}", file=sys.stderr)
            errors += 1
            continue
        try:
            result = await run_turn(state_from_scenario(case), case)
            print_summary(result)
        except Exception as exc:
            errors += 1
            print(f"\n  ERROR: {exc}\n", file=sys.stderr)
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the AI Assistant LangGraph with live node tracing (no HTTP).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--demo",
        action="store_true",
        help=f"Run preset demo scenarios: {', '.join(DEMO_SCENARIO_NAMES)}",
    )
    group.add_argument(
        "--scenario",
        metavar="NAME",
        help="Run one fixture scenario by name (see --list)",
    )
    group.add_argument(
        "--message",
        metavar="TEXT",
        help="Run a custom user message (use with --url)",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List trajectory fixture scenarios and exit",
    )

    parser.add_argument(
        "--url",
        default="https://www.meridian.example.com/",
        help="Page URL context (default: Meridian homepage)",
    )
    parser.add_argument(
        "--content-id",
        default=None,
        help="CMS content UUID for get_related (optional)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenarios = load_scenarios()

    if args.list:
        print("Trajectory scenarios (tests/fixtures/trajectory_tests.json):\n")
        for case in scenarios:
            marker = " *" if case["name"] in DEMO_SCENARIO_NAMES else ""
            print(f"  {case['name']}{marker}  →  {case['expected_intent']}")
            print(f'    "{case["message"][:70]}{"…" if len(case["message"]) > 70 else ""}"')
        print("\n  * included in --demo")
        return 0

    if args.demo:
        return asyncio.run(run_demo(scenarios))

    if args.scenario:
        case = next((s for s in scenarios if s["name"] == args.scenario), None)
        if case is None:
            names = ", ".join(s["name"] for s in scenarios)
            print(f"Unknown scenario {args.scenario!r}. Choose from: {names}", file=sys.stderr)
            return 1
        state = state_from_scenario(case)
    else:
        state = build_state(
            message=args.message,
            url=args.url,
            content_id=args.content_id,
        )
        case = None

    try:
        result = asyncio.run(run_turn(state, case))
        print_summary(result)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "\nCheck VPN and ai-assistant/.env (AI_GATEWAY_API_KEY, CONCORDE_*).",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
