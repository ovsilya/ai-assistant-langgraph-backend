# CDN Explained — For Backend & MLE

**Who this is for:** You build APIs, models, and pipelines — not CDN infrastructure.  
**Goal:** Understand what people mean when they say “CDN” in Phase 2 planning, and what is **your** work vs **DevOps’s**.

**Related:** `04_GCP_DEPLOYMENT_PRIMER.md` §8 · `01_SOFTWARE_ENGINEERING_GLOSSARY.md` (CDN entry) · `03_ML_ARCHITECTURE_GCP_AI_ENGINEER_STUDY_GUIDE.md` §3.5

---

## 1. What is a CDN? (30 seconds)

**CDN** = **Content Delivery Network**.

It **saves copies of HTTP responses** (JSON, files, images) on servers **closer to users**. When someone asks for the **same thing again**, the CDN can answer **without calling your backend**.

```text
Request
  → CDN: "Do I already have this answer?"
       YES → return saved copy (fast)
       NO  → call your service → save copy (maybe) → return
```

Your Python service on GKE is still the **source of truth**. The CDN is a **shared copy shelf**, not your database and not Redis.

---

## 2. Simple analogy

| Role | Real system | Analogy |
|------|-------------|---------|
| Your recommendation API | Computes recommendations | **Kitchen** — cooks when needed |
| CDN | Stores recent responses | **Shelf** — hands out the same dish again |
| Redis | Per-user session data | **Guest’s tab at the bar** — personal, not shared |
| `POST /chat` | Every message is unique | **Custom order** — never pre-made on a shelf |

First reader on article X → kitchen cooks → CDN puts JSON on the shelf.  
Next 1,000 readers on article X → shelf serves the same JSON → kitchen may not run.

---

## 3. Phrases you will hear (and what they mean)

These come up in Phase 2 / MediaCo-style work. Plain English below.

### “Submit a request to DevOps for the CDN configuration of the new endpoint.”

**Means:** The **new public URL or path** must be wired into platform infrastructure — load balancer, CDN rules, TTL, purge process, TLS. That is **not** something you turn on in application code.

**Your part:** Describe the endpoint (method, path, whether responses can be shared).  
**DevOps part:** Route traffic and enable caching for that path.

---

### “Pre-caching article recommendations behind a CDN.”

**Means:** **Warm the shelf before users arrive.** When an article publishes, a job or pipeline **calls the recommendation URL once on purpose** so the CDN stores the response. The **first real reader** gets a fast answer instead of waiting on a cold backend call (embedding search, etc.).

**Your part:** Provide a stable URL to call; ensure “same article URL → same JSON” is OK for the product.  
**DevOps / platform part:** CDN is enabled; TTL and purge are defined.

---

### “Concord recommendation endpoint is already CDN-backed.”

**Means:** Recommendation **read** traffic for a given **article URL** can be served from the **CDN copy** after the first request. Repeat page views do not always hit your GKE pods.

**Your part:** Know that latency and load may drop for hot URLs; know that answers can be **briefly stale** until TTL expires or cache is purged.  
**Not the same as:** caching chat — chat is per user and stays on the origin.

---

## 4. Words worth knowing

| Term | Plain meaning |
|------|----------------|
| **Cache hit** | CDN had a saved copy → your service might not run |
| **Cache miss** | CDN had nothing → request goes to your backend |
| **Origin** | Your real service (e.g. recommendation-api on GKE) |
| **TTL** | How long the CDN keeps a copy (e.g. 5 minutes) |
| **Purge** | Clear old copies from the CDN (e.g. after you change rec logic) |
| **Pre-caching / cache warming** | Fill the CDN **before** user traffic |

On Google Cloud the product is **Cloud CDN** (AWS equivalent: **CloudFront**).

---

## 5. What to cache vs what not to cache

| **OK for CDN** | **Not for CDN** |
|----------------|-----------------|
| Static files (widget JS, images) | `POST /chat` — every request is different |
| Recommendations **per article URL** (if slight staleness is OK) | Anything with session, login, or per-user auth |
| Public read-only GET-style APIs with one answer per URL | LLM calls — always hit your service |

**Rule of thumb for backend/MLE:**

```text
Many users, same URL, same JSON  →  CDN maybe yes
One user, one conversation       →  CDN no  (use DB / Redis)
```

---

## 6. CDN vs Redis vs your database

All three can “store something,” but they solve different problems.

| | **CDN** | **Redis** | **Database (AlloyDB, etc.)** |
|---|---------|-----------|------------------------------|
| **Shared by many users?** | Yes | Sometimes | Yes, but not for edge speed |
| **Typical data** | Saved HTTP responses | Hot session / chat window | Durable history |
| **You configure in code?** | Rarely (maybe `Cache-Control` headers) | Often | Yes |
| **Phase 2 example** | Rec JSON for article URL X | Last N messages in session | Full conversation history |

---

## 7. Your job vs DevOps’s job

| **You (backend / MLE)** | **DevOps / platform** |
|-------------------------|------------------------|
| Endpoint logic and JSON shape | Which hostnames/paths use CDN |
| Decide if “same URL = same answer” is acceptable | TTL, purge runbooks |
| Optional: response headers (`Cache-Control`) | Load balancer, DNS, TLS |
| Tests and eval when rec logic changes | Invalidate CDN after deploys |

**You do not “enable CDN” in Python.** You align on what is safe to cache and file a ticket when a new endpoint needs to be on the CDN.

---

## 8. Request path (where CDN sits)

```text
Article page / browser
        ↓
   Cloud CDN  ← saved copies live here
        ↓
   Load balancer
        ↓
   GKE service  ← your FastAPI / recommendation API
        ↓
   Embedding DB, models, etc.
```

Chat (`POST /chat`) usually **skips** the “save on shelf” behavior — it goes to your service every time.

---

## 9. Trade-offs (say this in a meeting)

**Pros**
- Faster responses for popular articles  
- Less load on recommendation / embedding paths  
- Lower cost at scale for repeat reads  

**Cons**
- Cached recommendations can be **slightly out of date** until TTL or purge  
- Wrong cache rules could expose shared data — needs DevOps + product agreement  

**Product question to ask:** *“If two readers see the same article in the same 5 minutes, is it OK if they get identical recommendations from cache?”*

---

## 10. One-liners for standups and interviews

**What is a CDN?**  
*“A layer that saves HTTP responses so repeat requests for the same URL do not always hit our backend.”*

**Why pre-cache recommendations?**  
*“So the first reader after publish is fast — we call the rec URL when the article goes live, not when a human waits on the page.”*

**Why is chat not CDN-cached?**  
*“Every message and session is different — there is no shared shelf answer.”*

**Why a DevOps ticket?**  
*“CDN is platform wiring for a new path — I own the API; they own routing, TTL, and purge.”*

---

## 11. Quick checklist before you agree to CDN for an endpoint

- [ ] Is the response **the same for every user** given the same URL (or same cache key)?  
- [ ] Is **brief staleness** acceptable for the product?  
- [ ] Is it a **read** (`GET`-style), not a write with side effects?  
- [ ] Do we have a **purge plan** when recommendation logic or models change?  
- [ ] Is **chat / session / auth** kept off the CDN?

If any answer is “no” or “unsure,” talk to product and DevOps before assuming CDN helps.

---

*Last updated for Phase 2 / recommendation + chat context (a media-publisher stack on GCP).*
