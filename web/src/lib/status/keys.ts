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

export interface SavedRequest {
  id: string;
  /** When it was sent, read from the request id itself (rq-<principal>-<base36 milliseconds>). */
  sentAt: number | null;
}

/** The requests whose private links this browser holds, newest first. Only ids are listed; keys stay in storage. */
export function savedRequests(): SavedRequest[] {
  const ids = new Set(inMemory.keys());
  try {
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const name = window.localStorage.key(i);
      if (name?.startsWith(STORAGE_PREFIX) && isRequesterKey(window.localStorage.getItem(name))) ids.add(name.slice(STORAGE_PREFIX.length));
    }
  } catch {
    // Storage can be blocked; this tab's links still count.
  }
  return [...ids]
    .filter((id) => /^rq-r_[0-9a-f]{32}-[0-9a-z]+$/.test(id))
    .map((id) => {
      const sent = parseInt(id.slice(id.lastIndexOf("-") + 1), 36);
      return { id, sentAt: Number.isFinite(sent) && sent > 1.6e12 && sent < 4.1e12 ? sent : null };
    })
    .sort((a, b) => (b.sentAt ?? 0) - (a.sentAt ?? 0));
}

/** Forget one request's private link in this browser. */
export function forgetKey(requestId: string): void {
  inMemory.delete(requestId);
  try {
    window.localStorage.removeItem(STORAGE_PREFIX + requestId);
  } catch {
    // Nothing else to do.
  }
}

/** True when this browser's storage (not only this tab) holds the request's key. */
export function isPersisted(requestId: string): boolean {
  try {
    return isRequesterKey(window.localStorage.getItem(STORAGE_PREFIX + requestId));
  } catch {
    return false;
  }
}

/**
 * Once the key from a private link is stored in this browser, the `#k=` fragment leaves the address bar, so
 * filming, screen-sharing, screenshots or synced history never carry it. "Copy private link" still rebuilds the
 * link from storage. If storage is blocked the fragment stays, because a reload would otherwise lose the key.
 */
export function dropKeyFromAddress(requestId: string): void {
  if (!keyFromHash(window.location.hash) || !isPersisted(requestId)) return;
  window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
}
