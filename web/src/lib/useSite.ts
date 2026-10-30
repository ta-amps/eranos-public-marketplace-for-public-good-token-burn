import type { NounResponse, SiteNoun } from "./nouns";
import { useResource } from "./useResource";

/** The site noun (headline, subline, title, brand sub, intro), or null while it loads or if it can't load. */
export function useSite(): SiteNoun | null {
  const { state } = useResource<NounResponse<SiteNoun>>("/api/nouns/eranos.instructions/site");
  return state.status === "ready" ? state.data.value : null;
}
