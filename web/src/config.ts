type PublicSurfaceTarget = "eranos" | "tessera";

export function resolvePublicUrl(explicit: string | undefined, target: PublicSurfaceTarget): string {
  if (explicit) return explicit;
  if (typeof window !== "undefined" && window.location.hostname.startsWith("eranos.")) {
    const rest = window.location.hostname.slice("eranos.".length);
    if (rest) {
      return `${window.location.protocol}//${target}.${rest}`;
    }
  }
  return `https://${target}.ta-amps.workers.dev`;
}

export const SNAPSHOT = import.meta.env.VITE_SNAPSHOT === "1";
export const SURFACE_DISPLAY_NAME = import.meta.env.VITE_SURFACE_NAME || "Eranos";
/** The canonical address: eranosforgood.org (the workers.dev host still serves the same pages). */
export const SURFACE_PUBLIC_URL = import.meta.env.VITE_SURFACE_URL || "https://eranosforgood.org";
export const FABRIC_DISPLAY_NAME = import.meta.env.VITE_FABRIC_DISPLAY_NAME || "Tessera";
export const FABRIC_PUBLIC_URL = resolvePublicUrl(import.meta.env.VITE_TESSERA_URL, "tessera");
export const LIVE_QUEUE_POLL_MS =
  Number.parseInt(String(import.meta.env.VITE_LIVE_QUEUE_POLL_MS || ""), 10) > 0
    ? Number.parseInt(String(import.meta.env.VITE_LIVE_QUEUE_POLL_MS), 10)
    : 15_000;
