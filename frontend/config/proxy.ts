export function developmentProxy(target = 'http://127.0.0.1:8000') {
  const url = new URL(target);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password
      || url.search || url.hash || url.pathname !== '/') {
    throw new TypeError('API_PROXY_TARGET must be an HTTP(S) origin without credentials.');
  }
  // Keep /api in the forwarded path; FastAPI already uses that prefix.
  return { '/api': { target: url.origin, changeOrigin: true } };
}
