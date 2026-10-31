import type { SiteNoun } from "./nouns";
import { useNoun } from "./useNoun";

/** The site noun (headline, subline, title, intro, privacy line), or null while it loads or if it can't load. */
export function useSite(): SiteNoun | null {
  return useNoun<SiteNoun>("site").value;
}
