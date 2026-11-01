import { useCallback, useEffect, useState } from "react";

import { SNAPSHOT } from "../config";
import { ApiError, getJson, type ApiPath } from "./api";

export type Resource<T> =
  | { status: "loading" }
  | { status: "error"; message: string; httpStatus?: number }
  | { status: "ready"; data: T; fromSnapshot: boolean };

export interface UseResourceOptions {
  pollMs?: number;
}

export function useResource<T>(
  path: ApiPath,
  options?: UseResourceOptions,
): { state: Resource<T>; reload: () => void; updatedAt: number } {
  const [state, setState] = useState<Resource<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [updatedAt, setUpdatedAt] = useState(() => Date.now());
  const pollMs = options?.pollMs ?? 0;

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    getJson<T>(path, controller.signal)
      .then((data) => {
        setState({ status: "ready", data, fromSnapshot: SNAPSHOT });
        setUpdatedAt(Date.now());
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
          httpStatus: error instanceof ApiError ? error.status : undefined,
        });
      });
    return () => controller.abort();
  }, [path, attempt]);

  useEffect(() => {
    if (SNAPSHOT || pollMs <= 0) return undefined;
    let activeController: AbortController | null = null;
    const refreshSilently = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      getJson<T>(path, controller.signal)
        .then((data) => {
          if (controller.signal.aborted) return;
          setState({ status: "ready", data, fromSnapshot: false });
          setUpdatedAt(Date.now());
        })
        .catch(() => {
          // Preserve last good live snapshot during background refreshes.
        });
    };
    const timer = window.setInterval(refreshSilently, pollMs);
    const onVisibility = () => {
      if (document.visibilityState === "visible") refreshSilently();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      activeController?.abort();
    };
  }, [path, pollMs]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, reload, updatedAt };
}
