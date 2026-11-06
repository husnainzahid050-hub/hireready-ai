---
competency: nlp_llms
title: NLP and LLMs
levels: [junior, mid]
---

# NLP and LLMs

## What interviewers evaluate

- Core NLP concepts: tokenization, embeddings, sequence models, and Transformers.
- How large language models are used in products: prompting, structured output, tool calling.
- Retrieval-Augmented Generation (RAG): chunking, embeddings, vector search, grounding answers.
- Evaluating LLM systems: hallucination, faithfulness, latency, and cost.
- For mid level: hybrid search, reranking, prompt injection defenses, fine-tuning vs RAG tradeoffs.

## Question bank

### Junior

#### What are embeddings and why are they useful?

**Strong answer includes:** dense vectors that represent meaning so similar texts are close in vector
space; measured with cosine similarity; used for semantic search, clustering, recommendations, and
RAG retrieval; produced by an embedding model, not the chat model.

**Common weak answers:** "Embeddings convert words to numbers" with no notion of semantic similarity.

**Red flags:** thinks embeddings are the same as one-hot encodings or token IDs.

#### Explain Retrieval-Augmented Generation (RAG).

**Strong answer includes:** documents are chunked and embedded into a vector store; at query time the
question is embedded, the most similar chunks are retrieved, and they are inserted into the prompt
so the LLM answers from that context; reduces hallucination and lets you use private or fresh data
without retraining; mentions chunk size and citing sources.

**Common weak answers:** "RAG is when the model searches Google."

**Red flags:** believes RAG retrains the model's weights.

#### What is prompt engineering? Give practical techniques.

**Strong answer includes:** clear instructions and role, delimiters around user data, few-shot
examples, asking for structured output (JSON matching a schema), breaking tasks into steps, setting
low temperature for deterministic tasks; iterate with an evaluation set rather than by feel.

**Common weak answers:** "Writing good questions to ChatGPT."

**Red flags:** no idea how to measure whether a prompt change helped.

### Mid

#### Why use hybrid search instead of pure vector search?

**Strong answer includes:** vector search captures meaning but can miss exact terms (names, error
codes, acronyms like "SQL" or "GIL"); keyword search (BM25/full-text) catches exact matches;
combining them, e.g. with Reciprocal Rank Fusion, improves recall; optionally add a reranker;
measure with hit rate@k and MRR.

**Common weak answers:** "Hybrid is better" with no reason.

**Red flags:** has never evaluated retrieval quality separately from generation.

#### What is prompt injection and how do you defend against it?

**Strong answer includes:** untrusted input (a user message, a retrieved document, a CV) contains
instructions that try to override the system prompt; defenses: treat inputs as data inside clear
delimiters, never give the model more privileges than needed, validate outputs against strict
schemas, keep secrets out of prompts, and test with adversarial examples; no defense is perfect.

**Common weak answers:** "Tell the model to ignore bad instructions."

**Red flags:** passes model output directly into code execution or database queries.

#### When would you fine-tune a model instead of using RAG?

**Strong answer includes:** RAG for knowledge that changes or must be cited; fine-tuning for style,
format, or a narrow task the base model does poorly, or to shrink a model for latency/cost;
fine-tuning needs labelled data and evaluation; often combine both.

**Common weak answers:** "Fine-tuning is always better because it is customised."

**Red flags:** proposes fine-tuning to teach facts that change weekly.

## Scoring anchors

Example question: "How would you reduce hallucinations in an LLM app that answers from company documents?"

### Score 1/5

"Use a bigger model, it will hallucinate less." No grounding strategy.

### Score 3/5

"Use RAG so the model answers from retrieved documents." Correct direction, missing details on
retrieval quality, instructions, or verification.

### Score 5/5

"Use RAG with good chunking and hybrid search so the right passages are retrieved, instruct the
model to answer only from the provided context and say 'I don't know' otherwise, require citations
to chunk IDs, and validate that cited quotes actually exist in the source. Then measure
faithfulness on an eval set and track it over time." Grounding, instructions, verification, and
measurement.

## Resources

- [Hugging Face LLM Course](https://huggingface.co/learn/llm-course/chapter1/1): free course on Transformers and LLMs.
- [Hugging Face Transformers docs](https://huggingface.co/docs/transformers/index): official library documentation.
- [Claude prompt engineering guide](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview): official prompting techniques.
- [OpenAI prompt engineering guide](https://developers.openai.com/api/docs/guides/prompt-engineering): official prompting guide.
- [Supabase AI and vectors guide](https://supabase.com/docs/guides/ai): embeddings and vector search in Postgres.
