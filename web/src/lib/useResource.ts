import { useCallback, useEffect, useState } from "react";

import { SNAPSHOT } from "../config";
import { getJson, type ApiPath } from "./api";

export type Resource<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T; fromSnapshot: boolean };

export function useResource<T>(path: ApiPath): { state: Resource<T>; reload: () => void } {
  const [state, setState] = useState<Resource<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    getJson<T>(path, controller.signal)
      .then((data) => setState({ status: "ready", data, fromSnapshot: SNAPSHOT }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
      });
    return () => controller.abort();
  }, [path, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, reload };
}
