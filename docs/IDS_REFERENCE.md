# Phase 2 — Identifier Reference (AI Assistant Service)

A complete review of every ID used in the `ai_assistant_service` code and its API/the Content Search API calls: what each one means, who creates it, where it lives, and how it flows through the LangGraph chat pipeline.

> **TL;DR confusion-killers**
> - `site_id` (API) is a **slug** like `brand_alpha_us`. `concorde_site_id` is a **Site Registry UUID** like `00000000-...`. They are **not** the same value.
> - `content_id` is the **article** UUID (CMS). `conversation_id` is the **chat session** UUID. `user_id` is the **reader**. All different scopes.
> - the Content Search API endpoints (`get_related`, `query_index`) need the **Site Registry UUID**, never the slug.

---

## 1. Quick map of all IDs

| ID | Type / format | Created by | Scope | Where it enters our code |
|----|---------------|------------|-------|--------------------------|
| `user_id` | string (caller-defined; e.g. `anon_1`) | Frontend / widget | One reader (or anon device) | `ChatRequest.user_id` |
| `conversation_id` | UUID4 string | **Our service** (`uuid4()`) if not supplied | One chat session | `ChatRequest.conversation_id` (optional) |
| `site_id` | **slug** (`brand_alpha_us`) | Brand config convention | One brand/locale | `ChatRequest.site_id` |
| `concorde_site_id` | **UUID** (Site Registry) | Site Registry (site registry) | One brand/locale | Brand JSON → `AgentState.concorde_site_id` |
| `content_id` | **UUID** (CMS) | CMS (CMS) | One article | `ChatRequest.content_id` (optional) |
| `message_id` | ULID string | **Our service** (`new_message_id()`) | One stored message | `Message.message_id` (DynamoDB) |
| article `id` | UUID (CMS) | CMS / the Content Search API index | One article | the Content Search API response → recommendation cards |

---

## 2. The two “site” identifiers (main source of confusion)

There are **two different values** that both describe the brand. Keeping them straight is the single most important thing in this project.

| | `site_id` | `concorde_site_id` |
|---|-----------|--------------------|
| Example | `brand_alpha_us` | `00000000-0000-0000-0000-000000000001` |
| Format | Human-readable slug | UUID (Site Registry) |
| Purpose | Pick brand config / persona / prompts on **our** side | Route the Content Search API search + related to the right OpenSearch index |
| Set where | `ChatRequest.site_id` (API input) | Brand JSON `concorde_site_id`, loaded into state by `load_context` |
| Used by | `brand_config.py`, all graph nodes | `concorde.py` (`get_related`, `query_index`) |
| Aliases | `brand_alpha` → `brand_alpha_us`, `rw` → `brand_gamma_us` (see `_SITE_ALIASES`) | none |

### How they connect

```
ChatRequest.site_id = "brand_alpha_us"      (slug from widget)
        │
        ▼  load_context → load_personality(site_id)
brand JSON "brand_alpha_us.json"
        │  contains:
        ▼
concorde_site_id = "00000000-0000-0000-0000-000000000001"   (Site Registry UUID)
        │
        ▼  passed to concorde.query_index / get_related
the Content Search API API path uses the UUID, NOT the slug
```

### Current brand values

| Brand file | API `site_id` | `concorde_site_id` (Site Registry UUID) |
|------------|---------------|-----------------------------------|
| `brand_alpha_us.json` | `brand_alpha_us` | `00000000-0000-0000-0000-000000000001` ✅ |
| `brand_beta_us.json` | `brand_beta_us` | *(empty — falls back to `CONCORDE_SITE_ID` in `.env`)* |
| `brand_gamma_us.json` | `brand_gamma_us` | *(empty — falls back to `.env`)* |

### Fallback safety net in `concorde.py`

`_voltron_site_id()` decides which UUID actually hits the Content Search API:

```12:18:ai_assistant_service/src/ai_assistant/services/concorde.py
def _voltron_site_id(site_id: str, concorde_site_id: str | None = None) -> str:
    voltron = (concorde_site_id or "").strip() or settings.concorde_site_id
    return site_id if _is_uuid(site_id) else voltron
```

Logic:
1. If the incoming `site_id` is **already a UUID**, use it directly.
2. Else use the brand's `concorde_site_id`.
3. Else fall back to `settings.concorde_site_id` (Meridian UUID from `.env` / defaults).

So a slug like `brand_alpha_us` is **never** sent to the Content Search API — it always resolves to a UUID first.

---

## 3. Each ID in detail

### `user_id`
- **What:** Identifies the reader (logged-in user or an anonymous device token like `anon_1`).
- **Created by:** The frontend/widget. Our service does not generate it.
- **Used for:** DynamoDB partition key on the conversations table (one user's chat list); fire-and-forget persistence.
- **In code:** `ChatRequest.user_id` → `AgentState.user_id` → `persist_turn` → `Conversation.user_id`.
- **Note:** Required on the API. Not used for any LLM or the Content Search API logic — purely identity/persistence.

### `conversation_id`
- **What:** Ties multiple turns into one chat session.
- **Created by:** **Our service** — `ensure_conversation_id()` generates a `uuid4()` when the client doesn't send one.
- **Used for:** In-memory history (`context_store._threads`), DynamoDB sort key on conversations + partition key on messages.
- **In code:** `ChatRequest.conversation_id` (optional) → `load_context` ensures it → returned in `ChatResponse.conversation_id`.
- **Client contract:** First request omits it → we mint one and return it → client echoes it back on follow-ups.

```10:11:ai_assistant_service/src/ai_assistant/services/context_store.py
def ensure_conversation_id(conversation_id: str | None) -> str:
    return conversation_id or str(uuid4())
```

> **the Content Search API note:** the Content Search API's own Conversational Search product has its *own* `conversation_id` (OpenSearch memory plugin). We do **not** use that — Phase 2 calls search-only endpoints, so our `conversation_id` is entirely our own.

### `site_id`
- **What:** Brand + locale selector as a slug.
- **Created by:** Convention in brand config (`brand_alpha_us`, `brand_beta_us`, `brand_gamma_us`).
- **Used for:** Loading persona, prompts, guardrail topics, response length.
- **In code:** `ChatRequest.site_id` (default `brand_alpha_us`) → `resolve_site_id()` (applies aliases) → `load_brand_config()`.
- **Aliases:** `brand_alpha`, `brand_beta`, `rw`, `brand_gamma` (case-insensitive).

### `concorde_site_id`
- **What:** Site Registry UUID for the same brand — the Content Search API's index routing key.
- **Created by:** Site Registry (MediaCo site registry).
- **Used for:** Building the Content Search API URLs for `get_related` and `query_index`.
- **In code:** Brand JSON field → `AgentState.concorde_site_id` → passed to both the Content Search API nodes.

### `content_id`
- **What:** UUID of the specific article the reader is viewing.
- **Created by:** CMS (the CMS). Equals the CSV `ITEM_ID` column.
- **Used for:** `get_related` — “you might also like” for the current page.
- **In code:** `ChatRequest.content_id` (optional) → `AgentState.content_id` → `get_related_node`.
- **Important:** Without `content_id`, `get_related` returns **empty** (we removed the CSV/URL-lookup fallback). The widget should pass the page’s CMS UUID.

```120:135:ai_assistant_service/src/ai_assistant/services/concorde.py
    cid = (content_id or "").strip()
    if not cid:
        logger.warning("get_related skipped: content_id required (page_url=%s)", page_url)
        return []

    voltron = _voltron_site_id(site_id, concorde_site_id)
    n = limit or settings.max_articles
    url = f"{settings.concorde_api_base.rstrip('/')}/v2/consumer/{voltron}/related/{cid}"
```

### `message_id`
- **What:** Per-message identifier for stored chat messages.
- **Created by:** **Our service** — `new_message_id()` returns a **ULID** (time-sortable).
- **Used for:** DynamoDB sort key on the messages table (chronological ordering).
- **In code:** `Message.message_id` default factory. Not exposed on the chat API.

### Article `id` (in recommendations)
- **What:** UUID of each recommended article in the Content Search API responses.
- **Created by:** CMS / the Content Search API index (same space as `content_id`).
- **Used for:** Identifying recommendation cards in `recommendations.related[]` and `recommendations.query_index[]`.
- **In code:** Mapped by `_map_article()` → `{"id": raw["id"], ...}`.

---

## 4. How IDs flow through one chat request

```
POST /v1/assistant/chat
{
  "user_id":         "anon_1",            ← reader identity (persistence)
  "message":         "What electric SUVs has Meridian reviewed?",
  "url":             "https://www.meridian.example.com/.../lucid-gravity-review/",
  "content_id":      "00000000-...",      ← article UUID (CMS) → get_related
  "site_id":         "brand_alpha_us",        ← brand slug → brand config
  "conversation_id":  null                 ← omitted → service mints uuid4()
}
        │
        ▼ _build_initial_state → AgentState
load_context:
   resolve_site_id("brand_alpha_us") → brand JSON
   → concorde_site_id = "00000000-..."  (Site Registry UUID added to state)
   → ensure_conversation_id(null) → new uuid4()
        │
        ▼ (content_question intent)
   ┌── query_index ── GET {ai_search}/search/{concorde_site_id}/{query}?max_age=90d
   └── get_related ── GET {api}/v2/consumer/{concorde_site_id}/related/{content_id}
        │
        ▼ generate_response → guardrails → assemble
ChatResponse
{
  "conversation_id": "<minted uuid4>",   ← client echoes this on next turn
  "recommendations": {
     "related":     [ { "id": "<article uuid>", ... } ],
     "query_index": [ { "id": "<article uuid>", ... } ]
  },
  ...
}
```

---

## 5. the Content Search API calls — which endpoint accepts which IDs

Both recommendation calls live in `services/concorde.py` and are triggered (in parallel) by the `content_question` branch of the graph. They use **different hosts**, **different path shapes**, and **different IDs**.

### 5.1 `get_related` — related articles for the current page

```
GET {CONCORDE_API_BASE}/v2/consumer/{concorde_site_id}/related/{content_id}
     └─ default: https://search.example.com
```

| Path / input | ID used | Format | Required? | Source |
|--------------|---------|--------|-----------|--------|
| `{concorde_site_id}` | site (Site Registry) UUID | UUID | ✅ | brand JSON `concorde_site_id` (or `.env` fallback) |
| `{content_id}` | article UUID (CMS) | UUID | ✅ | `ChatRequest.content_id` (the page the reader is on) |

- **No `content_id` → returns `[]`** (no fallback). The widget must pass the page’s CMS UUID.
- Does **not** use the message text, `user_id`, or `conversation_id`.
- Answers: *“you might also like”* relative to the current article.

### 5.2 `query_index` — search by the user’s message

```
GET {CONCORDE_AI_SEARCH_BASE}/search/{concorde_site_id}/{url_encoded_query}?max_age={CONCORDE_MAX_AGE}
     └─ default: https://content-search.internal.example.com
```

| Path / input | ID / value used | Format | Required? | Source |
|--------------|-----------------|--------|-----------|--------|
| `{concorde_site_id}` | site (Site Registry) UUID | UUID | ✅ | brand JSON `concorde_site_id` (or `.env` fallback) |
| `{url_encoded_query}` | the user’s message | URL-encoded text (**not an ID**) | ✅ | last `HumanMessage` in state |
| `max_age` | age filter | e.g. `90d` | optional | `settings.concorde_max_age` |

- Does **not** take `content_id` — it searches by the query string, not by article.
- Does **not** use `user_id` or `conversation_id` (no server-side query rewriting for follow-ups yet).
- Answers: *“articles matching what the user asked”*.

### 5.3 Side-by-side

| | `get_related` | `query_index` |
|--|---------------|---------------|
| Host setting | `CONCORDE_API_BASE` | `CONCORDE_AI_SEARCH_BASE` |
| Path | `/v2/consumer/{site_uuid}/related/{content_id}` | `/search/{site_uuid}/{query}` |
| Site ID | Site Registry UUID | Site Registry UUID |
| Second segment | **`content_id`** (article UUID) | **query text** (not an ID) |
| Uses message text? | ❌ | ✅ |
| Uses `content_id`? | ✅ (required) | ❌ |
| Empty when… | `content_id` missing | query blank |
| Writes to state | `related_articles` | `query_index_articles` |

> **Both segments after the host differ in kind:** in `get_related` the `{content_id}` is an **article** UUID; in `query_index` the matching segment is **free text**, not a UUID. Only the **site** segment (`concorde_site_id`) is the same type in both.

### 5.4 The shared resolver

Both calls run the incoming site value through `_voltron_site_id()` so a slug never reaches the Content Search API:

```12:18:ai_assistant_service/src/ai_assistant/services/concorde.py
def _voltron_site_id(site_id: str, concorde_site_id: str | None = None) -> str:
    voltron = (concorde_site_id or "").strip() or settings.concorde_site_id
    return site_id if _is_uuid(site_id) else voltron
```

- Pass a **UUID** as `site_id` → used directly.
- Pass a **slug** (`brand_alpha_us`) → ignored for the Content Search API; the brand’s `concorde_site_id` (or `.env` default) is used instead.

### 5.5 Article `id` in the responses

Each item in `recommendations.related[]` and `recommendations.query_index[]` carries an article `id` (CMS/the Content Search API UUID), mapped by `_map_article()`. That `id` is the **same kind of value** you would later pass back as a `content_id` to `get_related`.

---

## 6. Where each ID is used in DynamoDB (persistence)

| Table | Partition key (PK) | Sort key (SK) | Other IDs stored |
|-------|--------------------|---------------|------------------|
| `ai_assistant_conversations` | `user_id` | `conversation_id` | `site_id` |
| `ai_assistant_messages` | `conversation_id` | `message_id` (ULID) | — |

(Persistence is off by default: `PERSISTENCE_ENABLED=false`.)

---

## 7. Where each ID is configured / defaulted

| ID | Default / source | File |
|----|------------------|------|
| `site_id` | `brand_alpha_us` | `ChatRequest`, `settings.site_id_default` |
| `concorde_site_id` (Meridian) | `00000000-0000-0000-0000-000000000001` | `brand_alpha_us.json`, `settings.concorde_site_id` |
| `content_id` (sample) | `00000000-0000-0000-0000-000000000002` (Lucid Gravity) | `scripts/run_chat.py`, tests |
| `conversation_id` | `uuid4()` if absent | `context_store.ensure_conversation_id` |
| `message_id` | `ULID()` | `models/message.new_message_id` |

---

## 8. Common mistakes to avoid

1. **Sending the slug to the Content Search API.** `brand_alpha_us` will not work against the Content Search API — it must resolve to the Site Registry UUID. `_voltron_site_id()` handles this; don’t bypass it.
2. **Expecting related articles without `content_id`.** No `content_id` → `get_related` returns `[]` (CSV fallback was removed).
3. **Confusing `content_id` with `concorde_site_id`.** One is an **article** UUID (CMS), the other is a **site** UUID (Site Registry). Both are UUIDs but occupy different path segments:
   - `get_related`: `/v2/consumer/{concorde_site_id}/related/{content_id}` — uses **both**
   - `query_index`: `/search/{concorde_site_id}/{query}` — uses the **site** UUID only
4. **Treating our `conversation_id` as the Content Search API's.** They are independent; Phase 2 never sends a conversation id to the Content Search API.
5. **Reusing `user_id` as identity for logic.** It only drives persistence; no brand/LLM behavior depends on it.

---

## 9. External systems that mint IDs

| System | Mints | Notes |
|--------|-------|-------|
| **Site Registry** | `site_id` (UUID) → our `concorde_site_id` | MediaCo site registry; UUID per brand/locale |
| **CMS (CMS)** | `content_id` / article `id` | Article UUIDs; equals CSV `ITEM_ID` |
| **Our service** | `conversation_id` (uuid4), `message_id` (ULID) | Session + message identity |
| **Frontend/widget** | `user_id` | Reader/device identity |

---

*Generated from a review of `ai_assistant_service/src` (`api/schemas.py`, `api/routes.py`, `state.py`, `services/concorde.py`, `services/brand_config.py`, `services/context_store.py`, `models/*`, brand JSONs) and internal content-search notes (not included).*
