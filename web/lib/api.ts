import type {
  Collection,
  Job,
  Message,
  ResearchEvent,
  Source,
  SourceKind,
  Thread,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    // no-store: the API sets no cache headers, so a GET repeated after a
    // mutation can otherwise be served stale from the browser's heuristic
    // cache -- a deleted row keeps rendering.
    response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API_URL}.`, 0);
  }

  if (!response.ok) {
    // FastAPI puts the reason in `detail`, which may be a validation array.
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(detail, response.status);
  }

  return response.status === 204 ? (undefined as T) : response.json();
}

function json(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const api = {
  health: () =>
    request<{
      status: string;
      database: boolean;
      redis: boolean;
      queue_depth: number;
    }>("/health"),

  listCollections: () => request<Collection[]>("/collections"),
  getCollection: (id: string) => request<Collection>(`/collections/${id}`),
  createCollection: (body: {
    slug: string;
    name: string;
    research_domain: string;
  }) => request<Collection>("/collections", json(body)),
  deleteCollection: (id: string) =>
    request<void>(`/collections/${id}`, { method: "DELETE" }),

  listSources: (collectionId: string) =>
    request<Source[]>(`/collections/${collectionId}/sources`),
  addSource: (
    collectionId: string,
    body: { kind: SourceKind; locator: string; title?: string },
  ) =>
    request<{ source: Source; job: Job }>(
      `/collections/${collectionId}/sources`,
      json(body),
    ),
  uploadSource: (collectionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ source: Source; job: Job }>(
      `/collections/${collectionId}/sources/upload`,
      { method: "POST", body: form },
    );
  },
  reindexSource: (sourceId: string) =>
    request<Job>(`/sources/${sourceId}/reindex`, { method: "POST" }),
  deleteSource: (sourceId: string) =>
    request<void>(`/sources/${sourceId}`, { method: "DELETE" }),

  listThreads: (collectionId: string) =>
    request<Thread[]>(`/collections/${collectionId}/threads`),
  createThread: (collectionId: string, title = "New conversation") =>
    request<Thread>(`/collections/${collectionId}/threads`, json({ title })),
  deleteThread: (threadId: string) =>
    request<void>(`/threads/${threadId}`, { method: "DELETE" }),
  listMessages: (threadId: string) =>
    request<Message[]>(`/threads/${threadId}/messages`),
};

/**
 * Stream a research run.
 *
 * The endpoint is a POST with a body, so EventSource cannot be used: it only
 * issues GETs. This reads the response body directly and splits SSE frames.
 */
export async function askStream(
  threadId: string,
  body: { question: string; max_research_steps?: number; k?: number },
  onEvent: (event: ResearchEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_URL}/threads/${threadId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new ApiError(
      `Research request failed (${response.status}).`,
      response.status,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Frames are separated by a blank line; the last chunk may be partial.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as ResearchEvent);
      } catch {
        /* ignore a frame we cannot parse rather than kill the stream */
      }
    }
  }
}
