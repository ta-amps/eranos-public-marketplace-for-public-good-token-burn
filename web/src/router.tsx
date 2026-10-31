import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent, type ReactNode } from "react";

export type RouteMatch =
  | { name: "overview" }
  | { name: "help" }
  | { name: "nonprofits" }
  | { name: "request"; id: string }
  | { name: "catalog" }
  | { name: "kit"; id: string }
  | { name: "contribute" }
  | { name: "tracks" }
  | { name: "fabric" }
  | { name: "about" }
  | { name: "connect" }
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
};

export function matchPath(rawPath: string): RouteMatch {
  const path = rawPath.replace(/\/+$/, "") || "/";
  const fixed = STATIC_ROUTES[path];
  if (fixed) return fixed;
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
  const reqMatch = /^\/requests\/([^/]+)$/.exec(path);
  const rawReqId = reqMatch?.[1];
  if (reqMatch && rawReqId) {
    try {
      return { name: "request", id: decodeURIComponent(rawReqId) };
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

export function navigate(to: string): void {
  window.history.pushState(null, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0 });
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
