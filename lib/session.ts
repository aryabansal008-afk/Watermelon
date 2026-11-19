import { cookies } from "next/headers";
import { SignJWT, jwtVerify } from "jose";
export const cookieName = "watermelon_session";
function key() {
  const secret = process.env.SESSION_SECRET;
  if (!secret || secret.length < 32) throw new Error("SESSION_SECRET must have at least 32 characters");
  return new TextEncoder().encode(secret);
}
export async function createSession() {
  return new SignJWT({ role: "owner" }).setProtectedHeader({ alg: "HS256" })
    .setSubject(process.env.OWNER_ID || "local-owner").setIssuer("watermelon").setAudience("watermelon-workspace")
    .setIssuedAt().setExpirationTime("8h").sign(key());
}
export async function session() {
  const token = (await cookies()).get(cookieName)?.value;
  if (!token) return null;
  try { const { payload } = await jwtVerify(token, key(), { issuer: "watermelon", audience: "watermelon-workspace", algorithms: ["HS256"] });
    if (payload.sub !== (process.env.OWNER_ID || "local-owner")) return null;
    return payload;
  } catch { return null; }
}
