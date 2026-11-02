import { useEffect, useState } from "react";

import { getJson } from "./api";

/**
 * Model names come from one place: the `models.meta` Task Object (ta-amps' list of the models it uses), which the
 * worker go-live writes to Tessera and the Worker serves read-only at `/api/models`. No page types a model's name.
 * Until the Task Object is there, a page names no model: a dedicated worker, or a Muse model id, reads as "Meta's
 * latest Muse model", and any other model a volunteer declares reads as its own model.
 */
export interface ModelsCatalog {
  id?: string;
  version?: number;
  runtime?: {
    /** Model id to its display name, e.g. "muse-spark-1.3" to the name pages show. */
    display_by_id?: Record<string, string>;
    /** The model id a dedicated worker run by ta-amps uses when its fact names none. */
    dedicated_worker_default?: string;
  };
}

export interface ModelWords {
  fallback: string;
  own: string;
}

interface ModelsResponse {
  catalog: ModelsCatalog | null;
}

let pending: Promise<ModelsCatalog | null> | null = null;

/** The catalog once per page view; null when Tessera holds none yet or it can't be read. */
export function loadModels(): Promise<ModelsCatalog | null> {
  pending ??= getJson<ModelsResponse>("/api/models")
    .then((response) => (response && typeof response.catalog === "object" ? response.catalog : null))
    .catch(() => null);
  return pending;
}

export function useModels(): ModelsCatalog | null {
  const [catalog, setCatalog] = useState<ModelsCatalog | null>(null);
  useEffect(() => {
    let current = true;
    void loadModels().then((found) => {
      if (current) setCatalog(found);
    });
    return () => {
      current = false;
    };
  }, []);
  return catalog;
}

/**
 * The name a page shows for the model a recorded fact declares: the catalog's display name for its id, never a
 * typed one. Null when a volunteer's fact declares no model, so the page names none.
 */
export function modelName(catalog: ModelsCatalog | null, id: string | undefined, words: ModelWords, dedicated = false): string | null {
  const key = (id ?? "").trim() || (dedicated ? (catalog?.runtime?.dedicated_worker_default ?? "") : "");
  if (!key && !dedicated) return null;
  const display = key ? catalog?.runtime?.display_by_id?.[key] : undefined;
  if (display) return display;
  if (dedicated || /^muse[-_.]/i.test(key)) return words.fallback;
  return words.own;
}
