# Observability, Monitoring & Tracking

### A practical guide for enterprise and LLM-powered applications — grounded in the MediaCo AI Assistant Phase 2 architecture

---

## Table of Contents

1. [Architecture + Observability Visual Map](#1-architecture--observability-visual-map)
2. [What Is Observability?](#2-what-is-observability)
3. [The Four Signals: Logs, Metrics, Traces, LLM Signals](#3-the-four-signals-logs-metrics-traces-llm-signals)
4. [Tags — How You Filter Everything](#4-tags--how-you-filter-everything)
5. [The Chosen Toolset](#5-the-chosen-toolset)
6. [Tracking — What Are Users Doing?](#6-tracking--what-are-users-doing)
7. [Monitoring — Is the Service Healthy?](#7-monitoring--is-the-service-healthy)
8. [APM — Where Did the Time Go?](#8-apm--where-did-the-time-go)
9. [Error Tracking — What Broke and Why?](#9-error-tracking--what-broke-and-why)
10. [AI Assistant Phase 2 — Agentic Observability](#10-ai-assistant-phase-2--agentic-observability)
11. [Best Practices](#11-best-practices)
12. [Quick Reference](#12-quick-reference)

---

## 1. Architecture + Observability Visual Map

> Read the legend first, then trace the request from top (user) to bottom (data stores), noting which observability domain covers each layer.

### Legend

```
 Domain          Tool(s)                            Annotation used below
 ─────────────── ────────────────────────────────── ──────────────────────
 [T]  TRACKING   GTM · GA4 · BigQuery · Looker      user behaviour events
 [M]  METRICS    Datadog DogStatsD (counters/gauges) health & cost numbers
 [TR] TRACES     Datadog ddtrace (distributed spans) where did time go
 [L]  LLM        ddtrace tags + LangSmith            model · tokens · cost
 [E]  ERRORS     Sentry + Datadog error counters     stack traces + alerts
 [Lo] LOGS       Datadog Log Mgmt (structured JSON)  what happened verbatim
```

---

### Diagram 1 — Full Phase 2 Architecture with Observability Domains

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║  USER LAYER                                                                      ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║   ┌──────────┐   interacts with   ┌─────────────────────────────────────────┐    ║
║   │  READER  │ ─────────────────► │  FRE  (React widget · web frontend repo)         │    ║
║   └──────────┘                    │  dispatchFreEvents()                    │    ║
║                                   └──────────────┬──────────────────────────┘    ║
║                                                  │                               ║
║                          ┌───────────────────────▼───────────────────────────┐   ║
║                          │  Google Tag Manager (GTM)  ◄── [T] TRACKING       │   ║
║                          │  routes client-side events, no code deploy needed │   ║
║                          └───────────────────────┬───────────────────────────┘   ║
║                                                  │                               ║
║                          ┌───────────────────────▼───────────────────────────┐   ║
║                          │  GA4  (Google Analytics 4)  ◄── [T] TRACKING      │   ║
║                          │  assistant_session_start / _end                   │   ║
║                          │  assistant_query_submitted                        │   ║
║                          │  assistant_response_rendered (latency_ms, model)  │   ║
║                          │  assistant_article_impression / _click            │   ║
║                          │  assistant_followup_click                         │   ║
║                          │  assistant_error                                  │   ║
║                          └────────────── GA4 BigQuery Linking ───────────────┘   ║
║                                                  │ (native export, no ETL)       ║
║                          ┌───────────────────────▼───────────────────────────┐   ║
║                          │  BigQuery  (my-gcp-project.analytics.ai_assistant_     │   ║
║                          │            events)  ◄── [T] TRACKING warehouse    │   ║
║                          │  DAY-partitioned · 30–45 day rolling retention    │   ║
║                          └───────────────────────┬───────────────────────────┘   ║
║                                                  │                               ║
║                          ┌───────────────────────▼───────────────────────────┐   ║
║                          │  Looker dashboards  ◄── [T] TRACKING / reporting  │   ║
║                          │  Engagement · Content CTR · ROI · Cost per brand  │   ║
║                          └───────────────────────────────────────────────────┘   ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  BACKEND LAYER   (GCP / GKE)                                                     ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║   ┌─────────────────────────────────────────────────────────────────────────┐    ║
║   │  ai-assistant-service  (Python · FastAPI)                               │    ║
║   │                                                                         │    ║
║   │  POST /v1/assistant/chat      @datadog.timed('api.chat.post')     [M]   │    ║
║   │  GET  /v1/.../conversations   @datadog.timed('api.conversations.get')[M]│    ║
║   │  GET  /v1/.../conversation    @datadog.timed('api.conversation.get')[M] │    ║ 
║   │  DELETE /v1/.../conversation  @datadog.timed('api.conversation.delete')[M]   ║  
║   │                                                                         │    ║
║   │  Structured JSON logs → Datadog Log Management              [Lo]        │    ║
║   │  Unhandled exceptions → FastAPI Sentry integration          [E]         │    ║
║   │  ddtrace root span for every request                        [TR]        │    ║
║   │                                                                         │    ║
║   │  ┌───────────────────────────────────────────────────────────────────┐  │    ║
║   │  │  LangGraph  Agent  (StateGraph)                                   │  │    ║
║   │  │                                                                   │  │    ║
║   │  │  ┌─────────────────────────────────────────────────────────────┐  │  │    ║
║   │  │  │ load_context                                          [TR]  │  │  │    ║
║   │  │  │  • Valkey GET  personality:{site_id}  (300s TTL)            │  │  │    ║
║   │  │  │  • Valkey LRANGE  conv:{conversation_id}  (60m TTL)         │  │  │    ║
║   │  │  └─────────────────────────┬───────────────────────────────────┘  │  │    ║
║   │  │                            │                                      │  │    ║
║   │  │  ┌─────────────────────────▼───────────────────────────────────┐  │  │    ║
║   │  │  │ intent_router  (LLM classifier — claude-haiku)    [TR][L]   │  │  │    ║
║   │  │  │  span: langgraph.node.intent_router                         │  │  │    ║
║   │  │  │  tags: intent, site_id, tokens_in, tokens_out               │  │  │    ║
║   │  │  │  metric: ai_assistant.intent_classified  [M]                │  │  │    ║
║   │  │  └───────┬──────────────────────┬──────────────┬───────────────┘  │  │    ║
║   │  │          │                      │              │                  │  │    ║
║   │  │   content_question         small_talk      off_topic              │  │    ║
║   │  │          │                      │              │                  │  │    ║
║   │  │  ┌───────▼──────────┐    ┌──────▼───────┐  ┌───▼────────────┐     │  │    ║
║   │  │  │ search_concorde  │    │   generate_  │  │   guardrail_   │     │  │    ║
║   │  │  │  [TR][M]         │    │   response   │  │   response     │     │  │    ║
║   │  │  │                  │    │   [TR][L]    │  │   [TR]         │     │  │    ║
║   │  │  │ span:            │    │              │  │ (static reply  │     │  │    ║
║   │  │  │ tool_call.       │    │ span:        │  │  from Config-  │     │  │    ║
║   │  │  │ query_index      │    │ llm_invoke   │  │  DS)           │     │  │    ║
║   │  │  │                  │    │ model: sonnet│  │                │     │  │    ║
║   │  │  │ gauge:           │    │ tokens_in/   │  └───────┬────────┘     │  │    ║  
║   │  │  │ search_query_    │    │ tokens_out   │          │              │  │    ║
║   │  │  │ index_latency[M] │    └──────┬───────┘          │              │  │    ║
║   │  │  │                  │           │                  │              │  │    ║
║   │  │  │ (also optionally)│    ┌──────▼───────┐          │              │  │    ║
║   │  │  │ tool_call.       │    │ followup_    │          │              │  │    ║
║   │  │  │ get_related      │    │ suggestions  │          │              │  │    ║
║   │  │  │ gauge:           │    │ [TR][L]      │          │              │  │    ║
║   │  │  │ search_related_  │    │ haiku model  │          │              │  │    ║
║   │  │  │ latency [M]      │    └──────┬───────┘          │              │  │    ║
║   │  │  └───────┬──────────┘           │                  │              │  │    ║
║   │  │          │                      │                  │              │  │    ║
║   │  │  ┌───────▼──────────┐           │                  │              │  │    ║
║   │  │  │ guardrail_check  │           │                  │              │  │    ║
║   │  │  │ [TR][L][M]       │           │                  │              │  │    ║
║   │  │  │                  │           │                  │              │  │    ║
║   │  │  │ span: llm_invoke │           │                  │              │  │    ║
║   │  │  │ counter:         │           │                  │              │  │    ║
║   │  │  │ guardrail_       │           │                  │              │  │    ║
║   │  │  │ triggered [M]    │           │                  │              │  │    ║
║   │  │  │ types:           │           │                  │              │  │    ║
║   │  │  │ input_topic_block│           │                  │              │  │    ║
║   │  │  │ content_grounding│           │                  │              │  │    ║
║   │  │  │ language_pattern │           │                  │              │  │    ║
║   │  │  │ hallucination    │           │                  │              │  │    ║
║   │  │  └────────┬─────────┘           │                  │              │  │    ║
║   │  │           │safe                 │                  │              │  │    ║
║   │  │  ┌────────▼─────────────────────▼──────────────────▼───────────┐  │  │    ║
║   │  │  │ stream_output  →  FastAPI StreamingResponse        [TR]     │  │  │    ║
║   │  │  └─────────────────────────────────────────────────────────────┘  │  │    ║
║   │  │                                                                   │  │    ║
║   │  │  (async, after streaming)                                         │  │    ║
║   │  │  ┌─────────────────────────────────────────────────────────────┐  │  │    ║
║   │  │  │ persist_conversation  →  DynamoDB write (3 ops/turn)  [TR]  │  │  │    ║
║   │  │  │  ai_assistant_messages (×2) + ai_assistant_conversations×1  │  │  │    ║
║   │  │  └─────────────────────────────────────────────────────────────┘  │  │    ║
║   │  └───────────────────────────────────────────────────────────────────┘  │    ║
║   └─────────────────────────────────────────────────────────────────────────┘    ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  DEPENDENCY LAYER                                                                ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║  ┌───────────────────┐  ┌───────────────────┐  ┌──────────────┐  ┌───────────┐   ║
║  │  Valkey (cache)   │  │ DynamoDB (persist)│  │  ai-gateway  │  │ the Content Search API  │   ║
║  │  [TR] auto-instr. │  │ [TR] auto-instr.  │  │  (LiteLLM)   │  │ (search)  │   ║
║  │                   │  │                   │  │  [TR][L]     │  │ [TR][M]   │   ║
║  │ conv:{id}         │  │ ai_assistant_     │  │              │  │           │   ║
║  │ user:{id}:convlist│  │   messages        │  │ span:        │  │ query_    │   ║
║  │ personality:{id}  │  │ ai_assistant_     │  │ llm_invoke   │  │ index     │   ║
║  │                   │  │   conversations   │  │ tags: model, │  │ get_      │   ║
║  │ TTL: 60m / 300s   │  │ TTL: 90 days      │  │ tokens_in,   │  │ related   │   ║
║  └───────────────────┘  └───────────────────┘  │ tokens_out,  │  └───────────┘   ║
║                                                │ stop_reason  │                  ║
║  ┌───────────────────────────────────────────┐ └──────────────┘                  ║
║  │  Config-DS  (personality · per brand)     │                                   ║
║  │  [TR] auto-instr.                         │                                   ║
║  │  GET /merged?site_id=...                  │                                   ║
║  │  deep-merge: Client → Brand → Site        │                                   ║
║  └───────────────────────────────────────────┘                                   ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  OBSERVABILITY LAYER  (receives signals from all layers above)                   ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║  ┌─────────────────────────────────┐  ┌──────────────┐  ┌──────────────────────┐ ║
║  │  Datadog                 [M][TR]│  │  Sentry  [E] │  │  LangSmith      [L]  │ ║
║  │                                 │  │              │  │                      │ ║
║  │  DogStatsD metrics:             │  │ FastAPI      │  │ Full LangGraph run   │ ║
║  │   ai_assistant.query_received   │  │ integration  │  │ per-node state       │ ║
║  │   ai_assistant.response_latency │  │ (auto)       │  │ actual prompt text   │ ║
║  │   ai_assistant.llm_latency      │  │              │  │ actual LLM response  │ ║
║  │   ai_assistant.tool_call        │  │ Explicit:    │  │ token counts         │ ║
║  │   ai_assistant.guardrail_       │  │  ai-gateway  │  │ eval datasets        │ ║
║  │     triggered                   │  │  concorde    │  │                      │ ║
║  │   ai_assistant.error            │  │  dynamodb    │  │ LANGCHAIN_           │ ║
║  │                                 │  │  valkey      │  │ TRACING_V2=true      │ ║
║  │  ddtrace spans (APM):           │  │  config-ds   │  │                      │ ║
║  │   ai_assistant.llm_invoke       │  │              │  │ Complements Datadog  │ ║
║  │   tool_call.query_index         │  │ Paired with  │  │ Does NOT replace it  │ ║
║  │   tool_call.get_related         │  │ Datadog [M]  │  └──────────────────────┘ ║
║  │                                 │  │ counters     │                           ║
║  │  Default tags on every metric:  │  └──────────────┘                           ║
║  │   application · environment     │                                             ║
║  │   site_id · auth_state          │                                             ║
║  └─────────────────────────────────┘                                             ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```

---

### Diagram 2 — LangGraph Agent: Nodes × Observability Domains

> Each row is one LangGraph node. All five signal types — Logs, Metrics, Traces, LLM Signals, Errors — are covered for each node.
>
> **Log note:** `ddtrace` injects `trace_id` and `span_id` into every log line automatically, so Datadog can link a log entry directly to the span it came from. This means you can click a slow span in the APM flame graph and jump straight to the log lines that fired inside it.

| Node | [Lo] Log (Datadog) | [TR] Trace Span | [M] Metric | [L] LLM Signal | [E] Error |
|------|-------------------|-----------------|-----------|----------------|-----------|
| **load_context** | `node=load_context` · `cache_hit=true\|false` · `site_id` · `conversation_id` | `langgraph.node.load_context` · Valkey GET/LRANGE auto-instrumented | — | — | Sentry if Valkey or Config-DS unreachable |
| **intent_router** | `node=intent_router` · `intent=...` · `site_id` · `latency_ms` | `langgraph.node.intent_router` · `ai_assistant.llm_invoke` | `ai_assistant.intent_classified` tagged `intent`, `site_id` | model=`claude-haiku` · tokens_in/out · intent=`small_talk` \| `content_question` \| `off_topic` | Sentry + `ai_assistant.error` (`error_source:ai-gateway`) on LLM timeout |
| **search_concorde** (query_index) | `node=search_concorde` · `result_count=N` · `site_id` · `latency_ms` | `ai_assistant.tool_call.query_index` | `ai_assistant.tool_call` (`tool:query_index`) · `ai_assistant.search_query_index_latency` (ms) | — | Sentry + `ai_assistant.error` (`error_source:concorde`) |
| **get_related** (CDN) | `node=get_related` · `result_count=N` · `page_url` · `latency_ms` | `ai_assistant.tool_call.get_related` | `ai_assistant.tool_call` (`tool:get_related`) · `ai_assistant.search_related_latency` (ms) | — | Sentry + `ai_assistant.error` on CDN failure |
| **guardrail_check** | `node=guardrail_check` · `result=safe\|unsafe` · `guardrail_type=...` · `site_id` | `ai_assistant.llm_invoke` | `ai_assistant.guardrail_triggered` tagged by type: `input_topic_block` · `content_grounding_fail` · `language_pattern_match` · `hallucination_detected` | model=`claude-haiku` · `guardrail_result`=safe\|unsafe · tokens_in/out | Sentry + `ai_assistant.error` (`error_source:ai-gateway`) |
| **generate_response** (main LLM) | `node=generate_response` · `model=...` · `tokens_in=N` · `tokens_out=N` · `stop_reason=...` | `ai_assistant.llm_invoke` | `ai_assistant.llm_latency` (ms) | model=`claude-sonnet` · tokens_in/out · stop_reason · `call_type:main_response` | Sentry + `ai_assistant.error` (`error_source:ai-gateway`) |
| **followup_suggestions** | `node=followup_suggestions` · `suggestions_count=N` · `latency_ms` | `ai_assistant.llm_invoke` | — | model=`claude-haiku` · tokens_in/out · `call_type:followup` | Sentry + `ai_assistant.error` (`error_source:ai-gateway`) |
| **persist_conversation** *(async)* | `node=persist_conversation` · `writes=3` · `conversation_id` · `message_count` | `dynamodb.write` auto-instrumented (×3 ops per turn) | — | — | Sentry + `ai_assistant.error` (`error_source:dynamodb`) |
| **stream_output** | `node=stream_output` · `response_latency_ms=N` · `conversation_id` | Root span closes here — end-to-end latency captured | `ai_assistant.response_latency` (ms) | — | — |


---

### Diagram 3 — Signal Flow: one chat turn, end to end

> Follows a single `POST /v1/assistant/chat` from browser to data stores, showing every signal emitted.

```
 BROWSER                   BACKEND                        OBSERVABILITY DESTINATION
 ─────────────────────────────────────────────────────────────────────────────────
 User sends message
       │
       │ HTTP POST /v1/assistant/chat
       ▼
                           FastAPI receives request
                           ├─ [TR] ddtrace root span opens          → Datadog APM
                           ├─ [M]  query_received counter +1        → Datadog
                           ├─ [M]  @timed('api.chat.post') starts   → Datadog
                           │
                           ├─ load_context
                           │   ├─ [TR] Valkey GET personality        → Datadog APM
                           │   └─ [TR] Valkey LRANGE conv history    → Datadog APM
                           │
                           ├─ intent_router  (haiku LLM)
                           │   ├─ [TR] llm_invoke span               → Datadog APM
                           │   ├─ [L]  tokens_in/out tagged on span  → Datadog APM
                           │   ├─ [L]  full prompt + response        → LangSmith
                           │   └─ [M]  intent_classified counter     → Datadog
                           │
                           ├─ search_concorde
                           │   ├─ [TR] tool_call.query_index span    → Datadog APM
                           │   └─ [M]  search_query_index_latency    → Datadog
                           │
                           ├─ guardrail_check  (haiku LLM)
                           │   ├─ [TR] llm_invoke span               → Datadog APM
                           │   ├─ [L]  guardrail_result=safe         → Datadog APM
                           │   ├─ [L]  full prompt + response        → LangSmith
                           │   └─ [M]  (no counter if safe)
                           │
                           ├─ generate_response  (sonnet LLM)
                           │   ├─ [TR] llm_invoke span               → Datadog APM
                           │   ├─ [L]  tokens_in/out, model          → Datadog APM
                           │   ├─ [L]  full prompt + response        → LangSmith
                           │   └─ [M]  llm_latency gauge             → Datadog
                           │
                           ├─ followup_suggestions  (haiku LLM)
                           │   ├─ [TR] llm_invoke span               → Datadog APM
                           │   └─ [L]  full prompt + response        → LangSmith
                           │
                           ├─ stream_output  →  response sent to FRE
                           │   └─ [M]  response_latency gauge closes → Datadog
                           │
                           └─ persist_conversation  (async)
                               └─ [TR] DynamoDB write spans (×3)     → Datadog APM

 FRE receives response and renders it
       │
       ├─ [T] assistant_response_rendered → GTM → GA4 → BigQuery
       │       (latency_ms, article_count, model_used)
       │
       └─ [T] assistant_article_impression (×N) → GTM → GA4 → BigQuery
               (article_url, position)

 User clicks article
       │
       └─ [T] assistant_article_click → GTM → GA4 → BigQuery
               (article_url, position, time_to_click_ms)

 ─────────────────────────────────────────────────────────────────────────────────
 If anything throws an exception at any backend step:
       ├─ [E] Sentry captures stack trace + request context    → Sentry dashboard
       └─ [M] ai_assistant.error counter +1 (error_source tag) → Datadog alert
```

---

## 2. What Is Observability?

Observability means being able to answer "what is my system doing right now — and why?" just by looking at the data it produces, without having to guess or add new code every time something breaks.

It is different from simple monitoring. Monitoring tells you *when* something is wrong (an alert fires). Observability lets you *understand why* — by giving you the data to investigate.

For an LLM-powered application like the AI Assistant, observability covers three distinct concerns:


| Concern               | Question it answers                            | Tools                         |
| --------------------- | ---------------------------------------------- | ----------------------------- |
| **Tracking**          | Are people using the product?                  | GA4 · GTM · BigQuery · Looker |
| **Monitoring / APM**  | Is the backend healthy? Where is it slow?      | Datadog                       |
| **LLM observability** | What is the agent actually doing with prompts? | LangSmith                     |


All three concerns are active at the same time. You need all three to have full visibility.

---

## 3. The Four Signals: Logs, Metrics, Traces, LLM Signals

Every observability system is built from four types of data. Here is what each one is and what question it answers.

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│    LOGS      │  │   METRICS    │  │   TRACES     │  │ LLM SIGNALS  │
│              │  │              │  │              │  │              │
│ What         │  │ How much /   │  │ Where did    │  │ What did     │
│ happened     │  │ how fast     │  │ time go      │  │ the model    │
│ (events)     │  │              │  │ (path)       │  │ do / cost    │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

### Logs

A log is a timestamped record of something that happened. In 2026, logs should be structured JSON — not plain text — so you can search and filter them later.

```json
{
  "timestamp": "2026-05-25T19:04:23Z",
  "level": "ERROR",
  "service": "ai-assistant-service",
  "site_id": "cosmopolitan_uk",
  "conversation_id": "conv_abc123",
  "event": "llm_timeout",
  "latency_ms": 30041,
  "model": "claude-sonnet-4-6"
}
```

With structured logs you can query: "show me all LLM timeouts for Cosmopolitan UK in the last hour." With plain-text logs you cannot.

### Metrics

A metric is a number measured over time. Three types:

- **Counter** — only goes up (total requests, total errors)
- **Gauge** — current value at a point in time (latency in ms, queue depth)
- **Histogram** — distribution of values (lets you compute p50, p95, p99 latency)

Metrics are cheap to store and fast to query. They're what powers dashboards and alerts.

### Traces and Spans

A **span** is one unit of work with a start time and end time.

```
"I called the Content Search API. It started at 14:05:00.000, ended at 14:05:00.180. It returned 5 results."
→ That's a span.
```

A **trace** is the full tree of spans for a single request, all linked by the same `trace_id`. It shows you the complete path a request took and exactly where time was spent.

```
POST /v1/assistant/chat  [450 ms total]   ← root span (the full trace)
  ├── load_context          12 ms         ← child span
  ├── intent_router         95 ms         ← child span  (LLM call inside)
  ├── search_concorde      180 ms         ← child span  ← this is the bottleneck
  ├── guardrail_check       78 ms         ← child span
  └── followup_suggestions  62 ms         ← child span
```

You look at a trace when someone says "the chatbot was slow" — the trace immediately shows you which step was slow (the Content Search API, 180 ms) rather than you having to guess.

### LLM Signals

Traditional monitoring tools like Datadog were built before LLMs existed. They are great at measuring latency and error rates, but they don't understand what a prompt is, what a completion is, or whether an answer was actually correct.

LLM signals are the data specific to AI calls:


| Signal                        | Why it matters                                               |
| ----------------------------- | ------------------------------------------------------------ |
| `tokens_in` / `tokens_out`    | Primary cost driver — what you pay for                       |
| `model_id`                    | Which model was used (cost and capability differ)            |
| `stop_reason`                 | Was the response cut off (`max_tokens`) or finished cleanly? |
| `guardrail_result`            | Did the safety check pass or fail?                           |
| `prompt_template_version`     | If you change a prompt, did answers get better or worse?     |
| Full prompt + completion text | Needed to actually read and evaluate what the model said     |


The last one — full prompt and completion text — is what LangSmith provides and Datadog intentionally does not (because prompts may contain user PII).

### Why you need all four


| Something goes wrong...           | Which signal finds it                       |
| --------------------------------- | ------------------------------------------- |
| "The service is slow"             | Metrics — latency gauge is high             |
| "Which request is slow?"          | Traces — find the long span                 |
| "What happened in that request?"  | Logs — read the structured events           |
| "The LLM is giving wrong answers" | LLM signals — read the prompts in LangSmith |


---

## 4. Tags — How You Filter Everything

A tag is a **key=value label** you attach to a metric, span, or log so you can filter and group it later.

Without tags, a counter like `ai_assistant.error` is just a number. With tags it becomes something you can slice:

```
ai_assistant.error  +1   error_source:concorde   site_id:cosmopolitan_uk   environment:production
ai_assistant.error  +1   error_source:dynamodb   site_id:brand_alpha_us        environment:production
```

Now in Datadog you can ask: "show me only the Content Search API errors for Cosmopolitan UK in production." Without tags, all errors look the same.

### Default tags in the Assistant

The following four tags are applied automatically to every single Datadog metric and span:


| Tag           | Example values                  | Why                             |
| ------------- | ------------------------------- | ------------------------------- |
| `application` | `ai_assistant`                  | Identifies the service          |
| `environment` | `production`, `staging`         | Separates prod from test data   |
| `site_id`     | `cosmopolitan_uk`, `brand_alpha_us` | Breaks down metrics per brand   |
| `auth_state`  | `signed_in`, `anonymous`        | Segments readers by login state |


The rule is: tag everything consistently. The same tag values should appear in Datadog metrics, ddtrace spans, Sentry scope, and BigQuery events. Without that consistency, you cannot correlate data across tools.

---

## 5. The Chosen Toolset

The Assistant Phase 2 uses three observability tools in combination. Each covers a different part of the picture.

```
┌──────────────────────────────────────────────────────────────────────┐
│                     PHASE 2 OBSERVABILITY STACK                      │
├──────────────────┬───────────────────────┬───────────────────────────┤
│    TRACKING      │    BACKEND HEALTH     │    LLM VISIBILITY         │
│                  │                       │                           │
│  GA4 + GTM       │  Datadog APM          │  LangSmith                │
│  BigQuery        │  DogStatsD metrics    │                           │
│  Looker          │  ddtrace spans        │  Full graph run traces    │
│                  │  Sentry (errors)      │  Actual prompt content    │
│  "Are users      │                       │  LLM response text        │
│   using it?"     │  "Is it working?"     │  Eval + regression        │
└──────────────────┴───────────────────────┴───────────────────────────┘
```

### Datadog

Datadog is the main backend observability platform. It handles metrics (counters and gauges via DogStatsD), distributed traces (via `ddtrace`), and log management. It powers alerts, SLO dashboards, and the on-call workflow.

**What Datadog sees:** request counts, latency, error rates, token counts (as tagged numbers), which LangGraph tools fired and how long they took.

**What Datadog does NOT see:** the actual text of prompts or LLM responses. This is intentional — prompts may contain user queries (PII), and Datadog is not the right place for that.

### LangSmith

LangSmith is LangChain's purpose-built observability platform for LangGraph. It understands the graph structure natively and captures the full execution of every agent run: which nodes fired, in what order, what the state looked like at each step, and the full text of every LLM prompt and response.

**What LangSmith sees:** the complete agent graph run as a tree, every node's input and output state, every LLM prompt + completion, token counts, latency per node, which branch the router took.

**What LangSmith does NOT do:** alerting, infrastructure metrics, on-call pages. It is a debugging and evaluation tool, not an operations tool.

**Integration:** two environment variables — no code changes to LangGraph are needed.

```python
# Set these at service startup — LangGraph does the rest automatically
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "..."
os.environ["LANGCHAIN_PROJECT"] = "ai-assistant-prod"
```

### Do Datadog and LangSmith integrate with each other?

No — they do not send data to each other. They are two separate destinations:

- Every LLM call → **both** get data simultaneously
- Datadog gets: latency numbers, token count numbers, error counters — everything as metrics/spans
- LangSmith gets: the full text, the full state tree, the full graph run

You use them for different questions:


| Question                                                                 | Tool                      |
| ------------------------------------------------------------------------ | ------------------------- |
| "Is LLM latency degrading over time?"                                    | Datadog                   |
| "Which call type is slowest — classifier vs main response vs guardrail?" | Datadog (span tags)       |
| "Why did the model give a bad answer on this specific conversation?"     | LangSmith                 |
| "Did changing the system prompt make answers better or worse?"           | LangSmith (eval datasets) |
| "How much did this brand spend on tokens this week?"                     | Datadog (token gauges)    |


### Sentry

Sentry captures the full exception context when something crashes: stack trace, the HTTP request that triggered it, local variables. Every Sentry capture is paired with a Datadog error counter — Datadog tells you *how often* something broke, Sentry tells you *exactly what broke*.

---

## 6. Tracking — What Are Users Doing?

Tracking answers **"Are people using the product?"** It is entirely client-side — it captures what the user does in the browser before or alongside any backend call.

### The event pipeline

```
User action in the widget
        │
        ▼
FRE  ──dispatchFreEvents()──►  GTM (Google Tag Manager)
                                        │
                                        ▼
                                   GA4 (Google Analytics 4)
                                        │
                               GA4 BigQuery Linking (native export)
                                        │
                                        ▼
                                   BigQuery  ──►  Looker dashboards
```

**FRE** is the React widget embedded on publisher pages. Every interaction fires a structured event through `dispatchFreEvents()`.

**GTM** is the tag manager sitting between FRE and GA4. It means analytics teams can change what events go where without touching the widget code. FRE fires once into GTM's data layer; GTM decides the destinations.

**GA4 → BigQuery** happens automatically via the GA4 BigQuery Linking feature — no custom pipeline is needed.

### GA4 event schema

All events are fired from `<AiAssistant />` in the web frontend via `dispatchFreEvents()`:


| Event                          | Trigger                      | Key properties                                                                               |
| ------------------------------ | ---------------------------- | -------------------------------------------------------------------------------------------- |
| `assistant_session_start`      | Panel opens                  | `session_id`, `user_id`, `auth_state`, `brand`, `page_url`, `device_type`, `referral_source` |
| `assistant_session_end`        | Panel closes / navigate away | `session_id`, `duration`, `message_count`, `articles_clicked`                                |
| `assistant_query_submitted`    | Every message sent           | `session_id`, `query_text`, `query_source`, `is_followup`, `intent_classification`           |
| `assistant_response_rendered`  | AI response displayed        | `session_id`, `response_type`, `article_count`, `latency_ms`, `model_used`                   |
| `assistant_article_impression` | Article card shown           | `session_id`, `article_url`, `position`                                                      |
| `assistant_article_click`      | Article card clicked         | `session_id`, `article_url`, `position`, `time_to_click_ms`                                  |
| `assistant_followup_click`     | Follow-up question clicked   | `session_id`, `article_url`, `position`, `time_to_click_ms`                                  |
| `assistant_history_accessed`   | History panel opens          | `session_id`, `conversations_shown`                                                          |
| `assistant_error`              | Frontend error               | `session_id`, `error_type`, `error_message`, `recovery_action`                               |


### Important: trust the backend for sensitive fields

Fields like `intent_classification`, `latency_ms`, `model_used`, and `guardrail_triggered` should come from the **backend**, not be filled in by the browser. A browser can be manipulated; the backend cannot. These values should be emitted server-side and either dual-written to the analytics pipeline or used to enrich the client event on arrival.

### Example queries

**Widget adoption rate per brand:**

```sql
SELECT
  brand,
  COUNT(DISTINCT user_id) AS widget_users,
  COUNT(DISTINCT CASE WHEN event_type = 'assistant_query_submitted' THEN user_id END) AS engaged_users,
  ROUND(
    100 * COUNT(DISTINCT CASE WHEN event_type = 'assistant_query_submitted' THEN user_id END)
        / COUNT(DISTINCT user_id), 1
  ) AS engagement_rate_pct
FROM `my-gcp-project.analytics.ai_assistant_events`
WHERE DATE(event_timestamp) = CURRENT_DATE()
GROUP BY brand
ORDER BY engaged_users DESC;
```

**Article click-through rate:**

```sql
SELECT
  JSON_EXTRACT_SCALAR(event_payload, '$.article_url') AS article_url,
  COUNT(CASE WHEN event_type = 'assistant_article_impression' THEN 1 END) AS impressions,
  COUNT(CASE WHEN event_type = 'assistant_article_click' THEN 1 END) AS clicks,
  ROUND(100 * COUNT(CASE WHEN event_type = 'assistant_article_click' THEN 1 END)
            / NULLIF(COUNT(CASE WHEN event_type = 'assistant_article_impression' THEN 1 END), 0), 2) AS ctr_pct
FROM `my-gcp-project.analytics.ai_assistant_events`
WHERE DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY article_url
ORDER BY clicks DESC
LIMIT 20;
```

---

## 7. Monitoring — Is the Service Healthy?

Monitoring answers **"Is it working?"** It is metric-driven: you define numeric thresholds and get notified when they are crossed.

### SLOs, SLIs, and SLAs

Before setting up alerts, you need to know what "healthy" means. The standard model:

- **SLI** (Service Level Indicator) — the metric you actually measure (e.g. error rate, p99 latency)
- **SLO** (Service Level Objective) — the target for that metric (e.g. error rate < 1%, p99 < 5 s)
- **SLA** (Service Level Agreement) — a contractual commitment to an external party
- **Error budget** — the allowed amount of SLO violation before you have a problem

```
Error budget = 1 − SLO target
SLO = 99.9%  →  error budget = 0.1%  =  ~43 minutes of downtime per month
```

When you burn through the error budget faster than expected, you freeze deployments and investigate.

### Key metrics for an LLM API


| Metric         | What to measure                     | Why                       |
| -------------- | ----------------------------------- | ------------------------- |
| Availability   | HTTP 5xx error rate                 | Is the service reachable? |
| Latency        | p50, p95, p99 end-to-end            | User experience           |
| LLM latency    | Round-trip to ai-gateway            | Where is time spent?      |
| Cache hit rate | Valkey hit/miss ratio               | Is the cache working?     |
| Guardrail rate | Fraction of responses filtered      | Safety signal             |
| Token cost     | Tokens in + out per conversation    | Budget control            |
| Tool call rate | How often each LangGraph tool fires | Agent behaviour health    |


### Datadog metric schema

`ai-assistant-service` emits metrics via DogStatsD using three primitives:

- `ping()` — increments a counter
- `gauge()` — records a value at a point in time
- `timed()` — decorator that measures route handler duration

**Counters and gauges:**


| Metric                                    | Type       | Description                                                                                                |
| ----------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------- |
| `ai_assistant.query_received`             | counter    | Every POST `/v1/assistant/chat`                                                                            |
| `ai_assistant.conversation_started`       | counter    | First message in a new thread                                                                              |
| `ai_assistant.conversation_deleted`       | counter    | DELETE conversation endpoint                                                                               |
| `ai_assistant.response_latency`           | gauge (ms) | End-to-end backend latency                                                                                 |
| `ai_assistant.llm_latency`                | gauge (ms) | Round-trip to ai-gateway                                                                                   |
| `ai_assistant.tool_call`                  | counter    | Each LangGraph tool invocation (tagged by tool name)                                                       |
| `ai_assistant.search_query_index_latency` | gauge (ms) | the Content Search API `query_index` duration                                                                            |
| `ai_assistant.search_related_latency`     | gauge (ms) | CDN `get_related` duration                                                                                 |
| `ai_assistant.guardrail_triggered`        | counter    | By type: `input_topic_block`, `content_grounding_fail`, `language_pattern_match`, `hallucination_detected` |
| `ai_assistant.error`                      | counter    | Unhandled exceptions; `error_source` tag: `ai-gateway`, `concorde`, `dynamodb`, `valkey`, `config_ds`      |


**Endpoint timing via decorator:**

```python
@datadog.timed('api.chat.post')
async def post_chat(request: ChatRequest) -> ChatResponse:
    ...

@datadog.timed('api.conversations.get')
async def get_conversations(user_id: str) -> ConversationListResponse:
    ...
```

This automatically tracks p50/p95/p99 for each route without any additional code.

**Example alerts:**

```
# Error rate SLO
Monitor: ai_assistant.error > 5 over last 5 minutes
  AND environment:production
Alert: PagerDuty + Slack #ai-assistant-alerts  →  P2

# LLM latency degradation
Monitor: avg:ai_assistant.llm_latency{environment:production} > 5000
Evaluation window: 10 minutes
Alert: Slack #ai-assistant-alerts  →  P3
```

---

## 8. APM — Where Did the Time Go?

APM (Application Performance Monitoring) shows you the complete path of a single request across all services and dependencies, with timing for every step. This is the trace view described in Section 3.

### What APM gives you

- A flame graph of every request — you can see exactly where time was spent
- Which dependency (Valkey, DynamoDB, the Content Search API, ai-gateway) is the bottleneck
- Which span threw an exception
- Jump from a Datadog metric spike → the individual slow traces → the log lines for those traces

### How ddtrace works

`ddtrace` is Datadog's Python APM library. It automatically instruments FastAPI, Valkey/Redis, DynamoDB clients, and outbound HTTP without any code changes. For LangGraph nodes, you add spans manually:

```python
from ddtrace import tracer

with tracer.trace("ai_assistant.llm_invoke") as span:
    span.set_tag("call_type", "main_response")
    span.set_tag("model", "claude-sonnet-4-6")
    span.set_tag("site_id", state.site_id)
    span.set_tag("intent", state.intent)

    response = await ai_gateway.invoke(messages)

    span.set_tag("tokens_in", response.usage.input_tokens)
    span.set_tag("tokens_out", response.usage.output_tokens)
    span.set_tag("stop_reason", response.stop_reason)
```

### ddtrace span catalog


| Span name                            | Fires when                     | Key tags                                                                            |
| ------------------------------------ | ------------------------------ | ----------------------------------------------------------------------------------- |
| `ai_assistant.llm_invoke`            | Any LiteLLM call to ai-gateway | `call_type`, `model`, `site_id`, `intent`, `tokens_in`, `tokens_out`, `stop_reason` |
| `ai_assistant.tool_call.query_index` | the Content Search API semantic search       | `site_id`, `result_count`                                                           |
| `ai_assistant.tool_call.get_related` | CDN related-content lookup     | `page_url`, `result_count`                                                          |


### A complete trace for one chat turn

```
POST /v1/assistant/chat  [450 ms]  trace_id=abc123
  │
  ├── load_context  [12 ms]
  │     ├── valkey.GET personality:{site_id}  [2 ms]   HIT
  │     └── valkey.LRANGE conv:{conversation_id}  [3 ms]
  │
  ├── intent_router  [95 ms]
  │     └── ai_assistant.llm_invoke  [91 ms]
  │           call_type=classifier  model=claude-haiku  intent=content_question
  │
  ├── ai_assistant.tool_call.query_index  [180 ms]   ← bottleneck
  │     result_count=5
  │
  ├── guardrail_check  [78 ms]
  │     └── ai_assistant.llm_invoke  [74 ms]
  │           call_type=guardrail  guardrail_result=safe
  │
  ├── followup_suggestions  [62 ms]
  │     └── ai_assistant.llm_invoke  [59 ms]
  │           call_type=followup
  │
  └── dynamodb.write  [23 ms]
        tables=ai_assistant_messages, ai_assistant_conversations
```

From this trace it is immediately clear that the Content Search API (180 ms) is the dominant cost — not the LLM calls.

---

## 9. Error Tracking — What Broke and Why?

Error tracking is different from monitoring. Monitoring tells you *that* errors are happening (a counter spiked). Error tracking captures the full context of *what* happened so engineers can fix it.

### Sentry

Sentry captures every exception with: full stack trace, the HTTP request that triggered it, request body, user/session context, and tags. It integrates natively with FastAPI so unhandled exceptions are captured automatically with zero instrumentation.

### The Datadog + Sentry pairing

> Every Sentry capture is paired with a corresponding Datadog counter. Datadog drives alerting. Sentry carries the debug detail.

This is the pattern used throughout the Assistant. Without Sentry you have an alert but no way to debug. Without Datadog you have debug detail but no alert.

```python
except ConcordeTimeoutError as e:
    # 1. Alert signal → Datadog counter fires → alert if threshold crossed
    datadog.ping("ai_assistant.error", tags=["error_source:concorde"])

    # 2. Debug detail → Sentry captures the full stack trace + request body
    sentry_sdk.capture_exception(e)

    # 3. Fallback → user gets a safe response
    return fallback_response()
```

**Captured automatically** via the FastAPI Sentry integration: any unhandled exception in a route handler.

**Captured explicitly** at the point of failure:

- ai-gateway errors and throttling
- the Content Search API call failures
- DynamoDB write failures
- Valkey connection failures
- Config-DS failures

**Sentry initialisation (follows the Content Search API's pattern):**

```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
import os

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),      # absent locally → Sentry disabled
    environment=os.environ.get("ENVIRONMENT", "development"),
    release=os.environ.get("GIT_SHA"),
    integrations=[FastApiIntegration()],
    traces_sample_rate=0.1,
)
```

---

## 10. AI Assistant Phase 2 — Agentic Observability

This section is specific to the Assistant's LangGraph architecture. It covers what is different about observing an agent versus a normal API, and how Datadog and LangSmith divide the work.

### Why agentic observability is different

A normal API always takes the same path:

```
Request → handler → database → response
(same every time)
```

A LangGraph agent takes a different path every time depending on the request:

```
Request → load_context → intent_router
                              │
                   ┌──────────┼──────────┐
             content_question small_talk off_topic
                   │              │          │
            search_concorde  generate    guardrail
                   │         response    response
            guardrail_check
                   │
            generate_response
                   │
            followup_suggestions
```

This means you cannot just monitor the endpoint — you need to know **which nodes fired**, **in what order**, **how long each took**, and **what the agent "knew" at each step**.

### What Datadog handles vs what LangSmith handles

They do not integrate with each other — signals go to two separate destinations. Each is built for a different purpose.


| Question                                                              | Tool                                                  |
| --------------------------------------------------------------------- | ----------------------------------------------------- |
| Is LLM latency degrading over time?                                   | **Datadog** (gauge trending)                          |
| Which call type is slowest — classifier, main response, or guardrail? | **Datadog** (span tags: `call_type`)                  |
| How much did each brand spend on tokens this week?                    | **Datadog** (token gauges by `site_id`)               |
| How often does the guardrail fire, and for which brand?               | **Datadog** (counter by `guardrail_type` + `site_id`) |
| Why did the agent give a wrong answer on conversation X?              | **LangSmith** (read the actual prompts)               |
| Did changing the system prompt make answers better or worse?          | **LangSmith** (eval datasets + regression)            |
| Which branch did the router take on this run?                         | **LangSmith** (full graph run tree)                   |
| What was the agent's state when it called the Content Search API?                   | **LangSmith** (per-node state snapshots)              |


### Datadog integration pattern for LangGraph nodes

Each LangGraph node gets a `ddtrace` span manually. This makes the node appear as a named span in the Datadog APM flame graph:

```python
from ddtrace import tracer

async def intent_router(state: AgentState) -> AgentState:
    with tracer.trace("langgraph.node.intent_router") as span:
        span.set_tag("site_id", state.site_id)
        span.set_tag("session_id", state.session_id)

        intent = await classify_intent(state)

        span.set_tag("intent", intent)
        datadog.ping("ai_assistant.intent_classified",
                     tags=[f"intent:{intent}", f"site_id:{state.site_id}"])
        return {**state, "intent": intent}

async def search_concorde(state: AgentState) -> AgentState:
    with tracer.trace("ai_assistant.tool_call.query_index") as span:
        span.set_tag("site_id", state.site_id)
        start = time.monotonic()

        results = await concorde.query_index(state.user_message, state.site_id)

        latency_ms = int((time.monotonic() - start) * 1000)
        span.set_tag("result_count", len(results))
        datadog.gauge("ai_assistant.search_query_index_latency", latency_ms,
                      tags=[f"site_id:{state.site_id}"])
        datadog.ping("ai_assistant.tool_call",
                     tags=["tool:query_index", f"site_id:{state.site_id}"])
        return {**state, "articles": results}
```

### LangSmith integration

LangGraph emits traces to LangSmith automatically — no code changes to the graph are needed:

```python
import os

# Set these at service startup
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "..."
os.environ["LANGCHAIN_PROJECT"] = "ai-assistant-prod"

# Nothing else needed — the graph emits automatically
graph = builder.compile()
```

LangSmith then lets you:

- Search all runs by `session_id`, `site_id`, intent, or date
- Click into any run and see the full tree: which nodes fired, input/output state at each node
- Read the exact prompt sent to the LLM and the exact response received
- Build evaluation datasets from production traces
- Run regression tests automatically when you change a prompt

### The four LLM calls per turn

Each chat turn invokes the ai-gateway (LiteLLM) **up to four times**, each with a different purpose and cost profile. It is important to monitor them separately because they have very different latency and cost characteristics:

```
Turn n
  │
  ├── [1] Input classifier  (claude-haiku)     ~50 ms    cheap
  │       Checks message against input_filter_topics
  │       If triggered → short-circuit, no further calls
  │
  ├── [2] Main LLM response  (claude-sonnet)   ~300 ms   expensive
  │       Generates the actual answer
  │
  ├── [3] Follow-up suggestions  (claude-haiku) ~100 ms  cheap
  │       Generates follow-up questions and topic labels
  │
  └── [4] Output guardrail check  (claude-haiku) ~80 ms  cheap
          Checks: content_grounding, blocked_language, hallucination
          If fail → [5] single retry → if still fail → safe fallback
```

The main response (call 2) dominates cost. The classifier (call 1) determines whether the expensive calls happen at all. Monitor them separately with `call_type` tags:

```python
with tracer.trace("ai_assistant.llm_invoke") as span:
    span.set_tag("call_type", "main_response")   # or: classifier, guardrail, followup
    span.set_tag("model", "claude-sonnet-4-6")
    span.set_tag("site_id", state.site_id)

    response = await ai_gateway.invoke(messages)

    span.set_tag("tokens_in", response.usage.input_tokens)
    span.set_tag("tokens_out", response.usage.output_tokens)
    span.set_tag("stop_reason", response.stop_reason)

    datadog.gauge("ai_assistant.tokens_in", response.usage.input_tokens,
                  tags=[f"call_type:main_response", f"site_id:{state.site_id}"])
    datadog.gauge("ai_assistant.tokens_out", response.usage.output_tokens,
                  tags=[f"call_type:main_response", f"site_id:{state.site_id}"])
```

### Guardrail observability

Guardrails are unique to LLM apps — a guardrail failure returns HTTP 200 (not an error) but shows the user a fallback message. Traditional monitoring would never catch this. You need explicit counters:

```
ai_assistant.guardrail_triggered  (Datadog counter)
  tags:
    guardrail_type: input_topic_block      ← input filter fired
    guardrail_type: content_grounding_fail ← response not grounded in MediaCo content
    guardrail_type: language_pattern_match ← blocked language detected
    guardrail_type: hallucination_detected ← unverified claim about a person/product
    site_id: {brand}
```

What the guardrail rates tell you:

- High `input_topic_block` for a brand → `input_filter_topics` in Config-DS is too broad, blocking real questions
- High `content_grounding_fail` → the LLM is going off-topic, not citing MediaCo articles
- High `hallucination_detected` → model drift or prompt quality issue

A guardrail event also fires from the **frontend** (`assistant_guardrail_triggered` in GA4) when the user sees the filtered response. This lets you correlate backend detection with actual user impact.

### Intent distribution monitoring

Knowing which intent the router classifies is important for understanding what users actually want:

```sql
-- BigQuery: intent distribution over the last 7 days
SELECT
  JSON_EXTRACT_SCALAR(event_payload, '$.intent_classification') AS intent,
  brand,
  COUNT(*) AS query_count,
  ROUND(AVG(CAST(JSON_EXTRACT_SCALAR(event_payload, '$.latency_ms') AS INT64)), 0) AS avg_latency_ms
FROM `my-gcp-project.analytics.ai_assistant_events`
WHERE event_type = 'assistant_query_submitted'
  AND DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY intent, brand
ORDER BY query_count DESC;
```

If `off_topic` spikes for a particular brand, the `system_prompt` or `content_domains` in Config-DS for that brand needs adjustment.

### Cache (Valkey) observability

The Assistant uses three Valkey caches:


| Cache key                 | TTL            | What to watch                                            |
| ------------------------- | -------------- | -------------------------------------------------------- |
| `conv:{conversation_id}`  | 60 min sliding | Hit rate — a miss means a DynamoDB fallback (slower)     |
| `user:{user_id}:convlist` | 60 min         | Hit rate — invalidated on every chat turn                |
| `personality:{site_id}`   | 300 sec        | Hit rate — a miss adds a Config-DS call to every request |


A cold cache after a deployment will temporarily spike p99 latency. Track this in Datadog so you can distinguish a deployment-caused degradation from an organic incident.

### DynamoDB write observability

Each chat turn causes 3 DynamoDB writes:

- 2 rows in `ai_assistant_messages` (user message + assistant response)
- 1 update to `ai_assistant_conversations`

At projected full-rollout load (~0.22 req/s peak), that is ~0.66 writes/s peak. Monitor write latency and throttling events — not raw throughput, which is low.

### Complete signal inventory


| Component                     | Tool                | Signal                    | What it captures                       |
| ----------------------------- | ------------------- | ------------------------- | -------------------------------------- |
| FRE (frontend widget)         | GA4 via GTM         | Events                    | Opens, queries, article clicks, errors |
| `POST /v1/assistant/chat`     | Datadog `@timed`    | Gauge                     | End-to-end route latency               |
| `GET /v1/.../conversations`   | Datadog `@timed`    | Gauge                     | Conversation list latency              |
| `GET /v1/.../conversation`    | Datadog `@timed`    | Gauge                     | Thread fetch latency                   |
| `DELETE /v1/.../conversation` | Datadog `@timed`    | Gauge                     | Delete latency                         |
| LangGraph — intent_router     | Datadog + LangSmith | Span + counter + full run | Intent, LLM latency, prompt content    |
| LangGraph — search_concorde   | Datadog             | Span + gauge              | the Content Search API latency, result count         |
| LangGraph — guardrail_check   | Datadog + LangSmith | Counter + full run        | Guardrail type, pass/fail, prompt      |
| LangGraph — llm_invoke (all)  | Datadog + LangSmith | Span + gauge + full run   | Latency, tokens, model, prompt text    |
| Valkey                        | Datadog (auto)      | Span                      | GET/SET latency, hit/miss              |
| DynamoDB writes               | Datadog (auto)      | Span                      | Write latency, failures                |
| Config-DS                     | Datadog (auto)      | Span                      | Personality fetch latency              |
| ai-gateway (LiteLLM)          | Datadog + LangSmith | Span + gauge + run        | Model, tokens, latency, response text  |
| Any unhandled exception       | Sentry              | Exception                 | Stack trace + request context          |
| Explicit failures             | Sentry + Datadog    | Exception + counter       | Debug detail + alert signal            |


---

## 11. Best Practices

### Structure your logs as JSON, not plain text

```python
# Bad — cannot be searched or filtered
logger.error(f"the Content Search API failed after {latency}ms for user {user_id}")

# Good — every field is queryable in Datadog Log Management
logger.error("concorde_call_failed", extra={
    "latency_ms": latency,
    "user_id": user_id,
    "site_id": site_id,
    "conversation_id": conversation_id,
    "error_type": type(e).__name__,
})
```

### Tag everything consistently

The same tag values (`application`, `environment`, `site_id`, `auth_state`) must appear in Datadog metrics, ddtrace spans, Sentry scope, and BigQuery events. Without this, you cannot correlate a Datadog alert with the BigQuery session or the Sentry error.

### Trust the backend for sensitive fields

`model_used`, `latency_ms`, `intent_classification`, and `guardrail_triggered` must come from the backend — never from the browser. The browser can be manipulated; the backend cannot.

### Measure impressions, not just clicks

CTR = clicks / impressions. Without `assistant_article_impression` events you only know articles were clicked — not how often they were shown. A 0% CTR could mean nobody clicked, or it could mean the article was never surfaced. Phase 2 adds impression events specifically to fix this.

### Set SLOs before setting alerts

Alerts without SLOs are noise. Define targets first:

- `ai_assistant.error` < 1% of requests → error rate SLO
- `ai_assistant.response_latency` p99 < 5,000 ms → latency SLO
- `ai_assistant.llm_latency` p95 < 3,000 ms → ai-gateway dependency SLO

Then set alerts on burn-rate thresholds rather than raw values.

### Pair every Datadog counter with a Sentry capture

Datadog tells you something broke. Sentry tells you how to fix it. A counter without Sentry gives you an alert with no debug path. A Sentry event without a counter gives you debug detail but no alert. Always emit both.

### Treat guardrail rate as a product signal, not just a safety signal

A high `content_grounding_fail` rate for a brand means the LLM is drifting off-topic. A high `input_topic_block` rate means the filters in Config-DS are too aggressive and blocking real user questions. Surface guardrail rates in Looker alongside engagement metrics.

### Budget LLM costs per brand

Cost per conversation depends on:

- Number of LLM calls per turn (up to 5 if the guardrail retry fires)
- Model tier used (haiku vs sonnet — roughly 5–10× cost difference)
- Token count (driven by `max_response_tokens` in Config-DS per site)

Track `ai_assistant.tokens_in` and `ai_assistant.tokens_out` tagged by `site_id` and `call_type`. This lets you attribute cost to each brand and identify which Config-DS settings are driving spend.

### Redact PII before it reaches analytics

`query_text` and `trigger_query` (the message that triggered a guardrail) contain user input. Before writing to BigQuery or Sentry: hash `user_id` for analytics, strip or truncate free-text fields in error tracking where the full text is not needed for debugging, and get Legal review on any field containing raw user input.

### Test your observability, not just your code

Instrumentation can silently break (a DogStatsD env var not set, a Sentry DSN misconfigured). Add smoke tests that:

- Verify a test request produces the expected Datadog metric
- Verify a test exception is captured in Sentry in staging
- Verify a test GA4 event arrives in BigQuery within the 5-minute SLA

---

## 12. Quick Reference

### Which tool answers which question


| Question                                   | Tool                                                               |
| ------------------------------------------ | ------------------------------------------------------------------ |
| "Why is it slow?"                          | Datadog ddtrace spans — find the long span in the flame graph      |
| "Why is it failing?"                       | Sentry exception + Datadog `ai_assistant.error` counter            |
| "Who is affected?"                         | GA4 → BigQuery → Looker; segment by `site_id`, `auth_state`        |
| "Is it safe?"                              | Datadog `ai_assistant.guardrail_triggered` by type                 |
| "What does it cost?"                       | Datadog `ai_assistant.tokens_in/out` by `site_id` and `call_type`  |
| "Are users engaging?"                      | GA4 `assistant_article_click` / `assistant_article_impression` CTR |
| "Is the cache working?"                    | Datadog Valkey span hit/miss for `personality:{site_id}`           |
| "Which LangGraph path fired?"              | LangSmith run tree (graph view)                                    |
| "What did the LLM actually say?"           | LangSmith — full prompt + completion per node                      |
| "Did my prompt change make things better?" | LangSmith evaluation datasets                                      |


### Metric quick lookup

```
ai_assistant.query_received                → counter  : total requests
ai_assistant.response_latency              → gauge ms : end-to-end latency
ai_assistant.llm_latency                   → gauge ms : ai-gateway round-trip
ai_assistant.search_query_index_latency    → gauge ms : the Content Search API search
ai_assistant.guardrail_triggered           → counter  : by guardrail_type
ai_assistant.error                         → counter  : by error_source
ai_assistant.tool_call                     → counter  : by tool name
ai_assistant.tokens_in / tokens_out        → gauge    : by call_type + site_id
```

### GA4 event quick lookup

```
assistant_session_start      → panel opened
assistant_query_submitted    → message sent
assistant_response_rendered  → AI response shown (latency_ms, model_used)
assistant_article_impression → article card shown (position)
assistant_article_click      → article card clicked (time_to_click_ms)
assistant_guardrail_triggered → filtered response shown to user
assistant_error              → frontend error
```

### LangSmith vs Datadog at a glance


| Dimension               | Datadog                             | LangSmith                      |
| ----------------------- | ----------------------------------- | ------------------------------ |
| Scope                   | Full service (HTTP, DB, cache, LLM) | LLM calls and agent graph only |
| Latency tracking        | All spans                           | Per-node in the agent graph    |
| Alerting                | Yes (PagerDuty, Slack, OpsGenie)    | No                             |
| Prompt content          | No (intentionally — PII risk)       | Yes (full prompt + completion) |
| Evaluation / regression | No                                  | Yes (datasets, scores)         |
| Cost tracking           | Token gauges (numbers only)         | Native token + cost per model  |
| LangGraph integration   | Manual ddtrace spans                | Native — two env vars, no code |
| Do they integrate?      | No — separate destinations          | No — separate destinations     |


---

*Document authored for MediaCo AI Assistant Phase 2. Ground truth source: `docs/AI_ASSISTANT_SCHEMA.md`. Last reviewed: May 2026.*