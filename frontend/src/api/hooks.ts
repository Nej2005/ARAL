import { useQuery } from "@tanstack/react-query";

import { api } from "./client";
import type {
  AttemptMap,
  Availability,
  Card,
  DocumentSummary,
  Exam,
  Outline,
  QuestionType,
  ReviewerDetail,
  ReviewerSummary,
  Scope,
  Summary,
} from "./types";

export const keys = {
  reviewers: ["reviewers"] as const,
  reviewer: (id: string) => ["reviewer", id] as const,
  reviewerExams: (id: string) => ["reviewer", id, "exams"] as const,
  outline: (id: string) => ["reviewer", id, "outline"] as const,
  availability: (id: string, types: QuestionType[], scope: Scope | null) =>
    ["reviewer", id, "availability", types.join(","), JSON.stringify(scope)] as const,
  document: (id: string) => ["document", id] as const,
  exam: (id: string) => ["exam", id] as const,
  attempt: (id: string) => ["attempt", id] as const,
  card: (id: string, index: number) => ["attempt", id, "card", index] as const,
  summary: (id: string) => ["attempt", id, "summary"] as const,
};

export function useReviewers() {
  return useQuery({
    queryKey: keys.reviewers,
    queryFn: () => api.get<ReviewerSummary[]>("/reviewers"),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "processing") ? 2500 : false),
  });
}

export function useReviewer(id: string | undefined) {
  return useQuery({
    queryKey: keys.reviewer(id ?? ""),
    queryFn: () => api.get<ReviewerDetail>(`/reviewers/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.status === "processing" ? 2000 : false),
  });
}

export function useReviewerExams(id: string | undefined) {
  return useQuery({
    queryKey: keys.reviewerExams(id ?? ""),
    queryFn: () => api.get<Exam[]>(`/reviewers/${id}/exams`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.some((e) => e.status === "generating") ? 2000 : false),
  });
}

export function useOutline(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.outline(id ?? ""),
    queryFn: () => api.get<Outline>(`/reviewers/${id}/outline`),
    enabled: !!id && enabled,
  });
}

export function useAvailability(id: string | undefined, types: QuestionType[], scope: Scope | null, enabled = true) {
  return useQuery({
    queryKey: keys.availability(id ?? "", types, scope),
    queryFn: () => api.post<Availability>(`/reviewers/${id}/availability`, { types, scope }),
    enabled: !!id && enabled && types.length > 0,
    placeholderData: (prev) => prev,
  });
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: keys.document(id ?? ""),
    queryFn: () => api.get<DocumentSummary>(`/documents/${id}`),
    enabled: !!id,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "uploaded" || s === "extracting" ? 1500 : false;
    },
  });
}

export function useExam(id: string | undefined, poll = false) {
  return useQuery({
    queryKey: keys.exam(id ?? ""),
    queryFn: () => api.get<Exam>(`/exams/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (poll && q.state.data?.status === "generating" ? 1500 : false),
  });
}

export function useAttemptMap(id: string | undefined) {
  return useQuery({
    queryKey: keys.attempt(id ?? ""),
    queryFn: () => api.get<AttemptMap>(`/attempts/${id}`),
    enabled: !!id,
  });
}

export function useCard(attemptId: string | undefined, index: number | null) {
  return useQuery({
    queryKey: keys.card(attemptId ?? "", index ?? 0),
    queryFn: () => api.get<Card>(`/attempts/${attemptId}/cards/${index}`),
    enabled: !!attemptId && !!index,
    staleTime: 60_000,
  });
}

export function useSummary(id: string | undefined) {
  return useQuery({
    queryKey: keys.summary(id ?? ""),
    queryFn: () => api.get<Summary>(`/attempts/${id}/summary`),
    enabled: !!id,
    retry: false,
  });
}
