---
competency: sql
title: SQL
levels: [junior, mid]
---

# SQL

## What interviewers evaluate

- Writing correct SELECT queries with filtering, grouping, and joins.
- Understanding the difference between join types and how NULLs behave.
- Aggregation with GROUP BY and HAVING, and window functions for rankings and running totals.
- Basic schema design: primary keys, foreign keys, normalization.
- For mid level: indexes, query plans (EXPLAIN), transactions, and avoiding N+1 query patterns.

## Question bank

### Junior

#### Explain the difference between INNER JOIN and LEFT JOIN.

**Strong answer includes:** INNER JOIN keeps only rows with a match in both tables; LEFT JOIN keeps
all rows from the left table and fills NULLs where there is no match; a common use is finding
customers with no orders via LEFT JOIN plus `WHERE orders.id IS NULL`.

**Common weak answers:** "LEFT JOIN takes the left table" without explaining NULL filling.

**Red flags:** thinks LEFT JOIN removes rows from the right table only; cannot draw an example.

#### What is the difference between WHERE and HAVING?

**Strong answer includes:** WHERE filters rows before grouping; HAVING filters groups after
aggregation (e.g. `HAVING COUNT(*) > 5`); WHERE cannot reference aggregates.

**Common weak answers:** "They are the same but HAVING is for groups" without the order of execution.

**Red flags:** uses HAVING for every filter without understanding the cost.

#### What are primary keys and foreign keys?

**Strong answer includes:** a primary key uniquely identifies a row and cannot be NULL; a foreign key
references another table's key to enforce referential integrity; mentions ON DELETE CASCADE or
restrict behaviour.

**Common weak answers:** "A primary key is the ID column."

**Red flags:** does not know why referential integrity matters.

### Mid

#### When would you use a window function instead of GROUP BY?

**Strong answer includes:** window functions compute values across related rows without collapsing
them (e.g. `ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC)` to get each user's
latest order, running totals with `SUM() OVER`); GROUP BY returns one row per group.

**Common weak answers:** knows the name but cannot give a use case.

**Red flags:** uses self-joins or loops in application code for every ranking problem.

#### A query is slow. How do you investigate?

**Strong answer includes:** run `EXPLAIN ANALYZE` to see the plan; look for sequential scans on large
tables, bad row estimates, or expensive sorts; add an index on filtered/joined columns; check for
N+1 patterns in the application; measure before and after.

**Common weak answers:** "Add an index" without checking the plan.

**Red flags:** suggests indexing every column; no notion of measuring.

## Scoring anchors

Example question: "How would you find each customer's most recent order?"

### Score 1/5

"I would SELECT all orders and look for the latest one." No SQL, no approach for grouping.

### Score 3/5

"GROUP BY customer_id and take MAX(created_at)." Correct for the date, but does not return the
full order row and does not mention joining back or window functions.

### Score 5/5

"Use `ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC)` in a subquery and keep
rows where it equals 1. That returns the full order row. An index on (customer_id, created_at)
keeps it fast, and I would check with EXPLAIN." Correct, complete, considers performance.

## Resources

- [PostgreSQL tutorial](https://www.postgresql.org/docs/current/tutorial.html): official SQL basics.
- [Window functions tutorial](https://www.postgresql.org/docs/current/tutorial-window.html): official introduction.
- [Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html): reading query plans.
- [Indexes](https://www.postgresql.org/docs/current/indexes.html): when and how indexes help.
