# **MediaCo AI Assistant Schema**

AI Assistant is a conversational assistant embedded on MediaCo article pages. It consists of a React component inside the web frontend and a dedicated Python/FastAPI backend (**ai-assistant-service**) that runs a LangGraph agent. The agent:

* Loads brand personality from Config-DS (Valkey-cached)  
* Fetches recent conversation history from Valkey/DynamoDB  
* Conditionally calls the Content Search API **`query_index`** (search by user message) and **`get_related`** (related articles for the current page; CDN/the Content Search API API)  
* Invokes ai-gateway (LiteLLM) to generate a response

Reads and writes are persisted asynchronously to DynamoDB. Reader behavior is tracked via GA4 through the web frontend's `dispatchFreEvents()` pipeline; backend operational health is tracked via Datadog.

---

# **1\. API Schemas**

## **1.1 POST /v1/assistant/chat**

**Request Fields**

| Field | Type | Notes |
| ----- | ----- | ----- |
| `user_id` | string | publisher member ID or generated anonymous ID (`anon_{uuid}`) |
| `message` | string | Reader's natural-language message |
| `url` | string | URL of the article currently being read |
| `site_id` | string / null | Brand/site identifier used to load the correct personality from Config-DS. |
| `conversation_id` | string / null | `null` \= new conversation; UUID \= resume thread |

**Response Fields**

| Field | Type | Notes |
| ----- | ----- | ----- |
| `response` | string | LLM-generated answer |
| `recommendations.articles` | object\[\] | Recommended articles |
| `recommendations.articles[].id` | string | Article ID from the Content Search API index |
| `recommendations.articles[].title` | string | Article title |
| `recommendations.articles[].url` | string | Full production URL |
| `recommendations.articles[].description` | string | SEO meta description |
| `recommendations.articles[].image_url` | string / null | Lead image URL  |
| `recommendations.articles[].publish_date` | string / null | ISO8601 publish datetime  |
| `topics` | string\[\] | Suggested topic labels |
| `follow_up_suggestions` | string\[\] | Follow-up question prompts |
| `conversation_id` | string | UUID — carry forward on next turn |
| `title` | string / null | Auto-generated thread title (first turn only) |
| `model_used` | string | LiteLLM model alias as configured in the ai-gateway |
| `guardrail_triggered` | string / null | Type of guardrail triggered |

---

## 

## **1.2 GET /v1/assistant/users/{user\_id}/conversations**

**Response Fields**

| Field | Notes |
| ----- | ----- |
| `conversation_id` | Generated for every thread of conversation |
| `title` | Auto-generated from first user message |
| `preview` | Last message  |
| `created_at` | When the conversation thread was first created |
| `last_message_at` | Timestamp of most recent message; drives sort order |
| `message_count` | Total messages in the thread |

*Ordered by `last_message_at` descending (most recent first).*

---

## **1.3 GET /v1/assistant/conversation/{conversation\_id}**

Returns the full thread in chronological order, capped at 200 messages. 

**Response Fields**

| Field | Notes |
| ----- | ----- |
| `conversation_id` | UUID |
| `title` | Thread title |
| `created_at` | ISO8601 |
| `last_message_at` | ISO8601 |
| `messages` | List of messages  |

---

## **1.4 DELETE /v1/assistant/conversation/{conversation\_id}**

Returns `204 No Content`. Deletes the conversation record and all its messages from DynamoDB, also clears the Redis cache.

---

# **2\. Valkey Schemas**

## **2.1 Conversation Context Cache**

* **Key:** `conv:{conversation_id}`  
* **Type:** List  
* **Write:** `RPUSH {message_json}` (grows with each turn)  
* **Read:** `LRANGE 0 -1` (all messages), `LRANGE -10 -1` (last 10 messages for LLM context)  
* **TTL:** 60 minutes, sliding

---

## **2.2 Conversation List Cache**

* **Key:** `user:{user_id}:convlist`  
* **Type:** String (serialized JSON)  
* **TTL:** 60 minutes

Invalidated on every chat turn and conversation delete.

---

## **2.3 Personality Cache**

* **Key:** `personality:{site_id}`  
* **Type:** String (serialized JSON)  
* **TTL:** 300 seconds

---

# **3\. DynamoDB Schemas**

## **3.1 ai\_assistant\_conversations**

* **Table:** `ai_assistant_conversations`  
* **PK:** `user_id`  
* **SK:** `conversation_id`

| Attribute | Type | Notes |
| ----- | ----- | ----- |
| `site_id` | string | ID passed to Config-DS. |
| `title` | string / null | From first user message |
| `last_message_preview` | string / null | Latest message snippet |
| `created_at` | ISO8601 | Conversation start time |
| `last_message_at` | ISO8601 | Updated on new message |
| `message_count` | number | Incremented on every new message |
| `ttl` | seconds | Rolling: `last_message_at + 90 days` |

---

## **3.2 ai\_assistant\_messages (thread view)**

* **Table:** `ai_assistant_messages`  
* **PK:** `conversation_id`  
* **SK:** `created_at#message_id`

| Attribute | Type | Notes |
| ----- | ----- | ----- |
| `role` | user / assistant | Only these two values |
| `content` | string | Full message body |
| `page_url` | string / null | Page context at message time |
| `recommendations_json` | map / null | Stores article metadata for assistant responses |
| `topics` | list / null | Suggested topic labels |
| `followups` | list / null | Assistant follow-up suggestions |
| `model_provider` | string | ai-gateway |
| `model_name` | string / null | Model ID |
| `created_at` | ISO8601 | Insert time |
| `ttl` | epoch seconds | Fixed at `created_at + 90 days` |
| `guardrail` | string | Type of guardrail triggered a standard response |

---

# **4\. Config-DS Personality Schema**

`ai_assistant_personality` is a **new config type** that would be registered in Config-DS.

## **4.1 Hierarchy**

Config-DS organizes configuration in three levels:

```
Client  (business unit — e.g. MediaCo)
  └── Brand  (publication — e.g. Cosmopolitan)
        └── Site  (edition — e.g. Cosmopolitan UK)
```

1. Register a new consumer: `POST /consumers → { "slug": "ai_assistant" }`  
2. Register the config type with its JSON Schema: `POST /config_types → { "slug": "ai_assistant_personality", "config_schema": { ... } }`

When `ai-assistant-service` calls:

```
GET /merged?ID={site_id}&resource_type=site&config_type= ai_assistant_personality&consumer=ai_assistant
```

Config-DS walks the hierarchy bottom-up and deep-merges the results.

* Lower levels override higher levels on conflict  
* Unset fields inherit from parent levels

---

## **4.2 Merged Schema**

The merged document returned to the service:

| Field | Type | Notes |
| ----- | ----- | ----- |
| `persona_name` | string | Display name of the Assistant for this brand (e.g. `"Cosmo Assistant"`, `"Meridian Advisor"`) |
| `tone` | string | Editorial voice descriptor |
| `system_prompt` | string | Full system prompt injected as `SystemMessage` at the start of every LLM invocation |
| `response_length` | enum string | Response verbosity: `brief` (1–2 sentences), `standard` (short paragraph), `detailed` (multi-paragraph) |
| `content_domains` | string\[\] | Topics this Assistant actively engages with |
| `input_filter_topics` | string\[\] | Queries matching these topics are answered with a standard prompt- Please seek professional advice etc. |
| `output_filter.require_content_grounding` | boolean | Ensures responses reference MediaCo content |
| `output_filter.blocked_language_patterns` | string\[\] | Regex/keyword patterns prohibited in generated responses |
| `output_filter.hallucination_check` | boolean | Scans for unverified claims about named people/products |
| `max_response_tokens` | integer | Passed as max\_tokens in the request to the ai-gateway. |

Example Merged JSON

```json
{
  "persona_name": "string",
  "tone": "friendly / authoritative / playful / witty / warm",
  "system_prompt": "string (max 4000 chars)",
  "response_length": "brief | standard | detailed",
  "content_domains": ["string"],
  "input_filter_topics": ["string"],
  "output_filter": {
    "require_content_grounding": "boolean",
    "blocked_language_patterns": ["string"],
    "hallucination_check": "boolean"
  },
  "max_response_tokens": "integer (default 500)"
}
```

---

# 

# 

# **5\. GA4 Telemetry — Event Schemas**

All events are fired via `dispatchFreEvents()` from `<AiAssistant />` in the web frontend.

**Key Events:**

| Event | Trigger | Properties |
| ----- | ----- | ----- |
| assistant\_session\_start | Fired when the panel opens | session\_id, user\_id, auth\_state, brand, page\_url, device\_type, referral\_source, timestamp |
| assistant\_session\_end | Fired when panel closes or user navigates away | session\_id, duration, message\_count, articles\_clicked |
| assistant\_query\_submitted | Fired for every message sent | session\_id, query\_text, query\_source, is\_followup, intent\_classification |
| assistant\_response\_rendered | Fired when AI response is displayed | session\_id, response\_type, article\_count, latency\_ms, model\_used |
| assistant\_article\_impression | Fired when an article card is displayed | session\_id, article\_url, position |
| assistant\_article\_click | Fired when a recommended article is clicked | session\_id, article\_url, position, time\_to\_click\_ms |
| assistant\_followup\_click | Fired when a follow-up question is clicked | session\_id, article\_url, position, time\_to\_click\_ms |
| assistant\_history\_accessed | Fired when conversation history panel opens | session\_id, conversations\_shown |
| assistant\_error | Fired on frontend errors | session\_id, error\_type, error\_message, recovery\_action |

---

# **6\. Datadog Metrics**

`ai-assistant-service` uses the same DogStatsD primitives as the Content Search API (`concorde/clients/datadog.py`):

* `ping()` for counters  
* `gauge()` for measurements  
* `timed()` as a function decorator for endpoint timing  
* `ddtrace` spans for distributed traces

All metrics are namespaced under `ai_assistant`.

---

## **6.1 Default Tags**

Applied to every metric, following the Content Search API's `default_tags` pattern.

| Tag | Example Value | Notes |
| ----- | ----- | ----- |
| `application` | `ai_assistant` | Service identifier |
| `environment` | `staging` | `production` | Deployment environment |
| `site_id` | `cosmopolitan_uk` | Brand/site for the request |
| `auth_state` | `signed_in` | `anonymous` | Reader auth state |

---

## **6.2 Counters and Gauges**

| Metric | Type | Notes |
| ----- | ----- | ----- |
| `ai_assistant.query_received` | counter | Every POST `/v1/assistant/chat` received |
| `ai_assistant.conversation_started` | counter | First message in a new conversation (`conversation_id` was null on request) |
| `ai_assistant.conversation_deleted` | counter | DELETE `/v1/assistant/conversation/{id}` |
| `ai_assistant.response_latency` | gauge (ms) | End-to-end backend latency, from request received to response sent |
| `ai_assistant.llm_latency` | gauge (ms) | Measures round-trip to the ai-gateway |
| `ai_assistant.tool_call` | counter | Each LangGraph tool invocation; separable by tool via tag |
| `ai_assistant.search_query_index_latency` | gauge (ms) | the Content Search API `query_index` call duration; fires only when the agent invokes the tool |
| `ai_assistant.search_related_latency` | gauge (ms) | CDN `get_related` call duration; fires only when the agent invokes the tool |
| `ai_assistant.guardrail_triggered` | counter | `input_topic_block`, `content_grounding_fail`, `language_pattern_match`, `hallucination_detected` |
| `ai_assistant.error` | counter | Unhandled backend exceptions; `error_source` values: `ai-gateway`, `concorde`, `dynamodb`, `valkey`, `config_ds`; feeds error-rate SLOs |

---

## **6.3 Endpoint Timing (Decorator)**

Following the Content Search API conventions, FastAPI route handlers are decorated with `@datadog.timed(...)`.

| Decorator | Route |
| ----- | ----- |
| `@datadog.timed('api.chat.post')` | `POST /v1/assistant/chat` |
| `@datadog.timed('api.conversations.get')` | `GET /v1/assistant/users/{user_id}/conversations` |
| `@datadog.timed('api.conversation.get')` | `GET /v1/assistant/conversation/{conversation_id}` |
| `@datadog.timed('api.conversation.delete')` | `DELETE /v1/assistant/conversation/{conversation_id}` |

---

## 

## **6.4 Distributed Traces (ddtrace)**

LangGraph execution uses the same ddtrace span **pattern** as the Content Search API's graph code (`concorde/services/conversational_search.py`) for visibility. Assistant does **not** call the Conversational Search HTTP endpoint; the `ai_assistant.tool_call.query_index` span covers the Content Search API **search-by-query** only.

| Span Name | Fires When |
| ----- | ----- |
| `ai_assistant.llm_invoke` | LiteLLM call to the ai-gateway inside LangGraph |
| `ai_assistant.tool_call.query_index` | the Content Search API semantic search |
| `ai_assistant.tool_call.get_related` | CDN related-content lookup |

---

# **7\. Capacity and Load Estimates**

Pilot figures are from the peak month across the 3 pilot brands at 1% traffic. Projected figures apply a 100× multiplier for the complete rollout.

**Baseline**

|  | Pilot | Projected  |
| ----- | ----- | ----- |
| Distinct users / month | 1748 | 174,800 |
| User messages / month | 1884 | 188,400 |

---

## 

## 

## 

## 

## **Expected Load per Component**

Peak \= 3× daily average, accounting for daytime traffic concentration.

| Component | Avg req / sec | Peak req / sec | Notes |
| ----- | ----- | ----- | ----- |
| POST /v1/assistant/chat | \~0.07 | \~0.22 | One request per user message |
| ai-gateway | \~0.22 \+ retry overhead | \~0.88 \+ retry overhead | 4 calls per turn: input classifier \+ main LLM \+ follow ups / topics \+ output guardrail check. Output guardrail failures add a 5th retry call. |
| the Content Search API query\_index | \~0.07 | \~0.22 | One call per chat turn (optional) |
| the Content Search API get\_related | \~0.07 | \~0.22 | One call per chat turn, concurrent with query\_index (optional) |
| DynamoDB writes | \~0.22 | \~0.66 | 3 writes per turn: 2 message rows \+ 1 conversation update |
| Valkey operations | \~0.29 | \~0.88 | \~4 ops per turn: LRANGE \+ 2× RPUSH \+ EXPIRE |

---

## **Ai-gateway Call Breakdown per Turn**

1. **Input classifier**  
   * Checks message against `input_filter_topics`  
   * If triggered, the flow short-circuits (no further LLM calls)  
2. **Main LLM invocation**  
   * Generates the response  
3. **LLM follow-up invocation**  
   * Generates the topics and follow-up questions based on the chat history  
4. **Output guardrail check**  
   * Secondary validation pass covering:  
     * content grounding  
     * blocked language patterns  
     * hallucination detection  
   * If it fails, a **single retry call** is issued with corrective instructions  
   * If retry also fails, a safe fallback response is returned

---

# **8\. Sentry**

ai-assistant-service will use Sentry for exception tracking. Datadog counters signal that errors are happening; Sentry captures the stack trace and requests context needed to debug them.

## **Initialisation**

Follows the Content Search API's established pattern, gated on the `SENTRY_DSN` environment variable so local development requires no configuration. Each event is tagged with the service name, release version, and deployment environment. FastAPI-native integration is enabled so all unhandled exceptions are automatically captured with full request context, without manual instrumentation in each route handler.

## **What Gets Captured**

Every Sentry capture is paired with a corresponding Datadog counter. Datadog drives alerting; Sentry carries the debug detail.

**Captured automatically via the FastAPI integration**: any unhandled exception in a route handler. 

**Captured explicitly at the point of failure**: ai-gateway errors and throttling, the Content Search API call failures, DynamoDB write failures, Redis connection failures, and Config-DS failures.

---

