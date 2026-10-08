import { SSEParser } from "./sse";
import type {
  AdminUser,
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
  User,
} from "./types";

/**
 * Every call goes to this Next.js server's same-origin /api proxy (src/app/api/[...path]/route.ts), which
 * forwards it to BACKEND_URL together with the HttpOnly session cookie. The browser never talks to FastAPI
 * directly and never sees the session token: it only holds the CSRF token below, in memory.
 */
const API_BASE = "/api";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
/** 401 codes that mean "sign in again" (as opposed to e.g. a misconfigured proxy token). */
const SIGNED_OUT_CODES = new Set(["authentication_required", "session_expired"]);

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

/** Field → message map from a 422 response, for showing errors next to form inputs. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) return {};
  const out: Record<string, string> = {};
  for (const item of error.details as { field?: string; message?: string }[]) {
    if (item.field && item.message && !out[item.field]) out[item.field] = item.message;
  }
  return out;
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

const networkError = () => new ApiError(0, "network_error", "Cannot reach the app server. Check your connection and try again.");

// --- CSRF token (kept in memory; fetched lazily, refreshed once on a csrf_failed answer) ------------------

let csrfToken: string | null = null;
let csrfInFlight: Promise<string> | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

async function ensureCsrfToken(refresh = false): Promise<string> {
  if (csrfToken && !refresh) return csrfToken;
  csrfInFlight ??= fetch(`${API_BASE}/auth/csrf`, { cache: "no-store", credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) throw await toApiError(response);
      csrfToken = ((await response.json()) as { csrf_token: string }).csrf_token;
      return csrfToken;
    })
    .catch((error) => {
      throw error instanceof ApiError ? error : networkError();
    })
    .finally(() => {
      csrfInFlight = null;
    });
  return csrfInFlight;
}

// --- Session lifecycle: one place to cancel private requests and react to "signed out" -------------------

let sessionController = new AbortController();
let unauthorizedHandler: ((error: ApiError) => void) | null = null;

/** Called once per expired/missing session (outside the auth endpoints). Returns an unsubscribe function. */
export function onUnauthorized(handler: (error: ApiError) => void): () => void {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null;
  };
}

/** Cancel every in-flight private request, uploads and answer streams included (sign-out, account switch). */
export function abortPrivateRequests(): void {
  sessionController.abort();
  sessionController = new AbortController();
}

/** Forget everything tied to the current session. */
export function resetClientSession(): void {
  abortPrivateRequests();
  csrfToken = null;
}

function sessionSignal(signal?: AbortSignal | null): AbortSignal {
  return signal ? AbortSignal.any([signal, sessionController.signal]) : sessionController.signal;
}

function reportUnauthorized(error: ApiError, path: string): void {
  if (error.status === 401 && SIGNED_OUT_CODES.has(error.code) && !path.startsWith("/auth/")) unauthorizedHandler?.(error);
}

/** fetch + CSRF header on state-changing methods + one retry with a fresh token if it went stale. */
async function send(path: string, init: RequestInit = {}, retried = false): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !(init.body instanceof FormData) && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (UNSAFE_METHODS.has(method)) headers.set("x-csrf-token", await ensureCsrfToken());

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      signal: sessionSignal(init.signal),
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw networkError();
  }
  if (response.status === 403 && UNSAFE_METHODS.has(method) && !retried) {
    const error = await toApiError(response.clone());
    if (error.code === "csrf_failed") {
      await ensureCsrfToken(true);
      return send(path, init, true);
    }
  }
  return response;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await send(path, init);
  if (!response.ok) {
    const error = await toApiError(response);
    reportUnauthorized(error, path);
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const json = (body: unknown, method = "POST"): RequestInit => ({ method, body: JSON.stringify(body) });

/** Upload with progress events (fetch can't report upload progress, XHR can). */
function uploadFiles(courseId: string, files: File[], onProgress?: (fraction: number) => void): Promise<UploadResult> {
  const path = `/courses/${courseId}/documents`;
  const attempt = async (retried: boolean): Promise<UploadResult> => {
    const token = await ensureCsrfToken(retried);
    const signal = sessionController.signal;
    return new Promise((resolve, reject) => {
      const form = new FormData();
      files.forEach((file) => form.append("files", file));
      const xhr = new XMLHttpRequest();
      const cancel = () => xhr.abort();
      signal.addEventListener("abort", cancel, { once: true });
      const done = () => signal.removeEventListener("abort", cancel);
      xhr.open("POST", `${API_BASE}${path}`);
      xhr.setRequestHeader("X-CSRF-Token", token);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress?.(event.loaded / event.total);
      };
      xhr.onabort = () => {
        done();
        reject(new DOMException("Upload cancelled", "AbortError"));
      };
      xhr.onerror = () => {
        done();
        reject(networkError());
      };
      xhr.onload = () => {
        done();
        let body: unknown = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) return resolve(body as UploadResult);
        const info = (body as { error?: { code: string; message: string; details?: unknown } } | null)?.error;
        const error = new ApiError(xhr.status, info?.code ?? "http_error", info?.message ?? "Upload failed.", info?.details);
        if (error.code === "csrf_failed" && !retried) return resolve(attempt(true));
        reportUnauthorized(error, path);
        reject(error);
      };
      xhr.send(form);
    });
  };
  return attempt(false);
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
  const path = `/courses/${courseId}/chat/stream`;
  const response = await send(path, { ...json(body), headers: { accept: "text/event-stream" }, signal });
  if (!response.ok || !response.body) {
    const error = await toApiError(response);
    reportUnauthorized(error, path);
    throw error;
  }

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

interface AuthResult {
  user: User;
  csrf_token: string;
}

async function signIn(path: string, body: unknown): Promise<User> {
  const result = await request<AuthResult>(path, json(body));
  setCsrfToken(result.csrf_token); // the new session has a new token
  return result.user;
}

export const api = {
  health: () => request<Health>("/health"),

  auth: {
    me: () => request<User>("/auth/me"),
    login: (input: { email: string; password: string; remember_me: boolean }) => signIn("/auth/login", input),
    register: (input: { email: string; password: string; password_confirm: string; display_name?: string | null }) =>
      signIn("/auth/register", input),
    logout: async () => {
      try {
        await request<void>("/auth/logout", { method: "POST" });
      } finally {
        resetClientSession();
      }
    },
    forgotPassword: (email: string) => request<{ message: string }>("/auth/forgot-password", json({ email })),
    resetPassword: (input: { token: string; password: string; password_confirm: string }) =>
      request<{ message: string }>("/auth/reset-password", json(input)),
  },

  admin: {
    users: () => request<AdminUser[]>("/admin/users"),
    setActive: (id: string, isActive: boolean) => request<AdminUser>(`/admin/users/${id}`, json({ is_active: isActive }, "PATCH")),
  },

  courses: {
    list: () => request<Course[]>("/courses"),
    get: (id: string) => request<Course>(`/courses/${id}`),
    create: (input: CourseInput) => request<Course>("/courses", json(input)),
    update: (id: string, input: Partial<CourseInput>) => request<Course>(`/courses/${id}`, json(input, "PATCH")),
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
    /** Same-origin link: the browser sends the session cookie, the proxy forwards it, FastAPI checks ownership. */
    fileUrl: (id: string, page?: number | null) => `${API_BASE}/documents/${id}/file${page ? `#page=${page}` : ""}`,
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
