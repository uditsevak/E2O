import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** All requests go to /api on the same origin; Next.js forwards them to the backend. */
export const api = createClient<paths>({ baseUrl: "", credentials: "include" });

type ValidationIssue = { loc?: (string | number)[]; msg?: string };

const FIELD_NAMES: Record<string, string> = {
  email: "Email",
  password: "Password",
  name: "Name",
  host: "Server",
  port: "Port",
  username: "Username",
};

function detailToMessage(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const issue = detail[0] as ValidationIssue;
    const field = String(issue.loc?.at(-1) ?? "");
    const label = FIELD_NAMES[field] ?? field;
    const msg = (issue.msg ?? "is not valid").replace(/^Value error, /, "");
    return label ? `${label}: ${msg}` : msg;
  }
  return "Something went wrong. Please try again.";
}

/** Turn an openapi-fetch result into data, or throw an ApiError with a human message. */
export async function unwrap<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await request;
  } catch {
    throw new ApiError("Can't reach the server. Check your internet connection.", 0);
  }
  if (!result.response.ok) {
    throw new ApiError(detailToMessage(result.error), result.response.status);
  }
  return result.data as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}
