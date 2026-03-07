const RAW_API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export function sanitizeApiBase(raw: string): string {
  const trimmed = raw.trim().replace(/^[\s'"]+|[\s'"]+$/g, "");
  const match = trimmed.match(/https?:\/\/[^\s'"]+/i);
  return (match ? match[0] : trimmed).replace(/\/+$/g, "");
}

const API_BASE = sanitizeApiBase(RAW_API_BASE);

export function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (!API_BASE) {
    return normalized;
  }
  if (!/^https?:\/\/[^\s]+$/i.test(API_BASE)) {
    throw new Error(`Invalid NEXT_PUBLIC_API_BASE value "${RAW_API_BASE}".`);
  }
  return `${API_BASE}${normalized}`;
}
