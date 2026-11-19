import { NextRequest, NextResponse } from "next/server";
import { session } from "@/lib/session";
import { isSameOriginRequest } from "@/lib/request-origin";
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!await session()) return NextResponse.json({ error: { message: "Sign in to access your workspace." } }, { status: 401 });
  if (!["GET", "HEAD"].includes(request.method) && !isSameOriginRequest(request))
    return NextResponse.json({ error: { message: "Invalid request origin" } }, { status: 403 });
  const { path } = await context.params;
  if (path.some(p => !/^[a-zA-Z0-9_-]+$/.test(p)) || path[0] !== "v1") return new NextResponse(null, { status: 400 });
  if (Number(request.headers.get("content-length") || 0) > 65536) return new NextResponse(null, { status: 413 });
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    if (body && body.length > 65536) return new NextResponse(null, { status: 413 });
    const response = await fetch(`${process.env.API_BASE_URL || "http://127.0.0.1:8000"}/${path.join("/")}${request.nextUrl.search}`, {
      method: request.method, body, cache: "no-store", signal: AbortSignal.timeout(120_000),
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${process.env.API_SERVICE_TOKEN || ""}` },
    });
    const contentType = response.headers.get("Content-Type") || "application/json";
    if (contentType.includes("text/event-stream"))
      return new NextResponse(response.body, { status: response.status, headers: { "Content-Type": contentType, "Cache-Control": "no-cache", "X-Accel-Buffering": "no" } });
    return new NextResponse(await response.text(), { status: response.status, headers: { "Content-Type": contentType, "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: { message: "The memory service is unavailable. Check that FastAPI is running, then retry." } }, { status: 503 }); }
}
export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
