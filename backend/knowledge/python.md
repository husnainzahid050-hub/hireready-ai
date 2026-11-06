---
competency: python
title: Python
levels: [junior, mid]
---

# Python

## What interviewers evaluate

- Fluency with core data structures (list, dict, set, tuple) and when to pick each.
- Writing readable, idiomatic code: comprehensions, context managers, f-strings, PEP 8 naming.
- Understanding of mutability, references, and common pitfalls (mutable default arguments).
- Error handling with specific exceptions rather than bare `except`.
- For mid level: generators, decorators, typing, async/await, packaging, and testing habits.

## Question bank

### Junior

#### What is the difference between a list and a tuple, and when would you use each?

**Strong answer includes:** lists are mutable and tuples are immutable; tuples can be dictionary keys
or set members because they are hashable (if their contents are); tuples signal "fixed record"
intent (e.g. coordinates, function returning multiple values); lists suit collections that grow.
Mentions a concrete example from their own code.

**Common weak answers:** "Tuples use round brackets" with no mention of mutability or hashability.

**Red flags:** claims tuples are always faster in every case without nuance; confuses tuples with sets.

#### How does a dictionary work and what is its lookup complexity?

**Strong answer includes:** key-value hash table; average O(1) lookup, insert and delete; keys must be
hashable; insertion order is preserved since Python 3.7; uses `.get()` with a default or
`collections.defaultdict` / `Counter` for counting.

**Common weak answers:** "It stores key and value" with no complexity or hashability.

**Red flags:** says lookup is O(n) by scanning; uses a list as a dict key without knowing why it fails.

#### What is a list comprehension and when should you avoid one?

**Strong answer includes:** concise syntax to build a list from an iterable with optional filter;
more readable than a loop for simple transforms; avoid when logic is complex, has side effects,
or nests more than two levels; a generator expression avoids building the whole list in memory.

**Common weak answers:** only shows syntax, no judgement about readability.

**Red flags:** uses comprehensions for side effects like printing or appending to another list.

#### Why is a mutable default argument dangerous?

**Strong answer includes:** default values are evaluated once at function definition, so a default
`[]` is shared across calls; fix with `None` and create the list inside the function.

**Common weak answers:** knows it is "bad practice" but cannot explain why.

**Red flags:** has never heard of it and cannot reason about it after a hint.

### Mid

#### Explain generators and when you would use one.

**Strong answer includes:** functions using `yield` return a lazy iterator; values are produced on
demand, so memory stays constant for large or infinite streams (reading a large file line by line,
batching records for an API); generator state is suspended between `next()` calls; mentions
`yield from` or generator expressions.

**Common weak answers:** "It is like a list but faster" without the laziness concept.

**Red flags:** thinks a generator can be iterated multiple times without re-creating it.

#### What is a decorator? Write or describe one you have used.

**Strong answer includes:** a callable that takes a function and returns a wrapped function; used for
cross-cutting concerns like logging, timing, retries, caching (`functools.lru_cache`), auth checks
in web frameworks (FastAPI route decorators); uses `functools.wraps` to preserve metadata.

**Common weak answers:** "The @ symbol above a function" without explaining the wrapping.

**Red flags:** cannot explain what the decorator returns.

#### How does async/await work in Python, and when does it help?

**Strong answer includes:** a single-threaded event loop runs coroutines; `await` yields control
while waiting on I/O so other tasks run; great for many concurrent network calls (e.g. calling
several APIs with `asyncio.gather`); does not speed up CPU-bound work, which needs processes;
blocking calls inside async code stall the whole loop.

**Common weak answers:** "async makes code run in parallel."

**Red flags:** believes async bypasses the GIL for CPU work; calls `time.sleep` inside a coroutine.

## Scoring anchors

Example question: "What is a Python decorator and where have you used one?"

### Score 1/5

"A decorator is the @ thing you put on functions. I think it makes them faster." Inaccurate,
no example, no understanding of wrapping.

### Score 3/5

"A decorator is a function that wraps another function to add behaviour. Flask uses `@app.route`."
Correct definition and one example, but no detail on how it works or why you would write one.

### Score 5/5

"A decorator takes a function and returns a new function that adds behaviour around it. In my
project I wrote a `@retry` decorator that caught timeout errors from an API and retried with
backoff, and used `functools.wraps` so logs still showed the original function name. I also use
`lru_cache` to memoize an expensive lookup." Accurate, explains mechanism, concrete own example,
mentions a subtle detail.

## Resources

- [The Python Tutorial](https://docs.python.org/3/tutorial/): official tutorial covering core language features.
- [asyncio documentation](https://docs.python.org/3/library/asyncio.html): official guide to async/await and the event loop.
- [PEP 8 style guide](https://peps.python.org/pep-0008/): official Python style conventions.
- [collections module](https://docs.python.org/3/library/collections.html): Counter, defaultdict, deque and more.
- [Python TimeComplexity wiki](https://wiki.python.org/moin/TimeComplexity): Big-O of built-in operations.
