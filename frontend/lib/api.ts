/**
 * Centralised API client configuration.
 *
 * NEXT_PUBLIC_API_URL must be set in your environment:
 *   - Local dev:    http://localhost:8000
 *   - Production:   https://api-production-xxxx.up.railway.app  (or your domain)
 *
 * The empty-string fallback intentionally causes an obvious network error
 * in production if the variable is missing, rather than silently hitting
 * localhost (which would never work in a deployed environment).
 */

export const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_URL ?? '';

if (typeof window !== 'undefined' && !API_BASE_URL) {
  console.error(
    '[api] NEXT_PUBLIC_API_URL is not set. ' +
    'API calls will fail. Set this variable in your .env.local or deployment config.'
  );
}

/**
 * Thin wrapper around fetch that prepends API_BASE_URL and forwards
 * the Supabase session token from localStorage when available.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  // Attempt to read the Supabase access token from localStorage (client-side only)
  let token: string | null = null;
  if (typeof window !== 'undefined') {
    try {
      // Supabase stores the session under a key like `sb-<project>-auth-token`
      const raw = Object.entries(localStorage).find(([k]) =>
        k.startsWith('sb-') && k.endsWith('-auth-token')
      );
      if (raw) {
        const parsed = JSON.parse(raw[1]);
        token = parsed?.access_token ?? null;
      }
    } catch {
      // ignore parse errors
    }
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
}
