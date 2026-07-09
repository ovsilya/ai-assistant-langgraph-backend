# AWS Bedrock Guardrails Analysis & Integration Guide

Consolidated findings for the spike: *Check if AWS Bedrock Guardrails can be utilised while streaming the response.*

**Repo:** `ai-assistant` (internal repository)  
**Reference (MediaCo team):** internal reference material (not included)  
**Status:** Spike / architecture — **not yet implemented** in ai-assistant

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [What AWS Bedrock Guardrails are](#2-what-aws-bedrock-guardrails-are)
3. [What ai-assistant uses today (different system)](#3-what-ai-assistant-uses-today-different-system)
4. [MediaCo team reference material](#4-mediaco-team-reference-material)
5. [Accessing Bedrock Guardrails through ai-gateway](#5-accessing-bedrock-guardrails-through-ai-gateway)
6. [Streaming + guardrails (`streamProcessingMode`)](#6-streaming--guardrails-streamprocessingmode)
7. [Content Search API precedent](#7-content-search-api-precedent)
8. [Current ai-assistant code map](#8-current-ai-assistant-code-map)
9. [Feasibility conclusion](#9-feasibility-conclusion)
10. [Recommended architecture](#10-recommended-architecture)
11. [Implementation phases](#11-implementation-phases)
12. [Spike checklist & test matrix](#12-spike-checklist--test-matrix)
13. [Open questions for MediaCo platform](#13-open-questions-for-mediaco-platform)
14. [Risks and trade-offs](#14-risks-and-trade-offs)
15. [Suggested branch & PR strategy](#15-suggested-branch--pr-strategy)
16. [External links](#16-external-links)

---

## 1. Executive summary

| Question | Answer |
|----------|--------|
| Can Assistant use **AWS Bedrock Guardrails**? | **Yes** — via Bedrock **Converse** / **ConverseStream** APIs. |
| Can we use them through **ai-gateway**? | **Yes** — via **Bedrock pass-through** endpoints, **not** the OpenAI `/v1/chat/completions` path used today. |
| Can we use them **while streaming**? | **Yes** — `ConverseStream` + `guardrailConfig.streamProcessingMode` (`sync` or `async`). |
| Is it implemented in ai-assistant today? | **No** — guardrails are **LLM prompt reviewers**; streaming is a **placeholder** node. |
| Does Bedrock replace our **brand output guardrail**? | **Not fully** — Bedrock covers AWS policy categories; **article grounding / editorial rules** still need the custom reviewer (or duplicated Bedrock policies). |

**Bottom line for** Feasible and aligned with how the Content Search API already works. Requires a **new transport layer** (Bedrock pass-through) and **real streaming** in the API/graph — not a config tweak on the existing `ChatOpenAI` client.

---

## 2. What AWS Bedrock Guardrails are

**Amazon Bedrock Guardrails** are AWS-managed content filters attached to Bedrock model calls. They run **inside the Bedrock runtime**, not as a separate LLM “reviewer” prompt.

Typical policy categories (configured in AWS console / API):

| Category | Examples |
|----------|----------|
| **Denied topics** | Medical diagnosis, hate, violence (configurable) |
| **Harmful content** | Toxicity, sexual content thresholds |
| **PII** | Detect / block / mask sensitive data |
| **Prompt attacks** | Jailbreak patterns |
| **Word filters** | Custom blocked/allowed lists |

You attach them with **`guardrailConfig`** on:

- `Converse` (non-streaming)
- `ConverseStream` (streaming)
- `InvokeModelWithResponseStream` (model-specific streaming)

Key fields:

```json
{
  "guardrailIdentifier": "arn:aws:bedrock:…:guardrail/…",
  "guardrailVersion": "1",
  "trace": "enabled",
  "streamProcessingMode": "async"
}
```

- **`guardrailIdentifier`** — guardrail ID or full ARN (the Content Search API uses ARN).
- **`guardrailVersion`** — version number or `DRAFT`.
- **`trace`** — optional diagnostics for what was blocked.
- **`streamProcessingMode`** — only for streaming APIs (`sync` | `async`).

Official docs:

- [Include a guardrail with the Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html)
- [Configure streaming response behavior](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-streaming.html)

---

## 3. What ai-assistant uses today (different system)

Assistant implements **application-level guardrails** — extra **Haiku** LLM calls with brand prompts from `config/brands/*.json`. This is **not** AWS Bedrock Guardrails.

```text
POST /v1/assistant/chat  (synchronous JSON — no token streaming)
        │
        ▼
   LangGraph
        │
        ├─ input_guardrail     → Haiku via ai-gateway OpenAI path
        │                        (intent, blocked topics, resolved_query)
        │
        ├─ generate_response   → Sonnet via same OpenAI path
        │                        (main answer with article context)
        │
        ├─ followup_suggestions → Haiku (parallel)
        │
        ├─ output_guardrail    → Haiku reviewer (parallel)
        │                        (brand output_filter editorial rules)
        │
        ├─ assemble_response   → pass / retry / fallback
        │
        └─ stream_output       → no-op placeholder (no SSE yet)
```

### Two guardrail systems compared

| | **AWS Bedrock Guardrails** | **Assistant LLM guardrails (today)** |
|---|------------------------------|--------------------------------------|
| **Mechanism** | Bedrock API `guardrailConfig` on model call | Separate Haiku calls + JSON prompts |
| **Input blocking** | Bedrock evaluates user/model content | `input_guardrail` node (`input_filter_topics`, intent) |
| **Output blocking** | Bedrock evaluates model output (incl. stream) | `output_guardrail` node (`output_filter` rules) |
| **Brand grounding** (“cite [1], no fake stats”) | Not built-in — custom policies or separate step | **Core purpose** of `output_guardrail` prompt |
| **When it runs** | During Converse / ConverseStream | After full response text is generated (output path) |
| **Streaming** | Native (`streamProcessingMode`) | N/A until streaming exists |
| **Gateway path** | Bedrock pass-through | `/v1/chat/completions` (OpenAI-compatible) |

**Important:** These can **coexist** — Bedrock for baseline safety on the **main model stream**, Haiku reviewer for **Meridian/Savora/RW editorial** rules.

---

## 4. MediaCo team reference material

Source file: internal reference material (not included)

### 4.1 ai-gateway Bedrock pass-through (curl)

MediaCo provided this pattern (environment: **feature** in the example; local dev often uses **staging**):

```bash
curl -X POST 'https://ai-gateway.internal.example.com/bedrock/model/my-bedrock-model/converse' \
  -H 'Authorization: Bearer sk-your-ai-gateway-virtual-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": [{"text": "Hello"}]
      }
    ],
    "inferenceConfig": {
      "temperature": 0,
      "maxTokens": 1000
    },
    "guardrailConfig": {
      "guardrailIdentifier": "BEDROCK_GUARDRAIL_ID",
      "guardrailVersion": "BEDROCK_GUARDRAIL_VERSION"
    }
  }'
```

### 4.2 Platform notes from the same file

| Note | Detail |
|------|--------|
| **LiteLLM docs** | https://docs.litellm.ai/docs/pass_through/bedrock |
| **Gateway UI** | https://ai-gateway.internal.example.com/#/Bedrock Pass-through |
| **Models with inference profiles** | `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-opus-4-7` |
| **Auth** | App inference profiles already set up — **no extra AWS keys in the app** when using ai-gateway for those models |

Replace `my-bedrock-model` with the actual model alias (e.g. `claude-sonnet-4-6`) per gateway UI.

### 4.3 Content Search API implementation note

the Content Search API already uses Bedrock Guardrails in **conversational search**:

- Code: `concorde/services/conversational_search.py#L463` (internal repository)
- Uses **ARN** as `guardrailIdentifier`
- Uses Bedrock **Converse** API via `ChatBedrockConverse` (LangChain AWS)

---

## 5. Accessing Bedrock Guardrails through ai-gateway

### 5.1 Two ai-gateway paths

```mermaid
flowchart TB
  subgraph openai_path [OpenAI-compatible path — USED TODAY]
    A[ChatOpenAI] --> B["ai-gateway …/v1/chat/completions"]
    B --> C[LiteLLM proxy]
    C --> D[Claude via inference profile]
  end

  subgraph bedrock_path [Bedrock pass-through — NEEDED FOR GUARDRAILS]
    E[httpx / ChatBedrockConverse] --> F["ai-gateway …/bedrock/model/{model}/converse"]
    F --> G[Bedrock Converse API]
    G --> H["guardrailConfig applied"]
  end
```

| Path | URL shape | `guardrailConfig`? | Used in ai-assistant? |
|------|-----------|--------------------|------------------------|
| **OpenAI proxy** | `{base}/v1/chat/completions` | **No** | **Yes** — all LLM steps |
| **Bedrock pass-through** | `{base}/bedrock/model/{model}/converse` | **Yes** | **No** |
| **Bedrock stream** | `{base}/bedrock/model/{model}/converse-stream` (confirm in UI) | **Yes** + `streamProcessingMode` | **No** |

Current client (`ai_assistant/llm/ai_gateway.py`):

```python
return ChatOpenAI(
    model=model,
    base_url=openai_base_url(),   # …/v1
    api_key=settings.ai_gateway_api_key,
    ...
)
```

**You cannot pass `guardrailConfig` through `ChatOpenAI`.** requires either:

1. **HTTP pass-through** to ai-gateway Bedrock endpoints (recommended spike), or  
2. **`langchain-aws` `ChatBedrockConverse`** with gateway-compatible endpoint (if supported), mirroring the Content Search API.

### 5.2 Environment variables (proposed)

Add to `config/base.py` / `.env` when implementing:

```bash
# Bedrock Guardrails — get ID/version from platform team
BEDROCK_GUARDRAIL_ID=arn:aws:bedrock:us-east-1:…:guardrail/…
BEDROCK_GUARDRAIL_VERSION=1
BEDROCK_STREAM_PROCESSING_MODE=async   # sync | async
```

Use the same `AI_GATEWAY_API_KEY` and `AI_GATEWAY_BASE_URL` as existing LLM calls (stage vs feature URL must match your environment).

### 5.3 Example spike request (stage)

Adjust host and model for your environment:

```bash
export AI_GATEWAY_BASE_URL=https://ai-gateway.internal.example.com
export AI_GATEWAY_API_KEY='…'
export BEDROCK_GUARDRAIL_ID='…'
export BEDROCK_GUARDRAIL_VERSION='1'

curl -sS -X POST "${AI_GATEWAY_BASE_URL}/bedrock/model/claude-sonnet-4-6/converse" \
  -H "Authorization: Bearer ${AI_GATEWAY_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"messages\": [{\"role\": \"user\", \"content\": [{\"text\": \"Hello from spike\"}]}],
    \"inferenceConfig\": {\"temperature\": 0.7, \"maxTokens\": 256},
    \"guardrailConfig\": {
      \"guardrailIdentifier\": \"${BEDROCK_GUARDRAIL_ID}\",
      \"guardrailVersion\": \"${BEDROCK_GUARDRAIL_VERSION}\"
    }
  }"
```

---

## 6. Streaming + guardrails (`streamProcessingMode`)

Streaming is **not implemented** in ai-assistant today (`stream_output` is a no-op; chat returns full JSON). asks whether Bedrock Guardrails work **during** streaming — AWS answer is **yes**, on **`ConverseStream`**.

### 6.1 Processing modes

| Mode | Behavior | Latency | Safety |
|------|----------|---------|--------|
| **`sync`** | Buffer chunks; guardrail scans before user sees each batch | Higher | Stricter — inappropriate content less likely to flash |
| **`async`** | Stream chunks immediately; guardrail runs in background | Lower (TTFT) | May briefly show bad content; **blocks subsequent chunks** when violation found |

the Content Search API uses **`async`** (see §7).

AWS notes:

- Async mode does **not** support **PII masking** ([streaming guardrails doc](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-streaming.html)).
- Product must choose latency vs. safety for the FRE widget.

### 6.2 Streaming request shape (illustrative)

```json
{
  "messages": [...],
  "inferenceConfig": { "maxTokens": 1024, "temperature": 0.7 },
  "guardrailConfig": {
    "guardrailIdentifier": "arn:aws:bedrock:…:guardrail/…",
    "guardrailVersion": "1",
    "streamProcessingMode": "async",
    "trace": "enabled"
  }
}
```

Endpoint: confirm exact pass-through path in ai-gateway **Bedrock Pass-through** UI (likely `…/converse-stream` parallel to `…/converse`).

### 6.3 Relationship to Assistant graph

Today:

```text
generate_response  →  ainvoke (full text)
output_guardrail   →  runs on complete response (parallel with followups)
stream_output      →  empty
API                →  single JSON blob
```

Target for streaming + Bedrock:

```text
generate_response  →  ConverseStream + guardrailConfig (tokens accumulate)
stream_output      →  forward SSE to client OR merge stream in API layer
output_guardrail   →  TBD: post-stream full-text review OR reduced scope
```

Open design choice: run **brand `output_guardrail`** after stream completes (keeps editorial rules) vs. rely on Bedrock only for live token gating (faster, weaker on grounding).

---

## 7. Content Search API precedent

the Content Search API **conversational search** (separate product — do not merge with Assistant Phase 2) still serves as the **internal reference** for Bedrock + guardrails + streaming:

```python
llm = ChatBedrockConverse(
    region_name=BEDROCK_LLM[effective_llm]["region"],
    model=BEDROCK_LLM[effective_llm]["model"],
    temperature=0,
    max_tokens=MAX_TOKENS,
    aws_access_key_id=aws_credentials.get("AccessKeyId"),
    aws_secret_access_key=aws_credentials.get("SecretAccessKey"),
    aws_session_token=aws_credentials.get("SessionToken"),
    **(
        {
            "guardrail_config": {
                "guardrailIdentifier": self._guardrail_id,
                "guardrailVersion": self._guardrail_version,
                "streamProcessingMode": "async",
            },
            "guard_last_turn_only": True,
        }
        if self._guardrail_id
        else {}
    ),
)
```

| the Content Search API pattern | Assistant takeaway |
|------------------|-------------------|
| ARN as `guardrailIdentifier` | Use same ID format MediaCo provides |
| `streamProcessingMode: "async"` | Default for streaming spike (match the Content Search API) |
| `guard_last_turn_only: True` | Only guard latest turn — relevant for multi-turn chat |
| Direct AWS creds in the Content Search API | Assistant should prefer **ai-gateway pass-through** + virtual key (no app AWS keys) |

---

## 8. Current ai-assistant code map

| Component | File | Role re: |
|-----------|------|------------------|
| OpenAI gateway client | `ai_assistant/llm/ai_gateway.py` | **Replace/extend** for Bedrock pass-through |
| Main answer | `ai_assistant/llm/client.py` → `generate_answer()` | Uses `main_llm().ainvoke` — **needs stream variant** |
| Generate node | `ai_assistant/nodes/generate_response.py` | Calls `generate_answer` |
| Output reviewer | `ai_assistant/nodes/output_guardrail.py` | LLM `check_output_guardrail` — **keep or narrow** |
| Input classifier | `ai_assistant/nodes/input_guardrail.py` | Unrelated to AWS guardrails (intent routing) |
| Stream terminal | `ai_assistant/nodes/stream_output.py` | **Placeholder** — must implement |
| Chat API | `ai_assistant/api/chat.py` | Sync JSON — **needs SSE/stream mode** |
| Brand rules | `config/brands/*.json` → `output_filter`, `input_filter_topics` | Editorial layer — not in Bedrock by default |
| Architecture doc | `docs/10_AGENTIC_ARCHITECTURE.md` § streaming | Documents streaming as future requirement |

Graph routing after guardrail pass (unchanged conceptually):

```text
assemble_response
  ├─ guardrail_passed → stream_output → END
  ├─ retry_count < 1  → generate_response (retry)
  └─ else             → build_fallback → stream_output → END
```

Bedrock guardrails on **generate_response** would filter **during** generation; the **assemble/output_guardrail** loop may still be needed for **grounding** failures Bedrock does not detect.

---

## 9. Feasibility conclusion

| acceptance criterion | Verdict |
|------------------------------|---------|
| Bedrock Guardrails usable in MediaCo stack? | **Yes** — proven in the Content Search API; documented for ai-gateway pass-through |
| Accessible via ai-gateway without app AWS keys? | **Yes** — virtual key + inference profiles for Claude models |
| Compatible with streaming? | **Yes** — `ConverseStream` + `streamProcessingMode` |
| Drop-in on current `ChatOpenAI` path? | **No** — different API surface |
| Ready to ship without other work? | **No** — needs streaming API + graph changes + guardrail IDs from platform |

---

## 10. Recommended architecture

### 10.1 Layered guardrails (recommended)

```mermaid
flowchart TB
  user[User message]
  input[input_guardrail Haiku intent + topics]
  concorde[the Content Search API articles]
  gen[generate_response Sonnet ConverseStream]
  bedrock[AWS Bedrock guardrailConfig on stream]
  follow[followup_suggestions Haiku]
  brand[output_guardrail Haiku editorial optional post-stream]
  api[SSE / JSON to FRE widget]

  user --> input
  input --> concorde
  concorde --> gen
  gen --> bedrock
  bedrock --> follow
  bedrock --> brand
  follow --> api
  brand --> api
```

**Layer 1 — AWS Bedrock (on main stream):** baseline safety, denied topics, PII, etc.  
**Layer 2 — LLM input guardrail (existing):** intent routing, brand domains, `resolved_query`.  
**Layer 3 — LLM output guardrail (existing or slimmed):** article grounding, hallucination, marketing language.

### 10.2 What to move first

| LLM call | Move to Bedrock guardrails? | Notes |
|----------|----------------------------|-------|
| **Main answer (Sonnet)** | **Yes focus** | Streaming + `guardrailConfig` |
| Input guardrail (Haiku) | No (short term) | Intent JSON not Converse-shaped |
| Output guardrail (Haiku) | Keep initially | Brand `output_filter` |
| Follow-ups / title (Haiku) | No | Low risk; small outputs |

---

## 11. Implementation phases

### Phase A spike (investigation only)

- [ ] Obtain `BEDROCK_GUARDRAIL_ID` + version from platform (same as the Content Search API or Assistant-specific).
- [ ] Confirm pass-through URLs on **staging** (your dev URL) in ai-gateway UI.
- [ ] Run non-streaming `converse` curl with benign + blocked prompts.
- [ ] Run `converse-stream` with `streamProcessingMode: async` and `sync`; record TTFT and block behavior.
- [ ] Document results in ticket + this doc (§12).

**Deliverable:** Written answer to with pass/fail matrix — no production graph change required.

### Phase B — Client module

- [ ] Add `ai_assistant/llm/bedrock_gateway.py` (httpx pass-through client).
- [ ] Env vars in `config/base.py`; document in `.env.example`.
- [ ] Unit tests with mocked HTTP responses (guardrail block vs pass).

### Phase C — Streaming in graph + API

- [ ] `generate_answer_stream()` using ConverseStream.
- [ ] Implement `stream_output` / SSE endpoint on `POST /v1/assistant/chat` (or new route).
- [ ] Frontend contract with FRE widget team.

### Phase D — Guardrail strategy finalization

- [ ] Decide sync vs async with product.
- [ ] Decide whether to keep full `output_guardrail` after stream.
- [ ] Observability: map Bedrock `trace` to Datadog/Sentry tags.

---

## 12. Spike checklist & test matrix

### Prerequisites

- VPN on
- `AI_GATEWAY_API_KEY` in `ai-assistant/.env`
- Guardrail ID/version from MediaCo
- ai-gateway Bedrock pass-through enabled for your virtual key

### Test matrix

| # | Test | Endpoint | Expected |
|---|------|----------|----------|
| 1 | Benign greeting | `converse` | 200, normal completion |
| 2 | Known denied topic (e.g. medical diagnosis) | `converse` | Guardrail intervention / blocked content |
| 3 | Missing `guardrailConfig` | `converse` | Baseline — model responds (no AWS guardrail) |
| 4 | Invalid guardrail ID | `converse` | 4xx with clear error |
| 5 | Benign prompt | `converse-stream` + `async` | Token events; low TTFT |
| 6 | Denied topic | `converse-stream` + `async` | Stream starts then stops or replaces per AWS behavior |
| 7 | Same with `sync` | `converse-stream` | Higher latency; stricter filtering |

Record for each: status code, latency, sample response body, whether `trace` explains the block.

---

## 13. Open questions for MediaCo platform

1. **Guardrail identity:** Assistant uses the Content Search API's guardrail ARN, or a separate Assistant guardrail?
2. **Exact pass-through paths** on staging vs feature for `converse` and `converse-stream`.
3. **Virtual key scope:** Does our key allow Bedrock pass-through, or only `/v1`?
4. **Model alias in URL:** Is it `claude-sonnet-4-6` or an inference profile slug?
5. **Streaming mode:** Product preference — `sync` (safer) vs `async` (the Content Search API default)?
6. **UX on block:** What should FRE show when Bedrock blocks mid-stream?
7. **Editorial rules:** Keep Haiku `output_guardrail` for article grounding after?
8. **Input path:** Any plan to move input filtering to Bedrock, or keep LLM intent node?

---

## 14. Risks and trade-offs

| Risk | Mitigation |
|------|------------|
| **Two guardrail systems** confuse operators | Document layers clearly; tag spans `guardrail_source=bedrock\|llm` |
| **async streaming flashes bad tokens** | Use `sync` for strict UX, or accept the Content Search API-style async |
| **Bedrock doesn’t enforce article grounding** | Keep brand `output_guardrail` post-stream |
| **Dual latency** (Bedrock sync + Haiku reviewer) | Measure; consider reviewer only on `content_question` with articles |
| **Wrong gateway path** | Spike on pass-through before graph refactor |
| **Environment mismatch** | staging key + URL together; reference file uses feature |
| **Replacing output guardrail too early** | Caused production grounding failures in testing — don’t remove until Bedrock policies match |

---

## 15. Suggested branch & PR strategy

| Approach | When |
|----------|------|
| **`-bedrock-guardrails-spike`** branch from `main` | Spike script + findings only |
| **Separate PR** from agent PR | Keeps review focused; is investigation |
| **Merge spike doc + script** without changing production graph | Satisfies ticket with minimal risk |

After spike approval, implementation PRs should reference the spike ticket and any follow-on streaming ticket.

---

## 16. External links

| Resource | URL |
|----------|-----|
| LiteLLM Bedrock pass-through | https://docs.litellm.ai/docs/pass_through/bedrock |
| ai-gateway Bedrock UI (feature example) | https://ai-gateway.internal.example.com/#/Bedrock Pass-through |
| AWS Guardrails + Converse | https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html |
| AWS Guardrails streaming modes | https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-streaming.html |
| the Content Search API reference implementation | (internal repository) |
| Assistant architecture (streaming note) | `docs/10_AGENTIC_ARCHITECTURE.md` |
| Assistant LLM stack | internal architecture notes (not included) §6–7 |
| Assistant testing | `docs/TESTING_GUIDE.md` |

---

*Last updated: development session covering analysis against ai-assistant `-797-798-799-800-langgraph-agent` branch state.*
