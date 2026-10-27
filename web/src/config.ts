type PublicSurfaceTarget = "eranos" | "shamash" | "tessera";

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
export const SURFACE_PUBLIC_URL = resolvePublicUrl(import.meta.env.VITE_SURFACE_URL, "eranos");
export const SIBLING_DETECTION_NAME = import.meta.env.VITE_SIBLING_NAME || "Shamash";
export const SIBLING_DETECTION_URL = resolvePublicUrl(import.meta.env.VITE_SIBLING_URL, "shamash");
export const FABRIC_DISPLAY_NAME = import.meta.env.VITE_FABRIC_DISPLAY_NAME || "Tessera";
export const FABRIC_PUBLIC_URL = resolvePublicUrl(import.meta.env.VITE_TESSERA_URL, "tessera");
