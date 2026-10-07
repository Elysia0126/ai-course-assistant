// Mirrors the FastAPI schemas in backend/app/schemas.

export type CourseColor = "indigo" | "blue" | "emerald" | "amber" | "rose" | "violet" | "cyan" | "slate";

export interface CourseStats {
  document_count: number;
  ready_document_count: number;
  chunk_count: number;
  quiz_count: number;
  deck_count: number;
  due_card_count: number;
  chat_count: number;
}

export interface Course {
  id: string;
  name: string;
  code: string | null;
  term: string | null;
  description: string | null;
  color: CourseColor;
  created_at: string;
  updated_at: string;
  stats: CourseStats;
}

export interface CourseInput {
  name: string;
  code?: string | null;
  term?: string | null;
  description?: string | null;
  color?: CourseColor;
}

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface CourseDocument {
  id: string;
  course_id: string;
  filename: string;
  file_type: "pdf" | "pptx" | "docx" | "md" | "txt";
  size_bytes: number;
  status: DocumentStatus;
  error_message: string | null;
  page_count: number | null;
  chunk_count: number;
  created_at: string;
  processed_at: string | null;
  embedding_signature: string | null;
  /** Indexed with a different embedding model than the one now configured. */
  needs_reindex: boolean;
}

export interface UploadResult {
  documents: CourseDocument[];
  errors: { filename: string; code: string; message: string }[];
}

export interface Chunk {
  id: string;
  chunk_index: number;
  content: string;
  page_number: number | null;
  section: string | null;
  char_count: number;
}

export interface ChunkDetail extends Chunk {
  document_id: string;
  filename: string;
  file_type: string;
}

export type SearchMode = "hybrid" | "vector" | "keyword";

export interface SourceRef {
  index: number | null;
  chunk_id: string | null;
  document_id: string;
  filename: string;
  file_type: string;
  page_number: number | null;
  section: string | null;
  location: string | null;
  snippet: string;
  score?: number | null;
  vector_score?: number | null;
  keyword_score?: number | null;
  cited: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: SourceRef[];
  meta: { provider?: string; model?: string; low_confidence?: boolean; latency_ms?: number };
  created_at: string;
}

export interface ChatSessionSummary {
  id: string;
  course_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatSessionDetail extends ChatSessionSummary {
  messages: ChatMessage[];
}

export interface SearchResponse {
  results: SourceRef[];
  low_confidence: boolean;
  best_vector_score: number;
}

export type QuestionType = "mcq" | "true_false" | "short_answer";
export type Difficulty = "easy" | "medium" | "hard";

export interface QuizQuestion {
  id: string;
  position: number;
  question_type: QuestionType;
  prompt: string;
  options: string[];
  source: Omit<SourceRef, "index" | "cited"> | null;
}

export interface QuizSummary {
  id: string;
  course_id: string;
  title: string;
  difficulty: Difficulty;
  topic: string | null;
  generator: string;
  created_at: string;
  question_count: number;
  attempt_count: number;
  best_score: number | null;
}

export interface QuizDetail extends QuizSummary {
  questions: QuizQuestion[];
}

export interface QuestionResult {
  question_id: string;
  given: string;
  correct: boolean;
  score: number;
  correct_answer: string;
  explanation: string;
  feedback: string;
  source: QuizQuestion["source"];
}

export interface QuizAttempt {
  id: string;
  quiz_id: string;
  score: number;
  correct_count: number;
  total: number;
  results: QuestionResult[];
  created_at: string;
}

export interface Flashcard {
  id: string;
  deck_id: string;
  position: number;
  front: string;
  back: string;
  source: QuizQuestion["source"];
  ease_factor: number;
  interval_days: number;
  repetitions: number;
  lapses: number;
  review_count: number;
  due_at: string;
  last_reviewed_at: string | null;
}

export interface DeckSummary {
  id: string;
  course_id: string;
  title: string;
  topic: string | null;
  generator: string;
  created_at: string;
  card_count: number;
  due_count: number;
  reviewed_count: number;
}

export interface DeckDetail extends DeckSummary {
  cards: Flashcard[];
}

export type Rating = "again" | "hard" | "good" | "easy";

export interface Health {
  status: string;
  version: string;
  database: { status: string; dialect: string };
  vector_store: string;
  llm: { provider: string; model: string };
  embeddings: { provider: string; model: string; dim: number; signature: string };
  limits: { max_upload_mb: number };
}
