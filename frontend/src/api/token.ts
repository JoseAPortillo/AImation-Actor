/**
 * Bearer token singleton for the AImation API.
 *
 * The token is read once from the build-time environment variable
 * `AIMATION_SESSION_TOKEN` (via `import.meta.env`) and held in this in-memory
 * module. It is NEVER persisted to localStorage/sessionStorage or Zustand
 * state, per HTTP-2.
 */

const SESSION_TOKEN = import.meta.env.AIMATION_SESSION_TOKEN ?? "";

/** Return the session token, or an empty string when not configured. */
export function sessionToken(): string {
  return SESSION_TOKEN;
}
