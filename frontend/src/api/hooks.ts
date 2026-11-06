import { useQuery, useQueryClient } from "@tanstack/react-query";

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

/**
 * The attempt's card map. With `withCards`, one request also brings every card and puts each one in the card
 * cache, so moving between cards shows them at once instead of waiting on the server each time.
 */
export function useAttemptMap(id: string | undefined, withCards = false) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: keys.attempt(id ?? ""),
    queryFn: async () => {
      const m = await api.get<AttemptMap>(`/attempts/${id}${withCards ? "?cards=true" : ""}`);
      // Kept for the whole session: a card nobody has opened yet must not drop out after the default 5 minutes.
      if (m.card_list) qc.setQueryDefaults(["attempt", id!, "card"], { gcTime: Infinity });
      for (const c of m.card_list ?? []) {
        // A card answered here meanwhile keeps its feedback (an older response must not undo it).
        qc.setQueryData<Card>(keys.card(id!, c.index), (old) => (old?.answered && !c.answered ? old : c));
      }
      return { ...m, card_list: undefined };
    },
    enabled: !!id,
  });
}

/** One card. Cards change only through this app (answering updates the cache; finishing invalidates it). */
export function cardQuery(attemptId: string, index: number) {
  return {
    queryKey: keys.card(attemptId, index),
    queryFn: () => api.get<Card>(`/attempts/${attemptId}/cards/${index}`),
    staleTime: Infinity,
  };
}

export function useCard(attemptId: string | undefined, index: number | null) {
  return useQuery({ ...cardQuery(attemptId ?? "", index ?? 0), enabled: !!attemptId && !!index });
}

export function useSummary(id: string | undefined) {
  return useQuery({
    queryKey: keys.summary(id ?? ""),
    queryFn: () => api.get<Summary>(`/attempts/${id}/summary`),
    enabled: !!id,
    retry: false,
  });
}
