/**
 * Token storage for the demo app. localStorage keeps S2 simple; the security
 * hardening phase moves tokens into httpOnly cookies behind a route handler.
 */

const ACCESS_KEY = "caremesh.access";
const REFRESH_KEY = "caremesh.refresh";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REFRESH_KEY);
}

export function storeTokens(access: string, refresh: string): void {
  window.localStorage.setItem(ACCESS_KEY, access);
  window.localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens(): void {
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
}

export function isLoggedIn(): boolean {
  return getAccessToken() !== null;
}
