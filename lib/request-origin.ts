import type { NextRequest } from "next/server";

/** Reject cross-site mutations while accepting browser requests on the current host. */
export function isSameOriginRequest(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (origin && origin === process.env.APP_ORIGIN) return true;
  if (!origin) return false;
  try {
    const parsed = new URL(origin);
    return parsed.host === request.headers.get("host") && parsed.protocol === request.nextUrl.protocol;
  } catch {
    return false;
  }
}
