---
competency: data_handling
title: Data Handling with pandas and NumPy
levels: [junior, mid]
---

# Data Handling with pandas and NumPy

## What interviewers evaluate

- Loading, cleaning, and exploring tabular data with pandas.
- Handling missing values, duplicates, wrong types, and outliers deliberately.
- Grouping, merging, and reshaping data correctly.
- Vectorized operations with NumPy/pandas instead of Python loops.
- For mid level: memory efficiency, large datasets, reproducible data pipelines.

## Question bank

### Junior

#### How do you handle missing values in a dataset?

**Strong answer includes:** first measure how much is missing and why (`df.isna().sum()`); options
are dropping rows/columns, imputing (mean/median for numeric, mode or "unknown" for categorical),
or adding a "was missing" indicator; the choice depends on the amount and the mechanism; fit
imputers on training data only.

**Common weak answers:** "I drop all rows with NaN" as the default for everything.

**Red flags:** fills missing values with 0 everywhere without thinking about meaning.

#### What is the difference between `merge`, `join`, and `concat` in pandas?

**Strong answer includes:** `merge` is SQL-style joining on columns (inner, left, right, outer);
`join` is a convenience for joining on the index; `concat` stacks frames vertically or
horizontally; checks row counts after merging to catch duplicate keys.

**Common weak answers:** "They all combine dataframes."

**Red flags:** never validates row counts after a merge.

#### Why is vectorization faster than looping over rows?

**Strong answer includes:** NumPy/pandas operations run in optimized C over contiguous arrays, avoiding
Python's per-element overhead; `df.iterrows()` is slow; use column arithmetic, `np.where`,
`.map`, or `groupby().transform`.

**Common weak answers:** "Because pandas is fast."

**Red flags:** uses `iterrows` for simple column math on large data.

### Mid

#### How would you process a CSV that does not fit in memory?

**Strong answer includes:** read in chunks (`chunksize`), select only needed columns (`usecols`), use
smaller dtypes (category, int32), convert to Parquet for columnar reads, or use a database or tools
built for larger-than-memory data; aggregate incrementally.

**Common weak answers:** "Get a bigger machine."

**Red flags:** no awareness of dtypes or column selection.

#### What does `groupby().transform()` do compared to `groupby().agg()`?

**Strong answer includes:** `agg` returns one row per group; `transform` returns a result aligned to
the original rows (e.g. each row's share of its group total), useful for feature engineering.

**Common weak answers:** cannot describe the shape difference.

**Red flags:** merges aggregated results back manually every time without knowing transform.

## Scoring anchors

Example question: "You receive a messy sales CSV. Walk me through cleaning it."

### Score 1/5

"I open it in Excel and fix it." No reproducible process.

### Score 3/5

"Load with pandas, drop NaNs and duplicates, fix column types." Reasonable steps, but no
investigation of why data is messy or validation of results.

### Score 5/5

"Load with pandas and profile it: shape, dtypes, missing values per column, duplicates, value
ranges. Fix types (dates, numerics with commas), standardize categories, decide per column how to
handle missing values, check outliers with domain sense, and write the steps as a function so it is
reproducible. Finally assert invariants like no negative quantities and row counts after merges."
Structured, deliberate, reproducible, validated.

## Resources

- [pandas User Guide](https://pandas.pydata.org/docs/user_guide/index.html): official guide.
- [NumPy: the absolute basics](https://numpy.org/doc/stable/user/absolute_beginners.html): official beginner guide.
