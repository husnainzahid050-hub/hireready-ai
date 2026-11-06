---
competency: apis_backend
title: APIs and Backend Development
levels: [junior, mid]
---

# APIs and Backend Development

## What interviewers evaluate

- REST fundamentals: resources, HTTP methods, status codes, idempotency.
- Building APIs with a framework such as FastAPI: routing, validation, error handling.
- Authentication vs authorization, and basic API security.
- Working with databases from a backend, and handling failures (timeouts, retries).
- For mid level: async I/O, pagination, rate limiting, caching, observability.

## Question bank

### Junior

#### What is a REST API? Explain the main HTTP methods.

**Strong answer includes:** resources identified by URLs, manipulated with HTTP methods: GET reads,
POST creates, PUT replaces, PATCH partially updates, DELETE removes; stateless requests; JSON
bodies; GET, PUT and DELETE are idempotent, POST is not.

**Common weak answers:** "An API lets two programs talk" with no HTTP specifics.

**Red flags:** uses GET to change data.

#### Which HTTP status codes do you use and when?

**Strong answer includes:** 200 OK, 201 Created, 204 No Content, 400 Bad Request, 401 Unauthorized
(not authenticated), 403 Forbidden (authenticated but not allowed), 404 Not Found, 422 validation
error, 429 rate limited, 500 server error; clients rely on them to handle errors.

**Common weak answers:** knows 200 and 404 only.

**Red flags:** returns 200 with an error message in the body for every failure.

#### What does FastAPI give you over writing a raw HTTP server?

**Strong answer includes:** automatic request validation and serialization with Pydantic models,
type hints for parameters, dependency injection (`Depends`) for auth and DB sessions, async
support, and auto-generated OpenAPI docs.

**Common weak answers:** "It is fast."

**Red flags:** validates inputs manually with long if-statements despite using FastAPI.

### Mid

#### Explain authentication vs authorization, and how you would secure an API.

**Strong answer includes:** authentication proves who you are (tokens, JWT, sessions); authorization
decides what you may do (ownership checks, roles); always check ownership server-side on every
request; use HTTPS, hash secrets, validate input, rate limit, never trust client-side checks, and
avoid leaking stack traces.

**Common weak answers:** treats the two terms as the same.

**Red flags:** relies on hiding IDs in the frontend as the only protection.

#### Your API calls a slow third-party service. How do you make it reliable?

**Strong answer includes:** set timeouts; retry with exponential backoff and jitter only on retryable
errors (429, 5xx); make operations idempotent so retries are safe; circuit breaker or fallback
provider; cache results where valid; run independent calls concurrently; log with request IDs.

**Common weak answers:** "Increase the timeout."

**Red flags:** retries forever with no backoff, amplifying outages.

## Scoring anchors

Example question: "How would you design an endpoint to upload a user's CV?"

### Score 1/5

"Make a POST endpoint that saves the file." No validation or security.

### Score 3/5

"POST multipart endpoint, check the file type and size, save the text to the database." Covers
basics, misses authorization and abuse cases.

### Score 5/5

"A POST multipart endpoint scoped to the user's session. Check auth and ownership, enforce a size
limit, validate both the MIME type and the file's magic bytes, parse server-side without ever
executing the file, store only extracted text, rate limit uploads, and return a clear 4xx error
envelope for each failure case. Log IDs, not file contents." Secure, complete, and user-friendly.

## Resources

- [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/): official step-by-step guide.
- [MDN: Overview of HTTP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Overview): how HTTP works.
- [MDN: HTTP status codes](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status): full reference.
- [OWASP Top Ten](https://owasp.org/projects/top-ten): most critical web security risks.
