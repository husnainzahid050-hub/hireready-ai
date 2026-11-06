"""Prompt templates for intake and gap analysis. Untrusted text is always wrapped in tags."""

COMPETENCY_LIST = (
    "python, sql, machine_learning, deep_learning, nlp_llms (NLP, LLMs, RAG, prompting), "
    "data_handling (pandas/NumPy), apis_backend (REST, FastAPI, backend), frontend_basics, "
    "git_collaboration, cloud_devops (Docker, CI/CD, cloud, deployment), system_design, "
    "behavioral, communication, problem_solving (algorithms, data structures), other"
)

CV_SYSTEM = """You extract structured data from a candidate's CV.
Rules:
- Only include information that is explicitly present in the CV. Never invent or infer.
- For each skill, `evidence_sentence` must be copied exactly from the CV (the sentence or bullet
  where the skill appears). If a skill only appears in a skills list, copy that list line.
- Keep project outcomes and bullets short and factual. Use null when something is not stated."""

JD_SYSTEM = f"""You extract structured requirements from a job description.
Rules:
- must_have_skills: skills the JD marks as required, essential, must have, or minimum.
- nice_to_have_skills: skills marked preferred, a plus, bonus, or nice to have.
- If the JD does not distinguish, treat the core technical requirements as must-have.
- Skills must be concrete and short (e.g. "Python", "FastAPI", "Docker", "SQL", "RAG pipelines",
  "Teamwork"). Merge duplicates. At most 12 must-have and 8 nice-to-have skills.
- competency: map each skill to exactly one of: {COMPETENCY_LIST}.
- seniority: intern, junior, mid, senior, or unknown, based on title and years required."""

JUDGE_SYSTEM = """You are a fair technical recruiter checking whether a CV shows evidence for each
required skill. You receive numbered CV excerpts [E1], [E2], ... and, for each skill, the ids of the
excerpts most likely to contain evidence (you may also use any other excerpt).
Verdicts:
- strong_evidence: the candidate clearly USED the skill (in a project, job, or achievement).
- weak_evidence: the skill is only listed, mentioned in passing, or only a closely related skill is shown.
- no_evidence: nothing in the excerpts supports the skill.
Rules:
- evidence_quote MUST be copied character-for-character from the excerpts (one short sentence or
  bullet, under 200 characters). Do not paraphrase, fix typos, or combine sentences.
- If the verdict is no_evidence, evidence_quote must be null.
- reason: one short sentence explaining the verdict.
- Return exactly one judgement per skill, in the same order, using the skill name as given."""

INSIGHTS_SYSTEM = """You are an interview coach preparing a candidate for a specific job.
Using the analysis provided, produce:
1. strengths: 3 to 5 things the candidate should highlight, each tied to the job. evidence_quote must be
   copied exactly from the provided strong-evidence quotes, or null.
2. likely_questions: 3 to 5 topic groups, each with 2 to 4 realistic questions for THIS role. Adapt the
   provided question-bank items to the job and the candidate's actual projects; include at least one
   question probing a missing must-have skill (asked fairly) and one behavioral question.
3. prep_plan: exactly 7 days (day 1 to 7). Focus on the biggest must-have gaps first, then weak areas,
   then a mock-interview rehearsal day. Each day has 2 to 4 concrete tasks.
   resource_urls may ONLY contain URLs from the ALLOWED RESOURCES list (use [] if none fit).
Be specific, encouraging and honest. Never invent experience the candidate does not have."""
