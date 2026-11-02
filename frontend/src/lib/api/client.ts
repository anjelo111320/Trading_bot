import type { components } from "./schema";

export type Health = components["schemas"]["HealthResponse"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      body?.error?.code ?? "http_error",
      body?.error?.message ?? `Request failed with status ${response.status}`,
    );
  }
  return (await response.json()) as T;
}
