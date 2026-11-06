"use client";

import { useParams } from "next/navigation";

import { AnalysisView } from "@/components/analysis-view";

export function AnalysisRoute() {
  const { id } = useParams<{ id: string }>();
  return <AnalysisView sessionId={id} />;
}
