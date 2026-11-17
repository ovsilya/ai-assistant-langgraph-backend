# AI Assistant — LangGraph Conversational Backend

A FastAPI + LangGraph backend for a chat assistant embedded on the article pages of a large magazine publisher's brand sites. Readers ask questions, and the assistant answers from the brand's own articles and recommends what to read next. Every chat turn runs a deterministic LangGraph `StateGraph` workflow:

**load context → input guardrail + intent routing → parallel content retrieval → grounded generation → output guardrail with one bounded retry → safe fallback.**

<a href="https://ovsilya.github.io/ai-assistant-langgraph-backend/diagrams/ai-assistant-architecture.html"><img src="docs/diagrams/png/architecture-board.png" width="900" alt="Architecture board: the widget calls the FastAPI LangGraph backend; the graph runs load context, input guardrail and intent router, retrieval, generation, follow-ups and output guardrail, assemble, fallback and stream; data layer and observability on the left; graph state and external services (config, content search, AI gateway) on the right; agent observability and deployment at the bottom"></a>

*Click the image for the interactive version.* The diagram shows the **target design** for this backend. Beyond the code in this repository it adds SSE token streaming, follow-up suggestions running in parallel with the output guardrail, and a LangSmith evaluation suite. The [evaluation board](docs/diagrams/README.md#evaluation-board) covers the datasets, the 14 evaluators and the experiment results.

## What the code does

- **Multi-brand personality system:** each magazine brand is a data-only JSON config (persona, tone, system prompt, blocked topics, output-filter rules, all prompt templates). Adding a brand needs no code changes.
- **RAG over publisher content:** semantic search (`query_index`) and the related-articles lookup (`get_related`) run in parallel (LangGraph fan-out / fan-in) and append to `state.articles` through a reducer. The generator answers only from the retrieved articles, with `[n]` citations.
- **LLM-as-judge guardrails:** on input, one cheap LLM call classifies the intent *and* filters blocked topics (routing to `content_question`, `small_talk`, `off_topic` or `blocked`). On output, a judge checks grounding, banned language patterns and hallucinated citations. One corrective retry, then a safe static fallback.
- **Provider abstraction:** LLM calls go through the company's AI gateway (LiteLLM, OpenAI-compatible, Claude models). A Gemini provider sits behind the same client interface and is selected with `LLM_PROVIDER`.
- **Persistence outside the graph:** DynamoDB conversations / messages / status tables are written by a background task after the graph finishes. Redis holds the recent conversation context.
- **GDPR deletion worker:** user-data deletion requests run as asynchronous jobs in a separate worker deployment.
- **Streaming-ready:** the graph ends in a `stream_output` node. The API returns the full JSON response today; SSE token streaming is part of the target design.
- **Observability:** Datadog APM and `ai_assistant.*` metrics, plus Sentry. The LLM-telemetry design is in [`docs/OBSERVABILITY_GUIDE.md`](docs/OBSERVABILITY_GUIDE.md).

## Key engineering highlights

- **300+ unit and integration tests, ~95% line coverage** on the `ai_assistant` package (`pytest`, `pytest-asyncio`, dependency-injected fakes; tests that call the live gateway are behind an `integration` marker).
- **Bounded guardrail retry loop** owned by a fan-in node: when the output check fails, the node adds a corrective instruction to the state and routes back to `generate_response` exactly once, then falls back. There are no unbounded LLM loops.
- **Data-driven brand configs** with startup validation: required prompt templates are checked per brand, and a missing per-brand search-index UUID raises an error instead of silently serving another brand's content.
- **Strict ID discipline:** API brand slugs, site-registry UUIDs and CMS content UUIDs are kept distinct, with a single resolution helper ([`docs/IDS_REFERENCE.md`](docs/IDS_REFERENCE.md)).
- **Resilience:** retry with exponential backoff for AWS calls, request-scoped timeouts on all outbound HTTP, and graceful degradation when retrieval returns nothing.

## Tech stack

Python 3.13 · FastAPI · LangGraph / LangChain · AI gateway (LiteLLM, Claude) with a switchable Gemini provider · DynamoDB (aioboto3) · Redis · Docker Compose + LocalStack · Kubernetes · Datadog · Sentry · uv · Ruff · pytest

## Repository structure

```
ai_assistant/
  agent/         # StateGraph assembly + conditional routing
  nodes/         # one module per graph node (guardrails, retrieval, generation, ...)
  llm/           # provider abstraction: ai_gateway (LiteLLM) | gemini
  services/      # brand config, content search ("concorde"), persistence, context store
  clients/       # DynamoDB, Redis, Datadog, Sentry
  models/        # conversation / message / deletion-job models
  workers/       # GDPR deletion worker
  api/           # FastAPI routes: chat, health, user data (GDPR)
config/
  base.py        # env-driven settings
  brands/        # per-brand JSON personality + prompt configs
tests/           # unit + integration suites, trajectory fixtures
docs/            # architecture, observability, testing, schema and ID references
  diagrams/      # architecture + evaluation boards (HTML + PNG previews)
k8s/             # deployment, service, ingress, deletion-worker manifests
```

> Naming note: `concorde` is the retained internal module name for the publisher's content-search service. The docs call it the Content Search API.

## Local development

```bash
# with Docker (API + LocalStack DynamoDB + Redis)
docker compose up ai-assistant          # API on http://localhost:8000

# run the test suite in Docker
docker compose up ai-assistant-test

# or natively
uv sync
cp .env.example .env                    # fill in placeholder values
uv run pytest -m "not integration"
uv run ruff check .
```

Endpoints: `POST /v1/assistant/chat/{site_id}`, `POST /users/{user_id}/deletion-requests`, `GET /deletion-requests/{job_id}`, `GET /health`, `GET /health/dynamodb`.

## Documentation

| Doc | What it covers |
|---|---|
| [`docs/diagrams/`](docs/diagrams/README.md) | Architecture and evaluation boards (target design) |
| [`10_AGENTIC_ARCHITECTURE.md`](docs/10_AGENTIC_ARCHITECTURE.md) | Graph nodes, state, routing, retry loop, request/response examples |
| [`AI_ASSISTANT_SCHEMA.md`](docs/AI_ASSISTANT_SCHEMA.md) | Multi-tenant config, brand personality fields, data models |
| [`GENERATE_RESPONSE.md`](docs/GENERATE_RESPONSE.md) | The generation step: prompt assembly, context, citations |
| [`IDS_REFERENCE.md`](docs/IDS_REFERENCE.md) | Every ID in the system and where it is resolved |
| [`OBSERVABILITY_GUIDE.md`](docs/OBSERVABILITY_GUIDE.md) | Logs, metrics, traces and LLM telemetry |
| [`AWS_BEDROCK_GUARDRAILS.md`](docs/AWS_BEDROCK_GUARDRAILS.md) | Spike: can AWS Bedrock Guardrails check a response while it streams? |
| [`TESTING_GUIDE.md`](docs/TESTING_GUIDE.md) | Test layout, fixtures, CI steps |

## Note

Sanitized portfolio version of a production system built during a client engagement at TELUS Digital. All client identifiers, internal URLs, credentials and proprietary references are removed or replaced with placeholders. Brand configurations use fictional magazine brands; UUIDs, hostnames and account IDs are placeholders.
