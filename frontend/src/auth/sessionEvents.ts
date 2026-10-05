// Only protected requests publish this event; failed logins are not expiration.
export const SESSION_UNAUTHORIZED = 'pole-position:unauthorized';
export const SESSION_STORAGE_KEY = 'pole-position:access-token';

export function reportUnauthorized(token: string) {
  window.dispatchEvent(new CustomEvent(SESSION_UNAUTHORIZED, { detail: token }));
}
