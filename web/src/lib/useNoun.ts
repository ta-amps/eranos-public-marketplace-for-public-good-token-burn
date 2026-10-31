import { useCallback, useEffect, useState } from "react";

import { getJson } from "./api";
import type { NounResponse } from "./nouns";

/**
 * Page text is nouns: `eranos.instructions/<key>` in Tessera, read through `/api/nouns/...`. Each noun loads
 * once per page view and is shared by every component that asks for it, so moving between pages shows the
 * text at once instead of flashing empty.
 */
const loaded = new Map<string, unknown>();
const pending = new Map<string, Promise<unknown>>();

function load<T>(key: string): Promise<T> {
  if (loaded.has(key)) return Promise.resolve(loaded.get(key) as T);
  const running = pending.get(key);
  if (running) return running as Promise<T>;
  const request = getJson<NounResponse<T>>(`/api/nouns/eranos.instructions/${key}`)
    .then((response) => {
      loaded.set(key, response.value);
      return response.value;
    })
    .finally(() => pending.delete(key));
  pending.set(key, request);
  return request;
}

/** Starts loading nouns before the first render; resolves when all have loaded or failed. */
export function preloadNouns(keys: string[]): Promise<void> {
  return Promise.allSettled(keys.map((key) => load(key))).then(() => undefined);
}

export interface NounState<T> {
  value: T | null;
  failed: boolean;
  reload: () => void;
}

export function useNoun<T>(key: string): NounState<T> {
  const [value, setValue] = useState<T | null>(() => (loaded.get(key) as T | undefined) ?? null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    if (loaded.has(key)) {
      setValue(loaded.get(key) as T);
      setFailed(false);
      return;
    }
    load<T>(key)
      .then((found) => {
        if (!current) return;
        setValue(found);
        setFailed(false);
      })
      .catch(() => {
        if (current) setFailed(true);
      });
    return () => {
      current = false;
    };
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { value, failed, reload };
}
