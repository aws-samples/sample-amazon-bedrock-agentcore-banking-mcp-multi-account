/**
 * Auth — Okta Web App (confidential, cookie-based session).
 * Backend handles all Okta interaction. Frontend just redirects and reads session.
 */

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

export function signIn() {
  window.location.href = `${BACKEND_URL}/api/login`;
}

export function completeNewPassword() {
  return Promise.resolve();
}

export async function getCurrentSession() {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/me`, { credentials: 'include' });
    if (resp.ok) {
      const user = await resp.json();
      return { token: 'cookie-session', email: user.email, name: user.name || user.email };
    }
  } catch (e) {}
  return null;
}

export async function signOut() {
  const resp = await fetch(`${BACKEND_URL}/api/logout`, { method: 'POST', credentials: 'include' });
  const data = await resp.json().catch(() => ({}));
  window.location.href = data.logout_url || '/';
}
