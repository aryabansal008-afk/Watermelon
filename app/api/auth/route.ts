import { NextRequest, NextResponse } from "next/server";
import { timingSafeEqual, createHash } from "node:crypto";
import { createSession, cookieName } from "@/lib/session";
import { isSameOriginRequest } from "@/lib/request-origin";
const attempts = new Map<string, { count: number; until: number }>();
export async function POST(request: NextRequest) {
  if (!isSameOriginRequest(request))
    return NextResponse.json({ error: { message: "Invalid request origin" } }, { status: 403 });
  // Single-operator gateway limiter. Reverse proxy must also rate-limit login in distributed deployments.
  const id = "owner-login";
  const previous = attempts.get(id);
  const entry = previous && previous.until > Date.now() ? previous : { count: 0, until: Date.now() + 60_000 };
  entry.count++; attempts.set(id, entry);
  if (entry.count > 10) return NextResponse.json({ error: { message: "Too many attempts. Try again in a minute." } }, { status: 429 });
  if (Number(request.headers.get("content-length") || 0) > 2048) return new NextResponse(null, { status: 413 });
  let password = "";
  try { const body = await request.json(); if (typeof body.password === "string") password = body.password; } catch { /* invalid credentials */ }
  const expected = process.env.OWNER_PASSWORD;
  if (!expected || expected.length < 16) return NextResponse.json({ error: { message: "Owner login is not configured." } }, { status: 503 });
  const hash = (s: string) => createHash("sha256").update(s).digest();
  if (password.length > 1024 || !timingSafeEqual(hash(password), hash(expected)))
    return NextResponse.json({ error: { message: "Incorrect workspace password." } }, { status: 401 });
  const response = NextResponse.json({ ok: true });
  response.cookies.set(cookieName, await createSession(), { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: 8 * 3600 });
  return response;
}
export async function DELETE(request: NextRequest) {
  if (!isSameOriginRequest(request)) return new NextResponse(null, { status: 403 });
  const response = NextResponse.json({ ok: true }); response.cookies.delete(cookieName); return response;
}
