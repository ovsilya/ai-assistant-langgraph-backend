# Diagrams

Click a preview for the full-size image. The interactive HTML version has both boards plus the API contract, data model, Datadog metrics, deployment pipeline and design choices.

These diagrams show the **phase 2 design**. It builds on the code in this repository and adds SSE token streaming, follow-up suggestions running in parallel with the output guardrail, and a LangSmith evaluation suite.

### Architecture board
The widget on top, the LangGraph backend flow in the middle, the data layer and observability on the left, graph state and external services (config, content search, AI gateway) on the right, agent observability and deployment at the bottom

<a href="png/architecture-board.png"><img src="png/architecture-board.png" width="720" alt="Architecture board: frontend, LangGraph backend flow, data layer, observability, graph state, external services, deployment"></a>

### Evaluation board
Evaluation concepts on the left; workflow evaluation, targets and metrics, two datasets, 14 evaluators and 3 experiments in the middle; LangSmith tracing and scores on the right, with loops from traces and failing cases back into the datasets

<a href="png/evaluation-board.png"><img src="png/evaluation-board.png" width="720" alt="Evaluation board: datasets, evaluators, experiments and LangSmith tracing"></a>

[Open the interactive version](https://ovsilya.github.io/ai-assistant-langgraph-backend/diagrams/ai-assistant-architecture.html)

---

**Anonymized.** The publisher, its magazine brands and internal service names are replaced by generic names (fictional brands such as Brand Alpha and Brand Beta, config service, content search, site registry, CMS, AI gateway).
