const BASE = '/api';
export function getToken() { return localStorage.getItem('flw_token'); }
export function setToken(t) { localStorage.setItem('flw_token', t); }
export function clearAuth() { localStorage.removeItem('flw_token'); }

function headers() {
  const t = getToken();
  return { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}) };
}

export async function api(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  ).toString();
  const url = `${BASE}${path}${qs ? '?' + qs : ''}`;
  const res = await fetch(url, { headers: headers() });
  if (res.status === 401) { clearAuth(); window.location.reload(); }
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.error || res.statusText); }
  return res.json();
}

export async function apiPost(path, body = {}) {
  const res = await fetch(`${BASE}${path}`, { method: 'POST', headers: headers(), body: JSON.stringify(body) });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.error || res.statusText); }
  return res.json();
}

export const authLogin = (email, password) => apiPost('/auth/login', { email, password });
export const authMe = () => api('/auth/me');
export const authGetUsers = () => api('/auth/users');
export const authCreateUser = (data) => apiPost('/auth/users', data);
export const authUpdateUser = (id, data) => apiPost(`/auth/users/${id}`, data);
export const authDeleteUser = (id) => apiPost(`/auth/users/${id}/delete`);
