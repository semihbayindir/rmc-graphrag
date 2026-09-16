const KEY = "rmc_session_id";

// Anonim tarayıcı kimliği; localStorage yoksa undefined.
export function getSessionId(): string | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    let id = window.localStorage.getItem(KEY);
    if (!id) {
      id = crypto.randomUUID();
      window.localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    return undefined;
  }
}
