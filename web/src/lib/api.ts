import { SNAPSHOT_DATA } from "virtual:snapshot-data";

import { SNAPSHOT } from "../config";

export type ApiPath =
  | "/api/catalog"
  | "/api/tracks"
  | "/api/requests"
  | "/api/fabric"
  | `/api/catalog/${string}`;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function snapshotKey(path: ApiPath): string {
  return path.replace(/^\/api\//, "");
}

export async function getJson<T>(path: ApiPath, signal?: AbortSignal): Promise<T> {
  if (SNAPSHOT) {
    const key = snapshotKey(path);
    if (!(key in SNAPSHOT_DATA)) {
      throw new ApiError(`The snapshot has no data for ${path}. Run make snapshot.`);
    }
    return SNAPSHOT_DATA[key] as T;
  }
  const response = await fetch(path, { headers: { accept: "application/json" }, signal });
  if (!response.ok) {
    throw new ApiError(`${path} answered ${response.status} ${response.statusText}`, response.status);
  }
  return (await response.json()) as T;
}
