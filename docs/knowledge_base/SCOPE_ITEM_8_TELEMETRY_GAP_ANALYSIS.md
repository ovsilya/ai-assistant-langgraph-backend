# Scope Item 8 — Telemetry: simple comparison

Scope Item 8 = full Assistant telemetry in **BigQuery**, **≤ ~5 min** visibility, **Looker** dashboard, client + server instrumentation. **Phase 1** was the **MVP / initial rollout**: enough telemetry to test the app in production with a smaller event set and earlier `event_type` names. **Phase 2** is the **upgrade**: expanded event types, renamed events, richer properties, and stricter contracts. This file contrasts Phase 1 with Phase 2 and lists what still needs to be built.

*Out of scope here:* widget code not under `backend/ai_assistant`, the vendor team repos, Looker assets.

---

## 1) What’s already in place

| Layer | What exists |
|--------|-------------|
| **API** | `POST /analytics/event` and `POST /analytics` — any `event_type` + body fields; extras go to `event_payload` (`extra = "allow"`). |
| **Enrichment** | Server adds `event_id`, `inserted_at`, IP, `user_agent`, `browser_type`, `device_type`, `environment`, etc. |
| **BigQuery** | Streaming inserts to `ai_assistant_events` (project/dataset/table from env). Buffered flush (default **10s** batching). |
| **AlloyDB** | Chat **content** + metadata (`conversations`, `messages`) — good for transcript metrics, **not** the same as the product event bus. |
| **Docs / SQL** | `SCHEMA_BIGQUERY_AND_ALLOYDB.md`, `BIGQUERY_QUERIES.md` — examples reflect **Phase 1 (MVP)** names like `prompt_query`, `article_click`, `latency` (not the Phase 2 names below). |

**Bottom line:** the **pipe** from client → BQ is there. There is **no** fixed Phase 2 event catalog, **no** validation of `event_type`, and **no** confirmed automatic server emits from the chat path (only “whatever the client posts”).

---

## 2) Phase 2 event schema (target)

Summary table from the scope. **Detailed BigQuery layout, column list, and per-event Phase 1 vs Phase 2 status** are in **§4**.

| Event | What it’s for | Key properties (scope) |
|--------|----------------|---------------------------|
| `assistant_session_start` | User opens Assistant or starts search | `user_id`, `auth_state`, `brand`, `page_url`, `device_type`, `referral_source`, `timestamp` |
| `assistant_session_end` | User closes or navigates away | `session_id`, `duration`, `message_count`, `articles_clicked`, `products_clicked` |
| `assistant_query_submitted` | Message or suggested question | `session_id`, `query_text`, `query_source` (typed/suggested/voice), `is_followup`, `intent_classification` |
| `assistant_response_rendered` | AI response shown | `session_id`, `response_type`, `article_count`, `product_count`, `latency_ms`, `model_used` |
| `assistant_article_impression` | Article card shown | `session_id`, `article_url`, `position`, `recommendation_source` |
| `assistant_article_click` | Article card clicked | `session_id`, `article_url`, `position`, `time_to_click_ms` |
| `assistant_product_impression` | Product card shown | `session_id`, `product_id`, `position`, `affiliate_network` |
| `assistant_product_click` | Product card clicked | `session_id`, `product_id`, `position`, `affiliate_url` |
| `assistant_signin_prompt_shown` | Sign-in prompt shown | `session_id`, `trigger_reason` |
| `assistant_signin_prompt_clicked` | User clicks sign-in prompt | `session_id`, `trigger_reason` |
| `assistant_history_accessed` | Opens conversation history | `session_id`, `conversations_shown` |
| `assistant_guardrail_triggered` | Response filtered / redirected | `session_id`, `guardrail_type`, `trigger_query` |
| `assistant_error` | Error state | `session_id`, `error_type`, `error_message`, `recovery_action` |
| `search_query_submitted` | Conversational search | `session_id`, `query_text`, `result_count`, `search_type` |
| `search_result_click` | Search result clicked | `session_id`, `article_url`, `position`, `result_score` |

**Delivery (scope):** widget = UI events; chat backend = classification, guardrails, latency, model — **both** into BigQuery.

---

## 3) What needs to be added

| Area | Gap |
|------|-----|
| **Instrumentation** | Emit **all** rows above from the right place (F = frontend, B = backend). SQL docs today still assume the **Phase 1 (MVP)** event set, not the full Phase 2 catalog. |
| **Naming** | Adopt Phase 2 `event_type` strings (or a **mapping view** from old → new so old dashboards don’t break during migration). |
| **Session model** | Clear rules for `session_id` / start / end and how counts on `assistant_session_end` align with AlloyDB / UI. |
| **Impressions** | Article + product **impression** events — required for real **CTR**; clicks alone are not enough. |
| **Server trust** | Latency, model, intent, guardrails should come from **backend** where possible, not only the browser. |
| **Governance** | Legal on `query_text`, `trigger_query`, `error_message`; optional hashing/redaction. |
| **Validation** | Contract per event (required fields, types); optional CI / JSON schema. |
| **SLA proof** | Measure insert lag (`inserted_at` vs `event_timestamp`); handle buffer-full drops — scope asks **≤ 5 minutes**. |
| **Dashboard** | Looker (or equivalent) with scope metrics — **not in this repo**; needs views + ownership. |
| **Documentation** | “Trigger → event” catalog (scope assigns to the vendor team); update **`BIGQUERY_QUERIES.md`** after names are live. |

---

## 4) Phase 2 data schema (BigQuery) — client clarification

*Suitable to share with the client as a **data schema clarification**: it states the target BigQuery shape and distinguishes **Phase 1** (MVP-era production telemetry) from **Phase 2** (upgraded event contracts and emitters still to standardise).*

**Purpose of this section:** describe the **final Phase 2 shape** as it will live in **BigQuery** (single event table + JSON payload), and mark what **Phase 1** (today’s ingestion plus MVP `event_type` / payload patterns) already covers versus what remains **Phase 2** (scope contract, new naming, and additional event types).

**Phase labels used in the tables below:**

| Label | Meaning |
|-------|--------|
| **Phase 1** | **MVP / initial rollout (in production today):** BigQuery columns and ingestion are live; **`event_type` strings and `event_payload` keys** in internal SQL examples reflect the **first-wave** instrumentation used to test the app (smaller event set, older names such as `prompt_query`). Not schema-validated. |
| **Phase 2** | **Scope target:** the contractual `event_type` name and full property set from Scope Item 8; emitters, validation, and dashboard contracts still to finish. |

*The backend does **not** validate `event_type` or JSON keys; production reality should be confirmed with `SELECT event_type, COUNT(*) …` in BigQuery.*

### 4.1 Physical table — `ai_assistant_events` (Phase 2 warehouse target)

All Phase 2 events are stored as **one row per occurrence** in this table (unless MediaCo later adds staging views or derived tables). Environment defaults: `BIGQUERY_PROJECT_ID` / `BIGQUERY_DATASET` / `BIGQUERY_TABLE` (e.g. `my-gcp-project.analytics.ai_assistant_events`).

| Column | Type | Phase 2 role | Phase 1 / Phase 2 |
|--------|------|----------------|-------------------|
| `event_id` | STRING | Unique row id | Phase 1 — server-generated |
| `event_type` | STRING | **Phase 2 event name** (e.g. `assistant_query_submitted`) | Phase 1 — column exists and stores any string. Phase 2 — canonical Phase 2 `event_type` list not yet required by the API |
| `event_timestamp` | TIMESTAMP | Client event time (`timestamp` in API) | Phase 1 |
| `inserted_at` | TIMESTAMP | Server receipt / enqueue time | Phase 1 |
| `user_id` | STRING | `user_id` on many Phase 2 events | Phase 1 |
| `session_id` | STRING | `session_id` / chat thread id | Phase 1 |
| `is_authenticated` | BOOL | Maps to scope **auth_state** (boolean vs string — align in contract) | Phase 1 |
| `page_url` | STRING | `page_url` where relevant | Phase 1 |
| `brand` | STRING | `brand` | Phase 1 |
| `ip_address` | STRING | Server-derived | Phase 1 |
| `user_agent` | STRING | Raw UA | Phase 1 |
| `browser_type` | STRING | Parsed UA | Phase 1 |
| `device_type` | STRING | `mobile` / `tablet` / `desktop` | Phase 1 |
| `event_payload` | JSON | **All Phase 2 properties not listed above** (and duplicates if explicitly duplicated) | Phase 1 — column stores arbitrary JSON. Phase 2 — agreed keys per `event_type` still to be finalized and enforced |
| `api_version` | STRING | Request metadata | Phase 1 |
| `environment` | STRING | e.g. `production` | Phase 1 |

### 4.2 Cross-event fields — where they live & Phase 1 / Phase 2

| Phase 2 concept (from scope) | Where it lives in BigQuery | Phase 1 / Phase 2 |
|------------------------------|----------------------------|---------------------|
| Wall-clock time of the event | `event_timestamp` | Phase 1 |
| User identifier | `user_id` | Phase 1 |
| Session / conversation id | `session_id` | Phase 1 |
| Authenticated vs anonymous | `is_authenticated` | Phase 1 (treat as **auth_state** boolean unless scope requires a string enum) |
| Brand / site | `brand` | Phase 1 |
| Page context | `page_url` | Phase 1 |
| Device class | `device_type` | Phase 1 |
| Referral / traffic source | `event_payload` (e.g. `referral_source`), or Phase 1 **`traffic_source`** **event_type** in examples | Phase 1 — if sent or MVP example pattern. Phase 2 — `referral_source` contract on `assistant_session_start` |
| Free-text query, article URL, positions, latency, model, counts, errors, etc. | `event_payload` keys per final catalog | Phase 1 — transport exists. Phase 2 — per-event key list and types |

### 4.3 Phase 2 `event_type` catalog — Phase 1 vs Phase 2

Each row is the **contractual event** for Phase 2. **Phase 1 (MVP)** used different **`event_type` names** in internal SQL examples (`prompt_query`, `article_click`, etc.); BigQuery **does not** rename existing rows when Phase 2 names go live — use migration, dual-write, or views if you need continuity.

| Phase 2 `event_type` | Phase 1 (telemetry today) | Phase 2 (contract) | Notes |
|----------------------|---------------------------|---------------------|--------|
| `assistant_session_start` | Phase 1 — top-level columns cover `user_id`, `brand`, `page_url`, `device_type`, and time via `event_timestamp`; `is_authenticated` maps to auth | Phase 2 — emit this `event_type` with `referral_source` and agreed **auth_state** shape | Referral may appear in payload or Phase 1 `traffic_source` patterns until standardised |
| `assistant_session_end` | Phase 1 — **`session_length`**-style events in query docs (different name/shape from Phase 2) | Phase 2 — `assistant_session_end` with `duration`, `message_count`, `articles_clicked`, `products_clicked` | Align session end rules with AlloyDB and UI |
| `assistant_query_submitted` | Phase 1 — **`prompt_query`** / **`widget_prompt`** with partial payload (`query_text`, turns, sources in examples) | Phase 2 — rename and add `is_followup`, `intent_classification`, stable `query_source` enum | Backend should own classification where required |
| `assistant_response_rendered` | Phase 1 — **`latency`** events plus payload fields in examples | Phase 2 — single row with `response_type`, counts, `latency_ms`, `model_used` | Unify latency and response metadata under Phase 2 name |
| `assistant_article_impression` | Phase 1 — not represented in MVP SQL examples | Phase 2 — full contract | Impressions required for CTR |
| `assistant_article_click` | Phase 1 — **`article_click`** in examples | Phase 2 — `time_to_click_ms`, positions, URLs per contract | Extend payload beyond Phase 1 keys |
| `assistant_product_impression` | Phase 1 — not in MVP SQL examples | Phase 2 — full contract | New surface |
| `assistant_product_click` | Phase 1 — not in MVP SQL examples | Phase 2 — full contract | New surface |
| `assistant_signin_prompt_shown` | Phase 1 — not in MVP SQL examples | Phase 2 — full contract | |
| `assistant_signin_prompt_clicked` | Phase 1 — not in MVP SQL examples | Phase 2 — full contract | |
| `assistant_history_accessed` | Phase 1 — not in MVP SQL examples | Phase 2 — full contract | |
| `assistant_guardrail_triggered` | Phase 1 — not in MVP SQL examples | Phase 2 — full contract | Server hook and Legal review on `trigger_query` |
| `assistant_error` | Phase 1 — application logs only; not a standard BQ event in examples | Phase 2 — structured `assistant_error` rows | Policy for `error_message` |
| `search_query_submitted` | Phase 1 — **`search_query`** in examples (partial overlap) | Phase 2 — `search_type`, `result_count`, naming | |
| `search_result_click` | Phase 1 — not in MVP SQL examples | Phase 2 — full contract | Distinct from article card click unless unified with a source dimension |

### 4.4 AlloyDB (reference only — not the telemetry table)

Chat **content** remains in **`conversations`** / **`messages`** (message text, `model_provider`, `model_name`, recommendations JSON). Phase 2 **does not replace** this store; it **complements** it for product analytics. Join / reconcile on **`session_id`** = **`conversation_id`** when ids match.

---

## 5) Related docs

| Doc | Use |
|-----|-----|
| [`SCHEMA_BIGQUERY_AND_ALLOYDB.md`](SCHEMA_BIGQUERY_AND_ALLOYDB.md) | Current BQ row shape + AlloyDB tables |
| [`../bigquery/BIGQUERY_QUERIES.md`](../bigquery/BIGQUERY_QUERIES.md) | Example queries (Phase 1 / MVP event names until Phase 2 lands) |
