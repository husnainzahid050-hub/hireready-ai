export type Verdict = "strong_evidence" | "weak_evidence" | "no_evidence";

export type GapItem = {
  skill: string;
  importance: "must_have" | "nice_to_have";
  competency: string;
  verdict: Verdict;
  evidence_quote: string | null;
  reason: string;
  quote_verified: boolean;
};

export type ScoreComponent = { weight: number; score: number; detail: string };

export type ScoreBreakdown = {
  formula: string;
  must_have: ScoreComponent;
  nice_to_have: ScoreComponent;
  seniority_fit: ScoreComponent;
};

export type Strength = { title: string; why_it_matters: string; evidence_quote: string | null };
export type QuestionGroup = { topic: string; questions: string[] };
export type PrepDay = { day: number; focus: string; tasks: string[]; resource_urls: string[] };

// ------------------------------------------------------------------ ATS readiness
// Mirrors backend/app/schemas/ats.py. Computed in code (services/ats.py), no LLM.

export type AtsStatus = "pass" | "warn" | "fail" | "info";
export type AtsCategory = "readability" | "keywords" | "content";

export type AtsCheck = {
  id: string;
  category: AtsCategory;
  title: string;
  status: AtsStatus;
  weight: number;
  points: number;
  message: string;
  fix: string | null;
  evidence: string | null;
};

export type KeywordHit = {
  term: string;
  importance: "must_have" | "nice_to_have" | "title" | "credential";
  status: "exact" | "alias_only" | "missing";
  matched_as: string | null;
  count: number;
  jd_count: number;
  sections: string[];
  proven_not_searchable: boolean;
  evidence_quote: string | null;
  where_to_add: string | null;
};

export type AtsReport = {
  score: number;
  band: "ready" | "few_fixes" | "fix_first";
  band_label: string;
  formula: string;
  gated: boolean;
  readability: ScoreComponent;
  keywords: ScoreComponent;
  content: ScoreComponent;
  checks: AtsCheck[];
  keyword_hits: KeywordHit[];
  knockouts: string[];
  file_kind: "pdf" | "docx" | "text";
  version: number;
};

export type Analysis = {
  role_title: string;
  match_score: number;
  breakdown: ScoreBreakdown;
  gaps: GapItem[];
  strengths: Strength[];
  likely_questions: QuestionGroup[];
  prep_plan: PrepDay[];
  /** null for analyses saved before the ATS check (the server backfills when it can). */
  ats?: AtsReport | null;
};

export type Profiles = {
  role_title: string;
  seniority: string;
  must_have_count: number;
  nice_to_have_count: number;
  candidate_name: string | null;
};

export type AnalysisEvent =
  | { event: "status"; data: { step: string; message: string } }
  | { event: "profiles"; data: Profiles }
  | { event: "score"; data: { match_score: number; breakdown: ScoreBreakdown } }
  | { event: "gaps"; data: { gaps: GapItem[] } }
  | { event: "ats"; data: AtsReport }
  | {
      event: "insights";
      data: { strengths: Strength[]; likely_questions: QuestionGroup[]; prep_plan: PrepDay[] };
    }
  | { event: "done"; data: Analysis }
  | { event: "error"; data: { code: string; message: string } };

export type SessionOptions = {
  mode: "voice" | "text";
  difficulty: "junior" | "mid";
  interview_type: "technical" | "behavioral" | "mixed";
  email: string | null;
  /** "Email me my report when it's ready" (unticked by default). */
  email_opt_in: boolean;
  /** "Send me 7 daily prep emails" (separate consent, double opt-in by email). */
  reminders_opt_in: boolean;
  consent: boolean;
};

// ------------------------------------------------------------------ interview (Phase 3)

export type QuestionType =
  "technical" | "project" | "gap_probe" | "behavioral" | "role_fit" | "follow_up";

export type Question = {
  id: string;
  /** 1-based; a follow-up shares its parent's order. */
  order: number;
  type: QuestionType;
  competency: string | null;
  text: string;
  is_follow_up: boolean;
};

export type AnswerFeedback = { summary: string; tip: string };

export type InterviewTurn = {
  status: "interviewing" | "completed";
  practice_mode: boolean;
  progress: { answered: number; total_planned: number };
  question: Question | null;
  last_answer: {
    question_id: string;
    transcript: string;
    feedback: AnswerFeedback | null;
    /** Phase 4: only on voice answers. */
    speech_metrics?: SpeechMetrics | null;
  } | null;
  history: { question: Question; answer_text: string }[];
};

// ------------------------------------------------------------------ voice (Phase 4)

export type SpeechMetrics = {
  duration_seconds: number | null;
  speaking_seconds: number | null;
  word_count: number;
  words_per_minute: number | null;
  filler_count: number;
  filler_breakdown: Record<string, number>;
  long_pauses: number;
  longest_pause_seconds: number;
};

// ------------------------------------------------------------------ report (Phase 5)
// Mirrors backend/app/schemas/report.py. Every number is computed in code on the server.

export type HiringVerdict = "strong_yes" | "lean_yes" | "lean_no" | "no";
export type ReadinessBand = "not_ready" | "getting_there" | "interview_ready" | "strong";
export type AnswerLevel = "below_junior" | "junior" | "mid" | "senior";
export type Dimension =
  "relevance" | "technical_accuracy" | "depth" | "structure" | "communication";

export type DimensionScore = {
  key: Dimension;
  label: string;
  weight: number;
  score: number | null; // 1-5; null = not applicable
  justification: string;
  evidence_quote: string | null; // verified against the transcript
};

export type AnswerSpeech = {
  duration_seconds: number | null;
  words_per_minute: number | null;
  filler_count: number;
  filler_breakdown: Record<string, number>;
  long_pauses: number;
};

export type FollowUpReport = {
  label: string;
  question: string;
  answer: string;
  average: number;
  score: number;
  handling: string;
  tip: string;
};

export type QuestionReport = {
  label: string;
  order: number;
  type: string;
  competency: string | null;
  question: string;
  answer: string;
  dimensions: DimensionScore[];
  average: number;
  score: number;
  level: AnswerLevel;
  level_label: string;
  summary: string;
  what_interviewer_wanted: string;
  improved_answer: string;
  tip: string;
  follow_up: FollowUpReport | null;
  speech: AnswerSpeech | null;
};

export type Readiness = {
  score: number;
  band: ReadinessBand;
  band_label: string;
  interview_score: number;
  match_score: number | null;
  formula: string;
  weights: Record<string, number>;
  next_band_label: string | null;
  points_to_next_band: number | null;
  /** ATS readiness from the analysis (not part of the readiness formula); absent on old reports. */
  ats_score?: number | null;
  ats_fixes?: string[];
};

export type Flag = {
  title: string;
  detail: string;
  answer_ref: string;
  question: string;
  quote: string | null;
  quote_verified: boolean;
};

export type EmployerView = {
  verdict: HiringVerdict;
  verdict_label: string;
  score_verdict: HiringVerdict;
  reaction: string;
  green_flags: Flag[];
  red_flags: Flag[];
};

export type Theme = { title: string; detail: string; answer_refs: string[] };

export type SpeechSummary = {
  voice_answers: number;
  average_wpm: number | null;
  pace: "slow" | "ideal" | "fast" | null;
  guidance: string;
  filler_total: number;
  filler_breakdown: Record<string, number>;
  long_pauses_total: number;
  rows: {
    label: string;
    words_per_minute: number | null;
    filler_count: number;
    long_pauses: number;
    duration_seconds: number | null;
  }[];
};

export type Report = {
  version: number;
  state: "ready";
  generated_at: string;
  generated_by: "llm" | "fallback";
  role_title: string;
  readiness: Readiness;
  employer: EmployerView;
  questions: QuestionReport[];
  speech: SpeechSummary | null;
  strengths: Theme[];
  improvements: Theme[];
  open_gaps: string[];
  prep_plan: PrepDay[];
};

/** The code-computed part, streamed before the LLM write-up (SSE `overview`). */
export type ReportOverview = {
  readiness: Readiness;
  score_verdict: HiringVerdict;
  questions: QuestionReport[];
  speech: SpeechSummary | null;
};

export type ShareInfo = { active: boolean; token: string | null; path: string | null };

export type ReportResponse = {
  status: "none" | "generating" | "ready";
  report: Report | null;
  share: ShareInfo;
  email_configured: boolean;
  emailed_at: string | null;
  expires_at: string | null;
  is_demo: boolean;
};

export type SharedReportResponse = { report: Report; expires_at: string | null };

export type ReportEvent =
  | { event: "status"; data: { step: string; message: string } }
  | { event: "overview"; data: ReportOverview }
  | { event: "done"; data: Report }
  | { event: "error"; data: { code: string; message: string } };
