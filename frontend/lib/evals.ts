/**
 * Eval results for the Engineering page. `eval-results.json` is written by `evals/run_evals.py`
 * (live mode) and committed, so it is read at BUILD time and the page stays static.
 */
import raw from "./eval-results.json";

export type Fraction = {
  k: number;
  n: number;
  value: number | null;
  ci95: [number, number];
};

export type SummaryRow = {
  eval: string;
  metric: string;
  result: string;
  n: string;
  target: string;
  kind: "measured" | "guarantee";
};

export type StepLatency = {
  ok: number;
  p50_s: number | null;
  p95_s: number | null;
  providers: Record<string, number>;
  mean_prompt_tokens: number;
  mean_completion_tokens: number;
};

export type EvalResults = {
  meta: {
    date: string;
    commit: string;
    mode: string;
    models: Record<string, string | null>;
    kb: { files: number; chunks: number };
    dataset_sizes: Record<string, number>;
    llm_calls_total: number;
  };
  summary: SummaryRow[];
  retrieval:
    { mode: string; hit_at_5: Fraction; mrr_at_5: number; failure_rate_at_5: number }[] | null;
  latency: {
    steps: Record<string, StepLatency>;
    per_session: {
      llm_calls: number;
      assumed_answers: number;
      tokens: number;
      cost_usd_list_price: number;
      missing_steps: string[];
    };
    endpoint_llm_time: Record<string, { p50_s: number | null; p95_s: number | null }>;
    prices_checked: string;
    fallback_calls: number;
  } | null;
  headline: {
    retrieval?: { vector: Fraction; hybrid: Fraction };
    evidence?: {
      raw_verbatim: Fraction;
      final_verbatim: Fraction;
      downgraded_by_validator: number;
    };
  };
};

export const evalResults = raw as unknown as EvalResults;

export function pct(f: Fraction | undefined | null): string {
  return f && f.value !== null ? `${Math.round(f.value * 100)}%` : "n/a";
}

export function seconds(v: number | null | undefined, digits = 1): string {
  return typeof v === "number" ? `${v.toFixed(digits)} s` : "n/a";
}
