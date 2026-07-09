# Scope Item 2 — Session history & logging: Phase 1 vs Phase 2

This document compares **Phase 1 (MVP)** chat persistence with **Scope Item 2** (upgraded session history, logging, retention, and user-facing controls). It proposes a **Phase 2 relational schema** that **extends** today’s AlloyDB tables rather than replacing them.

**Phase 2 assumption (this revision):** visitors are **unauthenticated only**. Identity is **cookie / stable anonymous visitor id**; there is **no** logged-in user, **no** merge-on-login, and **no** authenticated-user columns in the Phase 2 proposal below.

**Code / docs basis:** `services/alloydb_chat_history_service.py`, `services/alloydb_cached_chat_service.py`, `config.py` (`max_conversation_history`, `use_redis`, `use_alloydb`), `archive/scripts/queries/docs/SCHEMA_BIGQUERY_AND_ALLOYDB.md`.

**Boundary:** Product **telemetry** (latency distributions, CTR, funnels) may also live in **BigQuery** (see `SCOPE_ITEM_8_TELEMETRY_GAP_ANALYSIS.md`). Scope Item 2 asks for **session logging** tied to chat—you can store **authoritative** rows in AlloyDB next to messages and still **mirror** aggregates to BigQuery for analytics retention.

---

## 1) Phase 1 (MVP) — what exists today

| Area | Phase 1 behavior |
|------|------------------|
| **AlloyDB** | **`conversations`** + **`messages`** when `USE_ALLOYDB=true`. One `conversation_id` (UUID) per thread; `user_id` is a **single text key** (no built-in anonymous vs authenticated distinction in DDL). |
| **Redis** | Optional hot cache (`USE_REDIS=true`). Recent messages cached for fast reads; **window = `max_conversation_history`** (default **50** in config). AlloyDB remains source of truth. |
| **Message body** | User + assistant `content` stored. Assistant rows store **`recommendations_json`**, **`followups_json`**, **`model_provider`**, **`model_name`**, **`page_url`**. |
| **List history** | `get_user_conversations(user_id)` returns **all** conversations for that `user_id`, ordered by `last_message_at` (no server-side “last 10” cap in the service snippet; UI/API may limit). |
| **Per-thread read** | `get_conversation_history(session_id)` loads last **N** messages (`max_conversation_history`) for LLM context. |
| **Delete** | `delete_session(session_id)` removes one thread (messages + conversation). **No** built-in “delete all my data” for a user in one call. |
| **Retention** | **Not encoded** in schema (no `retention_tier`, `purge_after`, or TTL columns). |
| **Intent / guardrail / errors / latency / click-through** | **Not first-class columns** on `messages`; some signal may exist indirectly in content or JSON blobs, but **not formalised** for reporting or UI. |

**Phase 1 schema (summary)** — unchanged from production DDL today (**full** column tables in **§4.1–4.2**; **full Phase 2** tables in **§4.3–4.4**):

- **`conversations`:** `conversation_id`, `user_id`, `brand`, `namespace`, `created_at`, `last_message_at`, `message_count`, `title`, `last_message_preview`, `last_page_url`
- **`messages`:** `message_id`, `conversation_id`, `role`, `content`, `created_at`, `page_url`, `recommendations_json`, `followups_json`, `model_provider`, `model_name`

---

## 2) Scope Item 2 — Phase 2 requirements (summary, anonymous-only)

| Requirement | What Phase 2 must deliver |
|-------------|---------------------------|
| **Persistent history for the anonymous visitor** | Same **stable anonymous id** (cookie-backed) must retrieve **full conversation history** for that visitor across **return visits** and **tabs/devices** that share that id. (No account; scope is the visitor key.) |
| **Session logging (formalised)** | Beyond raw messages: **intent** per message, **recommendations vs clicks**, **guardrail** outcomes, **errors / fallbacks**, **latency per request**. |
| **Retention** | Policy for **anonymous** data (e.g. 90 days row TTL in operational store). **Encode** in data model + jobs, not only docs. Longer-lived **aggregates** can remain in the warehouse per analytics policy. |
| **User-facing history UI** | List past threads for this visitor, **resume**, **delete** history; V1 spoke of “**last 10 conversations**” — confirm product cap vs “load more”. |

**Out of scope for this Phase 2 schema:** authenticated users, cross-account merge, and retention tiers that depend on login state. If login is added later, extend the model (separate doc) rather than over-building now.

---

## 3) Phase 1 vs Phase 2 — gap table

| Topic | Phase 1 (MVP) | Phase 2 (Scope Item 2, anonymous-only) |
|-------|----------------|----------------------------------------|
| **Identity** | Single `user_id` text; no explicit “visitor” semantics in DDL | **`user_id` = stable anonymous visitor id** (cookie); optional extra columns only if you split “display key” from storage (usually unnecessary). |
| **Cross-return history** | Works if the same `user_id` is supplied on every request | **Guarantee** stable id issuance and propagation from edge → API → AlloyDB. |
| **Intent** | Not stored per message | **Per message** (or per user turn) classification fields |
| **Recs vs clicks** | Recommendations embedded on assistant message | **Structured** “shown vs clicked” (ids, positions, timestamps) for analytics and UI |
| **Guardrail / error / latency** | Not formal columns | **Per message** or **per request** logging fields (and optionally BigQuery events per Scope Item 8) |
| **Retention** | None in DB | **Tier** (anonymous policy) + **purge job** + possible **soft delete** before hard delete |
| **Delete / export** | Delete one conversation | **Bulk delete** for this visitor id; resume = open existing `conversation_id` |
| **UI “last 10”** | Not enforced in DB | **Product rule** — API `LIMIT` + pagination |

---

## 4) Phase 2 data schema (proposal) — extends Phase 1

Design principles:

1. **Keep `conversations` and `messages`** as the core tables so existing services keep working; add columns and **nullable** fields first, then backfill.
2. Put **high-volume optional telemetry** on **`messages`** (one row already exists per user/assistant turn) where it is **naturally scoped** to a message or assistant reply.
3. Put **thread-level** retention and soft-delete metadata on **`conversations`**.
4. Use **BigQuery** (or a sibling table) for **long-term aggregates** if AlloyDB rows are purged per retention.

Types and Phase 1 meanings match [`SCHEMA_BIGQUERY_AND_ALLOYDB.md`](SCHEMA_BIGQUERY_AND_ALLOYDB.md) §2. **Phase 2** columns below are the proposal; append them in migrations unless you intentionally reorder.

**Identity (Phase 2, this doc):** `user_id` is the **stable anonymous visitor id** (cookie-backed). No authenticated-user columns.

The **Origin** column in §4.3–4.4 marks each field as Phase 1 vs Phase 2 for readability; it is **not** part of the physical schema.

---

### 4.1 Phase 1 — full `conversations` table

| Column | Type | Meaning |
|--------|------|---------|
| `conversation_id` | UUID (PK) | Same id as API “session” / chat thread id (UUID string in API) |
| `user_id` | TEXT NOT NULL | Thread owner key (Phase 1: opaque text; Phase 2 product: stable anonymous visitor id) |
| `brand` | TEXT NOT NULL | Tenant brand (defaults to `"unknown"` if missing at insert) |
| `namespace` | TEXT NULL | Optional tenant namespace |
| `created_at` | TIMESTAMPTZ | Row insert time (conversation start) |
| `last_message_at` | TIMESTAMPTZ | Updated on each new message |
| `message_count` | INTEGER | Incremented on each message; denormalized count |
| `title` | TEXT NULL | Set from first user message preview when still null |
| `last_message_preview` | TEXT NULL | Short preview of latest message |
| `last_page_url` | TEXT NULL | Last known page URL on message append |

**Indexes (Phase 1, from canonical DDL):** `(user_id, last_message_at DESC)`, `(brand, namespace, user_id, last_message_at DESC)`.

---

### 4.2 Phase 1 — full `messages` table

| Column | Type | Meaning |
|--------|------|---------|
| `message_id` | BIGSERIAL (PK) | Surrogate key |
| `conversation_id` | UUID NOT NULL (FK → `conversations.conversation_id`) | Thread reference; ON DELETE CASCADE |
| `role` | TEXT NOT NULL | `user` or `assistant` (CHECK in DDL) |
| `content` | TEXT NOT NULL | Full message body |
| `created_at` | TIMESTAMPTZ | Insert time |
| `page_url` | TEXT NULL | Optional page context |
| `recommendations_json` | JSONB NULL | Assistant: structured recs (e.g. `articles` / `topics`) |
| `followups_json` | JSONB NULL | Assistant: follow-up suggestion list |
| `model_provider` | TEXT NULL | Provider id when logged |
| `model_name` | TEXT NULL | Model id when logged |

**Index (Phase 1):** `(conversation_id, created_at ASC)` for thread reads.

---

### 4.3 Phase 2 — full `conversations` table (Phase 1 + extensions)

| Column | Type | Meaning | Origin |
|--------|------|---------|--------|
| `conversation_id` | UUID (PK) | Same id as API “session” / chat thread id (UUID string in API) | Phase 1 |
| `user_id` | TEXT NOT NULL | Stable anonymous visitor id (cookie-backed) for this deployment | Phase 1 |
| `brand` | TEXT NOT NULL | Tenant brand (defaults to `"unknown"` if missing at insert) | Phase 1 |
| `namespace` | TEXT NULL | Optional tenant namespace | Phase 1 |
| `created_at` | TIMESTAMPTZ | Row insert time (conversation start) | Phase 1 |
| `last_message_at` | TIMESTAMPTZ | Updated on each new message | Phase 1 |
| `message_count` | INTEGER | Incremented on each message; denormalized count | Phase 1 |
| `title` | TEXT NULL | Set from first user message preview when still null | Phase 1 |
| `last_message_preview` | TEXT NULL | Short preview of latest message | Phase 1 |
| `last_page_url` | TEXT NULL | Last known page URL on message append | Phase 1 |
| `retention_tier` | TEXT NOT NULL DEFAULT `'anonymous_default'` | Drives purge job (e.g. `anonymous_90d` when product fixes the tier name) | Phase 2 |
| `retention_purge_after` | TIMESTAMPTZ NULL | Operational row expiry (e.g. `created_at` + policy interval) | Phase 2 |
| `user_deleted_at` | TIMESTAMPTZ NULL | Soft delete: hide from UI; hard-delete after grace period | Phase 2 |
| `last_device_label` | TEXT NULL | Optional coarse client label for support (non-PII) | Phase 2 |

**Indexes:** Phase 1 indexes on `(user_id, last_message_at DESC)` and `(brand, namespace, user_id, last_message_at DESC)`; **add** partial index on `retention_purge_after` WHERE `user_deleted_at IS NULL` for purge workers.

---

### 4.4 Phase 2 — full `messages` table (Phase 1 + extensions)

| Column | Type | Meaning | Origin |
|--------|------|---------|--------|
| `message_id` | BIGSERIAL (PK) | Surrogate key | Phase 1 |
| `conversation_id` | UUID NOT NULL (FK → `conversations.conversation_id`) | Thread reference; ON DELETE CASCADE | Phase 1 |
| `role` | TEXT NOT NULL | `user` or `assistant` (CHECK in DDL) | Phase 1 |
| `content` | TEXT NOT NULL | Full message body | Phase 1 |
| `created_at` | TIMESTAMPTZ | Insert time | Phase 1 |
| `page_url` | TEXT NULL | Optional page context | Phase 1 |
| `recommendations_json` | JSONB NULL | Assistant: structured recs (e.g. `articles` / `topics`) | Phase 1 |
| `followups_json` | JSONB NULL | Assistant: follow-up suggestion list | Phase 1 |
| `model_provider` | TEXT NULL | Provider id when logged | Phase 1 |
| `model_name` | TEXT NULL | Model id when logged | Phase 1 |
| `request_id` | TEXT NULL | Correlate with app logs / BigQuery (`session_id` + time) | Phase 2 |
| `latency_ms` | INTEGER NULL | Server-measured latency for this turn or assistant reply | Phase 2 |
| `intent_classification` | JSONB NULL | Classifier output: label, scores, version | Phase 2 |
| `guardrail` | JSONB NULL | e.g. `triggered`, `type`, `action`, `detail_ref` (avoid raw PII in free text) | Phase 2 |
| `error_or_fallback` | JSONB NULL | e.g. error `code`, `fallback_used` | Phase 2 |
| `recommendations_interaction` | JSONB NULL | Shown vs clicked: article ids, positions, `clicked_at`, `dismissed` | Phase 2 |
| `client_message_id` | TEXT NULL | Client idempotency / dedupe on retry | Phase 2 |

**Index (Phase 1):** `(conversation_id, created_at ASC)` for thread reads.

**Note:** `recommendations_json` remains the **rendered snapshot** from the model; `recommendations_interaction` captures **post-render** engagement (align with BigQuery telemetry if dual-written).

---

### 4.5 Optional: `conversation_participants` (only if multi-user threads ever exist)

Skip for 1:1 visitor–bot unless product requires **shared threads**. Otherwise omit.

### 4.6 Retention & purge

| Mechanism | Description |
|-----------|--------------|
| **Column-driven** | `retention_purge_after` set at insert or on tier change; nightly job `DELETE` or archive to GCS + delete. |
| **Soft delete first** | `user_deleted_at` set on visitor request; grace period; then hard delete messages + conversation. |
| **Analytics** | After purge, **counts** may still exist in **BigQuery** aggregates (Scope Item 8) if policy allows. |

### 4.7 User-facing API (not DDL, but required by scope)

| Capability | Suggested behaviour |
|--------------|---------------------|
| **List** | `GET …/conversations?user_id=<stable_anonymous_id>&limit=10&cursor=…` with `user_deleted_at IS NULL`. |
| **Resume** | Open chat with existing `conversation_id` (already Phase 1). |
| **Delete thread** | Existing `delete_session`. |
| **Delete all** | `UPDATE conversations SET user_deleted_at=now()` (scoped to `user_id`) then async purge; or immediate `DELETE` cascade for that visitor. |

---

## 5) What needs to be built (engineering checklist)

| Workstream | Tasks |
|------------|--------|
| **Schema migration** | Add Phase 2 columns; defaults so Phase 1 code paths keep running. |
| **Stable anonymous id** | Issue / rotate cookie rules; ensure **same `user_id`** on every chat request for that browser profile. |
| **Logging** | Populate `intent_classification`, `guardrail`, `latency_ms`, `recommendations_interaction`, `error_or_fallback` from chat pipeline (server-side). |
| **Retention jobs** | Scheduled purge by `retention_tier` / `retention_purge_after`; metrics on rows deleted. |
| **API + UI** | List / resume / delete for anonymous visitor; confirm **“last 10”** vs pagination with Product. |
| **Privacy** | Retention text in privacy policy; export if required by region. |
| **Cross-link to telemetry** | Align field names with Phase 2 BigQuery events where both systems store the same fact. |

---

## 6) Related docs

| Doc | Use |
|-----|-----|
| [`SCHEMA_BIGQUERY_AND_ALLOYDB.md`](SCHEMA_BIGQUERY_AND_ALLOYDB.md) | Current Phase 1 AlloyDB + BigQuery analytics shapes |
| [`SCOPE_ITEM_8_TELEMETRY_GAP_ANALYSIS.md`](SCOPE_ITEM_8_TELEMETRY_GAP_ANALYSIS.md) | Phase 2 **product** telemetry in BigQuery (complement to per-message logging here) |
| [`../alloydb/ALLOYDB_QUERIES.md`](../alloydb/ALLOYDB_QUERIES.md) | Example SQL on current tables (update after migrations) |

*This proposal is for planning and client clarification; final columns and retention windows require sign-off from Product, Legal, and Data.*
