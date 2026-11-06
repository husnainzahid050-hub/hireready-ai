---
competency: system_design
title: System Design Basics
levels: [junior, mid]
---

# System Design Basics

## What interviewers evaluate

- Clarifying requirements and constraints before designing.
- Sketching a sensible architecture: clients, API, database, cache, queues, storage.
- Reasoning about tradeoffs: consistency vs availability, latency vs cost, simplicity vs scale.
- Identifying bottlenecks and failure points.
- For mid level: caching strategies, async processing, data modelling at scale, rate limiting.

## Question bank

### Junior

#### How would you design a URL shortener?

**Strong answer includes:** clarify scale and features first; API to create and resolve links; a
table mapping short codes to URLs with a unique index; generate codes with base62 IDs or random
strings with collision checks; cache popular redirects; return a 301/302 redirect; add rate
limiting against abuse.

**Common weak answers:** jumps to microservices and Kubernetes without basics.

**Red flags:** no persistence or no uniqueness guarantee.

#### What is caching and where would you use it?

**Strong answer includes:** storing results of expensive operations closer to the consumer (browser,
CDN, in-memory, Redis); speeds up reads and reduces load; must handle invalidation and staleness
(TTL); cache keys based on inputs, e.g. a content hash.

**Common weak answers:** "Caching makes it faster."

**Red flags:** caches user-specific data in a shared cache without keys per user.

### Mid

#### When would you introduce a message queue?

**Strong answer includes:** to decouple slow or unreliable work from the request path (emails, video
processing, report generation), absorb traffic spikes, and retry failures; consumers must be
idempotent; adds operational complexity and eventual consistency.

**Common weak answers:** "Queues make systems scalable."

**Red flags:** uses queues for work the user needs answered synchronously.

#### How do you design for failure in a system that calls external AI APIs?

**Strong answer includes:** timeouts and retries with backoff, a fallback provider, graceful degraded
responses, idempotency, rate limits and quotas per user, caching identical requests, streaming to
improve perceived latency, and monitoring error rates and cost.

**Common weak answers:** "The API is reliable so it is fine."

**Red flags:** no limits on per-user usage of a paid API.

## Scoring anchors

Example question: "Design a system that lets users upload a document and get an AI summary."

### Score 1/5

"The frontend sends the document to ChatGPT and shows the answer." No backend, no limits, no security.

### Score 3/5

"Frontend uploads to a backend API, which extracts text, calls an LLM, and stores the summary in a
database." A reasonable flow without tradeoffs or failure handling.

### Score 5/5

"Clarify size limits and expected volume. The backend validates the upload, extracts text, and
stores only what is needed. It calls the LLM with timeouts, retries, and a fallback provider,
streams the summary back, and caches by content hash so duplicates are free. Rate limiting per
user controls cost, long jobs move to a queue, and logs and metrics track latency, errors, and
token usage." Clear flow, explicit tradeoffs, resilience, and cost awareness.

## Resources

- [The System Design Primer](https://github.com/donnemartin/system-design-primer): well-known free guide.
- [MDN: HTTP caching](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Caching): how web caching works.
- [The Twelve-Factor App](https://12factor.net/): principles for scalable services.
