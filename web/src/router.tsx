import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent, type ReactNode } from "react";

export type RouteMatch =
  | { name: "overview" }
  | { name: "help" }
  | { name: "nonprofits" }
  | { name: "catalog" }
  | { name: "kit"; id: string }
  | { name: "contribute" }
  | { name: "tracks" }
  | { name: "fabric" }
  | { name: "about" }
  | { name: "connect" }
  | { name: "library" }
  | { name: "yours" }
  | { name: "request"; id: string }
  | { name: "report"; id: string }
  | { name: "notFound"; path: string };

const STATIC_ROUTES: Record<string, RouteMatch> = {
  "/": { name: "overview" },
  "/help": { name: "help" },
  "/nonprofits": { name: "nonprofits" },
  "/catalog": { name: "catalog" },
  "/contribute": { name: "contribute" },
  "/tracks": { name: "tracks" },
  "/fabric": { name: "fabric" },
  "/about": { name: "about" },
  "/connect": { name: "connect" },
  "/library": { name: "library" },
  "/requests": { name: "yours" },
};

export function matchPath(rawPath: string): RouteMatch {
  const path = rawPath.replace(/\/+$/, "") || "/";
  const fixed = STATIC_ROUTES[path];
  if (fixed) return fixed;
  // A request's status page and its report page. "example" is the labeled example run.
  const requestMatch = /^\/requests\/([^/]+)(\/result)?$/.exec(path);
  const requestId = requestMatch?.[1];
  if (requestMatch && requestId) {
    try {
      const id = decodeURIComponent(requestId);
      return requestMatch[2] ? { name: "report", id } : { name: "request", id };
    } catch {
      return { name: "notFound", path };
    }
  }
  const kitMatch = /^\/catalog\/([^/]+)$/.exec(path);
  const rawId = kitMatch?.[1];
  if (kitMatch && rawId) {
    // A broken percent escape such as "%E0%A4%A" made decodeURIComponent throw while rendering, which left a
    // blank page. It is a page that does not exist.
    try {
      return { name: "kit", id: decodeURIComponent(rawId) };
    } catch {
      return { name: "notFound", path };
    }
  }
  return { name: "notFound", path };
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

export function usePath(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname);
}

/** The query string, such as `?part=2` on a report page. */
export function useSearch(): string {
  return useSyncExternalStore(subscribe, () => window.location.search);
}

export function navigate(to: string): void {
  window.history.pushState(null, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0 });
}

/**
 * Moves to a page with a same-document View Transition when the browser has one and motion is welcome: the
 * request box morphs into the status page's "Your request" node (both carry `view-transition-name: request`).
 * Without support, or with reduced motion, it is an ordinary navigation.
 */
export function navigateWithTransition(to: string, render: (commit: () => void) => void): void {
  const doc = document as Document & { startViewTransition?: (update: () => void) => unknown };
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!doc.startViewTransition || reduced) {
    navigate(to);
    return;
  }
  doc.startViewTransition(() => {
    render(() => navigate(to));
  });
}

interface AppLinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> {
  to: string;
  children: ReactNode;
}

export function AppLink({ to, children, onClick, ...rest }: AppLinkProps) {
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    const modified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
    if (event.defaultPrevented || modified || event.button !== 0) return;
    event.preventDefault();
    navigate(to);
  }
  return (
    <a href={to} onClick={handleClick} {...rest}>
      {children}
    </a>
  );
}
