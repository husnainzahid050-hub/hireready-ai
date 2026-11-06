"use client";

import { useParams } from "next/navigation";

import { InterviewView } from "@/components/interview/interview-view";

export function InterviewRoute() {
  const { id } = useParams<{ id: string }>();
  return <InterviewView sessionId={id} />;
}
