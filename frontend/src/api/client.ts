// Thin fetch wrapper. In demo mode the selected demo user is sent as X-Demo-User;
// the backend ignores it unless demo mode is explicitly enabled (and never in production).

const DEMO_USER_KEY = "cac.demoUser";

export class ApiError extends Error {
  constructor(public status: number, public code: string, public body?: unknown) {
    super(`${status} ${code}`);
  }
}

export function getDemoUser(): string | null {
  try {
    return localStorage.getItem(DEMO_USER_KEY);
  } catch {
    return null;
  }
}

export function setDemoUser(email: string | null) {
  try {
    if (email) localStorage.setItem(DEMO_USER_KEY, email);
    else localStorage.removeItem(DEMO_USER_KEY);
  } catch {
    /* ignore */
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const demo = getDemoUser();
  if (demo) headers.set("X-Demo-User", demo);
  const res = await fetch(`/api${path}`, { ...init, headers });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const code = body?.error?.code ?? (res.status === 422 ? "validation_error" : "http_error");
    throw new ApiError(res.status, code, body);
  }
  return body as T;
}

export const post = <T>(path: string, data: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(data) });
export const patch = <T>(path: string, data: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(data) });
export const put = <T>(path: string, data: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(data) });

export function newRequestId(): string {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, "");
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}
