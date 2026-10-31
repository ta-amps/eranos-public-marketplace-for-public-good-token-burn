/**
 * The requester key is a capability: whoever holds it can follow the request verb it filed and decide on the
 * results. It travels only in the private link's `#k=` fragment, which browsers never send to a server, and it is
 * kept in this browser's storage so a reload keeps decision rights. It never goes into a path or a query string.
 */

const STORAGE_PREFIX = "eranos.requester.";
const KEY_RE = /^tsk_[0-9a-f]{64}$/;
// Kept for this tab even when the browser blocks storage.
const inMemory = new Map<string, string>();

export function isRequesterKey(value: string | null | undefined): value is string {
  return typeof value === "string" && KEY_RE.test(value);
}

/** The key in a `#k=...` fragment, or null. */
export function keyFromHash(hash: string): string | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const key = params.get("k");
  return isRequesterKey(key) ? key : null;
}

export function rememberKey(requestId: string, key: string): void {
  if (!isRequesterKey(key)) return;
  inMemory.set(requestId, key);
  try {
    window.localStorage.setItem(STORAGE_PREFIX + requestId, key);
  } catch {
    // Storage can be blocked or full; the link's fragment and this tab still hold the key.
  }
}

export function storedKey(requestId: string): string | null {
  const held = inMemory.get(requestId);
  if (held) return held;
  try {
    const found = window.localStorage.getItem(STORAGE_PREFIX + requestId);
    return isRequesterKey(found) ? found : null;
  } catch {
    return null;
  }
}

/** The key for this request: from the link's fragment first (and then remembered), else from storage. */
export function requesterKeyFor(requestId: string, hash: string): string | null {
  const fromLink = keyFromHash(hash);
  if (fromLink) {
    rememberKey(requestId, fromLink);
    return fromLink;
  }
  return storedKey(requestId);
}

export function privateLink(origin: string, requestId: string, key: string): string {
  return `${origin}/requests/${encodeURIComponent(requestId)}#k=${key}`;
}
