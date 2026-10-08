/** Chunked upload: hash -> start -> PUT chunks -> complete (BACKEND.md §5.1). */

import { api } from "./client";
import type { DocumentSummary } from "./types";

interface StartResult {
  upload_id: string | null;
  duplicate: boolean;
  chunk_size?: number;
  chunk_count?: number;
  document?: DocumentSummary;
}

async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export interface UploadProgress {
  phase: "hashing" | "uploading";
  sent: number;
  total: number;
}

export async function uploadFile(
  file: File,
  opts: { reviewerId?: string | null; onProgress?: (p: UploadProgress) => void } = {},
): Promise<DocumentSummary> {
  opts.onProgress?.({ phase: "hashing", sent: 0, total: 1 });
  const sha256 = await sha256Hex(file);
  const start = await api.post<StartResult>("/uploads", {
    filename: file.name,
    size: file.size,
    sha256,
    reviewer_id: opts.reviewerId ?? null,
  });
  if (start.duplicate && start.document) return { ...start.document, duplicate: true };

  const size = start.chunk_size!;
  const count = start.chunk_count!;
  for (let i = 0; i < count; i++) {
    const part = file.slice(i * size, Math.min(file.size, (i + 1) * size));
    let attempt = 0;
    for (;;) {
      try {
        await api.putBytes(`/uploads/${start.upload_id}/chunks/${i}`, part);
        break;
      } catch (e) {
        if (++attempt >= 3) throw e;
        await new Promise((r) => setTimeout(r, 1000 * attempt));
      }
    }
    opts.onProgress?.({ phase: "uploading", sent: i + 1, total: count });
  }
  return api.post<DocumentSummary>(`/uploads/${start.upload_id}/complete`, { reviewer_id: opts.reviewerId ?? null });
}
