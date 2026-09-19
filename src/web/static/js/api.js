// Thin fetch wrapper over the Flask API. Every failure surfaces as an ApiError
// carrying the server's own message + recovery hint, so views can show
// "what went wrong and what to do" instead of a bare status code.

export class ApiError extends Error {
  constructor(status, error = {}) {
    super(error.message || "Something went wrong.");
    this.status = status;
    this.code = error.code || "unknown";
    this.hint = error.hint || "";
    this.detail = error.detail || "";
  }
}

async function request(method, url, body) {
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        // The server rejects state-changing requests without this header,
        // which a cross-origin page can't set without a CORS preflight.
        "X-Requested-With": "draft-copilot",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, {
      code: "network",
      message: "Can't reach the Draft Copilot server.",
      hint: "Make sure it's still running (run_dashboard.bat), then reload this page.",
    });
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, data.error);
  return data;
}

const enc = encodeURIComponent;
const notePath = (id) => id.split("/").map(enc).join("/");

export const api = {
  health: () => request("GET", "/api/health"),
  heroes: () => request("GET", "/api/heroes"),
  meta: (size = 8) => request("GET", `/api/meta?size=${size}`),
  recommend: (draft) => request("POST", "/api/recommend", draft),

  notes: () => request("GET", "/api/notes"),
  note: (id) => request("GET", `/api/notes/${notePath(id)}`),
  createNote: (text, hero) => request("POST", "/api/notes", { text, hero }),
  updateNote: (id, content) => request("PUT", `/api/notes/${notePath(id)}`, { content }),
  deleteNote: (id) => request("DELETE", `/api/notes/${notePath(id)}`),
  rebuildKb: () => request("POST", "/api/knowledge-base/rebuild"),

  watcher: () => request("GET", "/api/meta-watcher"),
  startWatcher: () => request("POST", "/api/meta-watcher/start"),
  stopWatcher: () => request("POST", "/api/meta-watcher/stop"),
};
