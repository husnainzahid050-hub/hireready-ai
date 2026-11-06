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
