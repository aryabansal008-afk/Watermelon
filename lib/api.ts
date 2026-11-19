export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend/v1${path}`, { ...options, headers: { "Content-Type": "application/json", ...options?.headers } });
  const body = await response.json();
  if (!response.ok) throw new ApiError(response.status, body.error?.message || "The request failed. Please retry.");
  return body;
}
export type Project = { id: string; name: string; repository: string; status: string; counts: Record<string, number> };
export type Decision = { id: string; decision_id: string; title: string; claim: string; scope: string; status: string; verification: string; model: string; created_at: string; revision: number; details: { open_questions?: string[]; verification?: { rationale: string } }; citations?: Citation[]; alternatives?: { id: string; approach: string; rationale: string; status: string }[]; code_links?: { id: string; status: string; proof_url: string; entity: { path: string; commit_sha: string } }[]; revisions?: Decision[] };
export type Citation = { id: string; quote: string; body: string; author: string; url: string; verification: string; content_hash: string; source_updated_at: string };
export type Discussion = { id: string; external_id: string; title: string; kind: string; url: string; source_created_at: string; messages?: { message_version_id: string; body: string; author: string; timestamp: string; url: string; kind: string }[] };
export type Job = { id: string; kind: string; status: string; progress: number; error: string | null; created_at: string; cursor: { numbers?: number[]; failures?: {number:number; error_type:string}[]; extraction_blocked?: { number:number; reason:string }[] } };
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
