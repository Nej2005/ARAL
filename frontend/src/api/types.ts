export type QuestionType = "mcq" | "true_false" | "identification";
export type DocStatus = "uploaded" | "extracting" | "ready" | "failed";

export interface Score {
  correct_count: number;
  total: number;
  kind?: string;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  file_type: "pdf" | "pptx" | "ppt";
  status: DocStatus;
  page_count: number;
  page_unit: "page" | "slide" | "section";
  item_count: number;
  reviewer_ids: string[];
  created_at: string | null;
  duplicate?: boolean;
  busy?: boolean;
  size?: number;
  error_code?: string | null;
  error_message?: string | null;
  extraction_progress?: number;
  steps_done?: number;
  steps_total?: number | null;
  outdated?: boolean;
  done?: boolean;
  resumed?: boolean;
}

export interface ReviewerSummary {
  id: string;
  title: string;
  document_count: number;
  item_count: number;
  used_items: number;
  unused_items: number;
  status: "processing" | "ready" | "needs_attention";
  exam_count: number;
  coverage_epoch: number;
  created_at: string | null;
  last_score: Score | null;
}

export interface ReviewerDoc {
  id: string;
  filename: string;
  file_type: string;
  status: DocStatus;
  busy: boolean;
  steps_done: number;
  steps_total: number | null;
  error_code: string | null;
  page_count: number;
  page_unit: "page" | "slide" | "section";
  item_count: number;
  used_items: number;
  exam_count: number;
  shared: boolean;
}

export interface ReviewerDetail extends ReviewerSummary {
  documents: ReviewerDoc[];
}

export interface ScopeDocument {
  document_id: string;
  pages?: [number, number][];
}

export interface Scope {
  documents?: ScopeDocument[];
  topics?: string[];
}

export interface Exam {
  id: string;
  reviewer_id: string;
  status: "generating" | "ready" | "failed";
  types: QuestionType[];
  scope: Scope | null;
  requested_count: number;
  actual_count: number;
  shortfall: number;
  parent_exam_id: string | null;
  all_items: boolean;
  error_code: string | null;
  error_message: string | null;
  busy?: boolean;
  done?: boolean;
  created_at: string | null;
  attempt_count?: number;
  best_score?: Score | null;
  latest_score?: Score | null;
  latest_attempt_id?: string | null;
  in_progress_attempt_id?: string | null;
}

export interface Outline {
  documents: {
    document_id: string;
    filename: string;
    status: DocStatus;
    page_count: number;
    page_unit: "page" | "slide" | "section";
    pages: { page_no: number; title: string | null; item_count: number }[];
  }[];
  topics: { topic: string; topic_key: string; item_count: number; unused_count: number }[];
}

export interface Availability {
  total_items: number;
  used_items: number;
  unused_items: number;
  max_count_for_types: number;
  unused_by_type: Record<QuestionType, number>;
  unused_outside_scope: number;
  all_items_count: number;
}

export interface Choice {
  id: string;
  text: string;
}

export interface Question {
  id: string;
  type: QuestionType;
  prompt: string;
  choices?: Choice[];
}

export interface AnswerRef {
  id: string | null;
  text: string | null;
}

export interface Source {
  quote: string;
  document_id: string | null;
  filename: string | null;
  page_no: number | null;
  location: string | null;
}

export interface Feedback {
  is_correct: boolean;
  your_answer: AnswerRef | null;
  correct_answer: AnswerRef;
  why: string;
  why_yours_is_wrong: string | null;
  source: Source;
  changed_span: { from: string; to: string } | null;
  match_note: string | null;
}

export interface Card {
  attempt_id: string;
  index: number;
  total: number;
  answered: boolean;
  next_unanswered_index: number | null;
  finished: boolean;
  question: Question;
  feedback?: Feedback | null;
  correct_answer?: AnswerRef;
}

export interface Progress {
  answered: number;
  unanswered: number;
  total: number;
  correct_count: number;
}

export interface AttemptStart {
  attempt_id: string;
  exam_id: string;
  attempt_no: number;
  kind: "full" | "mistakes";
  total: number;
  card: Card;
}

export interface AttemptMap {
  attempt_id: string;
  exam_id: string;
  kind: "full" | "mistakes";
  status: "in_progress" | "completed";
  attempt_no: number;
  total: number;
  last_viewed_index: number;
  progress: Progress;
  cards: { index: number; question_id: string; status: "unanswered" | "correct" | "wrong" }[];
}

export interface AnswerResult {
  feedback: Feedback;
  progress: Progress;
  next_unanswered_index: number | null;
  finished: boolean;
}

export interface SummaryCard {
  question_id: string;
  type: QuestionType;
  prompt: string;
  your_answer: AnswerRef | null;
  correct_answer: AnswerRef;
  why: string;
  why_yours_is_wrong: string | null;
  source: Source;
  changed_span: { from: string; to: string } | null;
}

export interface Summary {
  attempt_id: string;
  exam_id: string;
  kind: "full" | "mistakes";
  attempt_no: number;
  correct_count: number;
  answered: number;
  skipped: number;
  total: number;
  percent: number;
  wrong_cards: SummaryCard[];
  skipped_cards: SummaryCard[];
  retry_mistakes: { count: number };
  next_set: { unused_items: number; all_items: boolean };
}
