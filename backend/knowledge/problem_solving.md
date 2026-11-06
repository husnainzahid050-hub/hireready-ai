---
competency: problem_solving
title: Problem Solving
levels: [junior, mid]
---

# Problem Solving

## What interviewers evaluate

- Understanding the problem: restating it, asking about inputs, outputs, and edge cases.
- Starting with a simple working approach, then improving it.
- Reasoning about time and space complexity (Big-O).
- Choosing appropriate data structures (hash maps, sets, heaps, queues).
- Testing with examples and edge cases, and thinking aloud throughout.

## Question bank

### Junior

#### How do you approach a coding problem you have never seen before?

**Strong answer includes:** restate the problem, clarify constraints and edge cases, work through a
small example by hand, propose a brute-force solution and its complexity, then optimize (often with
a hash map or sorting), write clean code, and test with normal and edge cases while thinking aloud.

**Common weak answers:** "I start coding immediately."

**Red flags:** silent coding with no explanation; ignores edge cases.

#### Find two numbers in a list that add up to a target. Describe your approach.

**Strong answer includes:** brute force checks all pairs in O(n^2); better: one pass with a hash map
from value to index, checking if `target - x` was seen, O(n) time and O(n) space; handles
duplicates and no-solution cases.

**Common weak answers:** stops at the nested loop.

**Red flags:** cannot state the complexity of their own solution.

#### What is Big-O notation and why does it matter?

**Strong answer includes:** describes how runtime or memory grows with input size, focusing on the
dominant term; examples: O(1) dict lookup, O(log n) binary search, O(n log n) sorting, O(n^2)
nested loops; matters when data grows large.

**Common weak answers:** "It measures speed in seconds."

**Red flags:** thinks constant factors define Big-O.

### Mid

#### How would you debug a bug you cannot reproduce locally?

**Strong answer includes:** gather evidence (logs, request IDs, inputs, environment differences),
form hypotheses, add targeted logging or metrics, try to reproduce with production-like data or
config, narrow down by bisecting (e.g. `git bisect`), then add a regression test after fixing.

**Common weak answers:** "I would try random changes until it works."

**Red flags:** no structured hypothesis testing.

#### When would you use a heap or a queue?

**Strong answer includes:** a heap for repeatedly getting the smallest/largest item efficiently (top-k
items, scheduling, Dijkstra), O(log n) push/pop; a queue (FIFO, e.g. `collections.deque`) for
breadth-first search and task processing in arrival order.

**Common weak answers:** knows the names only.

**Red flags:** sorts the whole list repeatedly to get the minimum.

## Scoring anchors

Example question: "Given a list of words, find the most frequent one."

### Score 1/5

"Loop through and count somehow." No concrete approach.

### Score 3/5

"Use a dictionary to count each word, then find the max." Correct and efficient, but no
complexity, ties, or edge cases.

### Score 5/5

"Count with a dict or `collections.Counter` in O(n), then take the max in O(k) for k distinct
words. I'd clarify how to break ties and whether case matters, normalize words first, and handle
an empty list. For top-k instead of top-1, I'd use `Counter.most_common(k)` or a heap."
Clarifies, solves efficiently, states complexity, covers edge cases and extensions.

## Resources

- [MIT 6.006 Introduction to Algorithms](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/): free MIT course.
- [Python TimeComplexity wiki](https://wiki.python.org/moin/TimeComplexity): Big-O of Python operations.
- [collections module](https://docs.python.org/3/library/collections.html): Counter, deque and friends.
