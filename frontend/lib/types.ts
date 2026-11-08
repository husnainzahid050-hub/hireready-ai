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

export type Analysis = {
  role_title: string;
  match_score: number;
  breakdown: ScoreBreakdown;
  gaps: GapItem[];
  strengths: Strength[];
  likely_questions: QuestionGroup[];
  prep_plan: PrepDay[];
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
  email_opt_in: boolean;
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
