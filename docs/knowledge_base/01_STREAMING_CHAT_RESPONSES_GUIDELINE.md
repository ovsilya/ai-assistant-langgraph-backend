# Phase 2 Development Guideline: Streaming Chat Responses

## Purpose

Phase 2 includes the requirement: **"Support streaming chat responses."**

In this project, streaming should mean that the assistant answer is delivered to the frontend **progressively while it is being generated**, instead of waiting for the full answer and returning one complete JSON response.

This is primarily a **user experience improvement**. It does not replace the existing recommendation logic, alignment checks, analytics, AlloyDB persistence, Redis caching, or BigQuery analytics flow.

---

## Why Streaming Is Useful

Streaming improves the chat experience by:

- Showing the first part of the answer sooner.
- Making long answers feel faster and more interactive.
- Matching modern chatbot expectations.
- Allowing a future "stop generating" control.
- Avoiding a blank loading state while the LLM is still producing text.

Streaming is **not required for correctness**. The app can still work with normal request/response APIs. The value is that the user sees progress while the answer is being generated.

---

## Current Chat Flow

The current `/chat` endpoint works as a sequential pipeline:

```text
1. Frontend sends user message.
2. Backend loads conversation history.
3. Backend runs recommendation-intent classification.
4. Backend fetches recommendations/topics if needed.
5. Backend runs alignment check.
6. Backend generates the full assistant response.
7. Backend generates follow-up suggestions.
8. Backend saves user + assistant messages to AlloyDB and updates Redis cache.
9. Backend returns one complete ChatResponse JSON.
```

This means the frontend waits until **all** backend work is complete before showing the assistant response.

---

## Target Streaming Flow

In Phase 2, only the **main assistant answer** should stream. The checks and setup work should still happen before streaming begins.

```text
1. Frontend sends user message to a streaming endpoint.
2. Backend loads conversation history.
3. Backend runs recommendation-intent classification.
4. Backend fetches recommendations/topics if needed.
5. Backend runs alignment check.
6. Backend starts streaming the assistant answer.
7. Frontend renders chunks as they arrive.
8. Backend accumulates the full assistant answer while streaming.
9. Backend generates follow-up suggestions after the answer is complete.
10. Backend saves the final user + assistant messages to AlloyDB and updates Redis.
11. Backend sends a final event with metadata.
```

Important: the backend should **not** save every streamed token/chunk as a separate database row. It should save the final complete assistant message once generation finishes.

---

## Impact on Alignment and LLM Checks

Streaming does **not** mean every LLM step should stream.

The current workflow includes LLM-based checks and classifications, such as:

- Whether the user needs recommendations.
- Whether the conversation is aligned/safe.
- Follow-up suggestion generation.
- Main assistant response generation.

Only the **main assistant response generation** is a good candidate for streaming.

### Recommended order

```text
run checks first -> prepare context -> stream final answer -> generate follow-ups -> save final result
```

### Why alignment should stay before streaming

The alignment check is a safety gate. If the app streams first and checks later, unsafe or off-topic content could already be sent to the user before the guardrail finishes.

Recommended behavior:

```text
alignment = yes -> stream normal assistant answer
alignment = no  -> stream safe redirect / reroute answer
```

So the existing sequential guardrail workflow should remain. Streaming changes the **delivery of the final answer**, not the full pipeline.

---

## Recommended API Approach

Create a new streaming endpoint instead of replacing the current `/chat` endpoint immediately.

Recommended endpoint:

```text
POST /chat/stream
```

The current `/chat` endpoint can remain as the non-streaming fallback.

### Recommended transport

Use **Server-Sent Events (SSE)** unless there is a strong reason to use WebSockets.

| Option | Fit for this project |
|--------|----------------------|
| **SSE** | Best default. Simple browser support, good for one-way assistant streaming. |
| **WebSockets** | More complex. Useful if the app needs long-lived two-way real-time communication. |
| **Chunked HTTP** | Possible, but less structured than SSE for frontend event handling. |

SSE is likely sufficient because the main need is backend-to-frontend answer streaming.

---

## Suggested Stream Event Shape

The stream should send structured events so the frontend can distinguish text chunks from final metadata.

Example event sequence:

```text
event: start
data: {"session_id":"..."}

event: token
data: {"text":"Here are "}

event: token
data: {"text":"a few recommendations..."}

event: final
data: {
  "session_id": "...",
  "recommendations": {...},
  "followUpSuggestions": [...]
}

event: done
data: {}
```

For errors:

```text
event: error
data: {"message":"Unable to complete response"}
```

The frontend should append `token` text into the visible assistant message, then use the `final` event to attach recommendations and follow-up suggestions.

---

## Persistence and Storage Behavior

Streaming should preserve the current storage model.

### AlloyDB

AlloyDB remains the source of truth for chat history.

Recommended persistence timing:

```text
1. Save user message when the stream starts, or after checks pass.
2. Stream assistant answer to the frontend.
3. Accumulate the full assistant answer on the backend.
4. After generation completes, save one assistant message row with:
   - final answer text
   - recommendation snapshot
   - follow-up suggestions
   - model metadata
```

### Redis

Redis remains an optional hot cache.

After the final assistant message is saved to AlloyDB, update Redis with the final message object. Do not cache every token.

### BigQuery

BigQuery remains analytics-only. Streaming does not require BigQuery schema changes unless new analytics events are added, such as:

- `chat_stream_started`
- `chat_stream_completed`
- `chat_stream_cancelled`
- `chat_stream_error`

---

## Frontend Development Notes

The frontend should support:

- Starting a streamed request.
- Rendering assistant text incrementally.
- Showing recommendations/follow-ups after the final metadata event.
- Handling stream errors.
- Handling user cancellation / future "stop generating".
- Preventing duplicate messages if the user refreshes mid-stream.

The UI should treat a streamed assistant message as "draft/in progress" until the stream completes.

---

## Backend Development Notes

The backend needs:

- A streaming version of the chat endpoint.
- LLM service support for streamed generation.
- A way to accumulate streamed chunks into one final answer string.
- Final persistence after generation completes.
- Error handling for partial generation.
- Client disconnect handling.
- Deployment/proxy verification that responses are not buffered.

The existing non-streaming endpoint should remain available during rollout.

---

## Infrastructure Considerations

Streaming can be affected by infrastructure between the backend and browser.

Verify:

- The app server supports streaming responses.
- Load balancers/proxies do not buffer SSE responses.
- Timeouts are long enough for LLM generation.
- GKE/Cloud Run/ingress settings allow long-lived HTTP responses.
- The frontend can reconnect or gracefully fail if the stream drops.

---

## Rollout Recommendation

1. Keep current `/chat` as the stable fallback.
2. Add `/chat/stream` behind a feature flag or frontend config.
3. Stream only the main assistant answer first.
4. Keep alignment/recommendation checks sequential before streaming.
5. Save only the final assistant message to AlloyDB/Redis.
6. Add analytics events for stream start, completion, cancellation, and failure.
7. Test with long answers, safety reroutes, recommendation answers, disconnects, and refreshes.

---

## Summary

Streaming chat responses should be implemented as a **delivery-mode upgrade** for the final assistant answer.

It should not bypass the current LLM workflow. The safe Phase 2 model is:

```text
checks + recommendations first
then stream final assistant answer
then generate follow-ups
then persist final message
then send final metadata
```

This keeps the current architecture intact while improving perceived speed and user experience.
