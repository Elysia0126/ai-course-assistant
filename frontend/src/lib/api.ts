import { SSEParser } from "./sse";
import type {
  ChatMessage,
  ChatSessionDetail,
  ChatSessionSummary,
  Chunk,
  ChunkDetail,
  Course,
  CourseDocument,
  CourseInput,
  DeckDetail,
  DeckSummary,
  Difficulty,
  Flashcard,
  Health,
  QuestionType,
  QuizAttempt,
  QuizDetail,
  QuizSummary,
  Rating,
  SearchMode,
  SearchResponse,
  SourceRef,
  UploadResult,
} from "./types";

// Empty = same origin: requests go to this Next.js server's /api proxy (src/app/api/[...path]/route.ts),
// which forwards them to BACKEND_URL. Set NEXT_PUBLIC_API_URL only to call a backend directly (needs CORS).
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
const API_LABEL = API_URL || "the app server";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    if (body?.error) return new ApiError(response.status, body.error.code, body.error.message, body.error.details);
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(response.status, "http_error", `Request failed (${response.status}).`);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api${path}`, {
      ...init,
      headers: init.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    throw new ApiError(0, "network_error", `Cannot reach the API at ${API_LABEL}. Is the backend running?`);
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

/** Upload with progress events (fetch can't report upload progress, XHR can). */
function uploadFiles(courseId: string, files: File[], onProgress?: (fraction: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/api/courses/${courseId}/documents`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", `Cannot reach the API at ${API_LABEL}.`));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadResult);
      else {
        const error = (body as { error?: { code: string; message: string; details?: unknown } } | null)?.error;
        reject(new ApiError(xhr.status, error?.code ?? "http_error", error?.message ?? "Upload failed.", error?.details));
      }
    };
    xhr.send(form);
  });
}

export interface ChatStreamHandlers {
  onMeta?: (data: { session_id: string; user_message_id: string; title: string }) => void;
  onSources?: (data: { sources: SourceRef[]; low_confidence: boolean }) => void;
  onToken?: (text: string) => void;
  onDone?: (data: {
    session_id: string;
    message_id: string;
    content: string;
    cited: number[];
    meta: ChatMessage["meta"];
    created_at: string;
  }) => void;
}

async function streamChat(
  courseId: string,
  body: { question: string; session_id?: string | null; document_ids?: string[] | null },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/courses/${courseId}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(0, "network_error", `Cannot reach the API at ${API_LABEL}. Is the backend running?`);
  }
  if (!response.ok || !response.body) throw await toApiError(response);

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SSEParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const message of parser.push(value)) {
      const data = JSON.parse(message.data);
      switch (message.event) {
        case "meta":
          handlers.onMeta?.(data);
          break;
        case "sources":
          handlers.onSources?.(data);
          break;
        case "token":
          handlers.onToken?.(data.text);
          break;
        case "done":
          handlers.onDone?.(data);
          break;
        case "error":
          throw new ApiError(502, data.code, data.message);
      }
    }
  }
}

export const api = {
  health: () => request<Health>("/health"),

  courses: {
    list: () => request<Course[]>("/courses"),
    get: (id: string) => request<Course>(`/courses/${id}`),
    create: (input: CourseInput) => request<Course>("/courses", json(input)),
    update: (id: string, input: Partial<CourseInput>) =>
      request<Course>(`/courses/${id}`, { method: "PATCH", body: JSON.stringify(input) }),
    remove: (id: string) => request<void>(`/courses/${id}`, { method: "DELETE" }),
    reindex: (id: string) => request<CourseDocument[]>(`/courses/${id}/reindex`, { method: "POST" }),
    demo: () => request<Course>("/demo", { method: "POST" }),
  },

  chunk: (id: string) => request<ChunkDetail>(`/chunks/${id}`),

  documents: {
    list: (courseId: string) => request<CourseDocument[]>(`/courses/${courseId}/documents`),
    upload: uploadFiles,
    remove: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
    reprocess: (id: string) => request<CourseDocument>(`/documents/${id}/reprocess`, { method: "POST" }),
    chunks: (id: string, page?: number | null) =>
      request<Chunk[]>(`/documents/${id}/chunks?limit=500${page ? `&page=${page}` : ""}`),
    fileUrl: (id: string, page?: number | null) =>
      `${API_URL}/api/documents/${id}/file${page ? `#page=${page}` : ""}`,
  },

  search: (courseId: string, query: string, mode: SearchMode = "hybrid", documentIds?: string[] | null) =>
    request<SearchResponse>(`/courses/${courseId}/search`, json({ query, top_k: 8, mode, document_ids: documentIds })),

  chat: {
    stream: streamChat,
    sessions: (courseId: string) => request<ChatSessionSummary[]>(`/courses/${courseId}/chat/sessions`),
    session: (id: string) => request<ChatSessionDetail>(`/chat/sessions/${id}`),
    remove: (id: string) => request<void>(`/chat/sessions/${id}`, { method: "DELETE" }),
  },

  quizzes: {
    list: (courseId: string) => request<QuizSummary[]>(`/courses/${courseId}/quizzes`),
    generate: (
      courseId: string,
      input: {
        num_questions: number;
        difficulty: Difficulty;
        question_types: QuestionType[];
        topic?: string | null;
        document_ids?: string[] | null;
      },
    ) => request<QuizDetail>(`/courses/${courseId}/quizzes`, json(input)),
    get: (id: string) => request<QuizDetail>(`/quizzes/${id}`),
    submit: (id: string, answers: Record<string, string>) => request<QuizAttempt>(`/quizzes/${id}/attempts`, json({ answers })),
    attempts: (id: string) => request<QuizAttempt[]>(`/quizzes/${id}/attempts`),
    remove: (id: string) => request<void>(`/quizzes/${id}`, { method: "DELETE" }),
  },

  decks: {
    list: (courseId: string) => request<DeckSummary[]>(`/courses/${courseId}/decks`),
    generate: (courseId: string, input: { num_cards: number; topic?: string | null; document_ids?: string[] | null }) =>
      request<DeckDetail>(`/courses/${courseId}/decks`, json(input)),
    get: (id: string) => request<DeckDetail>(`/decks/${id}`),
    study: (id: string) => request<{ deck: DeckSummary; cards: Flashcard[] }>(`/decks/${id}/study`),
    review: (cardId: string, rating: Rating) => request<Flashcard>(`/flashcards/${cardId}/review`, json({ rating })),
    reset: (id: string) => request<DeckSummary>(`/decks/${id}/reset`, { method: "POST" }),
    remove: (id: string) => request<void>(`/decks/${id}`, { method: "DELETE" }),
  },
};
