const TOKEN_KEY = "mtg_rag_token";
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join(", ");
    }
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  auth = false
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(apiUrl(path), { ...options, headers });
  if (!res.ok) throw new Error(await parseError(res));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface ExtractedDecklist {
  commander: string | null;
  name: string | null;
  cards: string;
  card_count: number;
  description?: string | null;
}

export interface QueryResult {
  answer: string;
  sources: { snippet: string; metadata: Record<string, unknown> }[];
  has_decklist: boolean;
  decklist: ExtractedDecklist | null;
  color_identity?: string | null;
}

export interface User {
  id: number;
  email: string;
}

export interface Deck {
  id: number;
  name: string;
  commander: string | null;
  description: string | null;
  cards: string;
  created_at: string;
  updated_at: string;
}

export function askCommander(question: string) {
  return apiFetch<QueryResult>("/api/query", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export function registerUser(email: string, password: string) {
  return apiFetch<User>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function loginUser(email: string, password: string) {
  const body = new FormData();
  body.append("username", email);
  body.append("password", password);
  const res = await fetch(apiUrl("/api/auth/login"), { method: "POST", body });
  if (!res.ok) throw new Error(await parseError(res));
  const data = (await res.json()) as { access_token: string };
  setToken(data.access_token);
  return data;
}

export function fetchMe() {
  return apiFetch<User>("/api/auth/me", {}, true);
}

export function listDecks() {
  return apiFetch<Deck[]>("/api/decks", {}, true);
}

export function createDeck(payload: {
  name: string;
  commander?: string;
  description?: string;
  cards?: string;
}) {
  return apiFetch<Deck>(
    "/api/decks",
    { method: "POST", body: JSON.stringify(payload) },
    true
  );
}

export function updateDeck(
  id: number,
  payload: Partial<{ name: string; commander: string; description: string; cards: string }>
) {
  return apiFetch<Deck>(
    `/api/decks/${id}`,
    { method: "PUT", body: JSON.stringify(payload) },
    true
  );
}

export function deleteDeck(id: number) {
  return apiFetch<void>(`/api/decks/${id}`, { method: "DELETE" }, true);
}

export interface HealthStatus {
  status: string;
  rag_ready: boolean;
  indexing_phase: string;
  indexing_message: string;
  card_vectors: number;
  decks_indexed: number;
}

export function checkHealth() {
  return apiFetch<HealthStatus>("/api/health");
}
