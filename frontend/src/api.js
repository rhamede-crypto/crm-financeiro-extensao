export const isMock = (import.meta.env.VITE_API_MODE || 'mock') === 'mock';

export class ApiError extends Error {
  constructor(status, message, fields = {}, code) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.fields = fields;
    this.code = code;
  }
}

const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');
const csrfCookie = import.meta.env.VITE_API_CSRF_COOKIE || 'csrftoken';

function csrfToken() {
  const cookie = document.cookie.split(';').map((value) => value.trim())
    .find((value) => value.startsWith(csrfCookie + '='));
  return cookie ? decodeURIComponent(cookie.slice(csrfCookie.length + 1)) : '';
}

async function request(path, { method = 'GET', data, key, signal, publicRoute = false } = {}) {
  if (isMock) {
    const { mockRequest } = await import('./mock.js');
    try {
      signal?.throwIfAborted();
      return await mockRequest(path, method, data, key, signal);
    } catch (error) {
      if (error.status === 401 && !publicRoute) window.dispatchEvent(new Event('crm:expired'));
      throw error;
    }
  }

  const headers = { Accept: 'application/json' };
  const multipart = data instanceof FormData;
  if (data != null && !multipart) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') {
    const token = csrfToken();
    if (token) headers['X-CSRFToken'] = token;
  }
  if (key) headers['Idempotency-Key'] = key;

  let response;
  try {
    response = await fetch(base + path, {
      method, headers, credentials: 'include', signal,
      body: data == null || multipart ? data : JSON.stringify(data),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(0, 'Sem conexão com a API. Tente novamente.');
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !publicRoute) window.dispatchEvent(new Event('crm:expired'));
    throw new ApiError(response.status, payload?.message || payload?.detail || 'Não foi possível concluir a operação.',
      payload?.errors || {}, payload?.code);
  }
  if (payload === null && response.status !== 204) {
    throw new ApiError(502, 'A API retornou uma resposta inválida.');
  }
  return payload;
}

const post = (path, data, options) => request(path, { method: 'POST', data, ...options });
const segment = (id) => encodeURIComponent(id);
const jobPath = (id) => '/imports/' + segment(id);
const contactPath = (id) => '/contacts/' + segment(id);
export const api = {
  session: (signal) => request('/session', { signal, publicRoute: true }),
  login: (data) => post('/auth/login', data, { publicRoute: true }),
  register: (data) => post('/auth/register', data, { publicRoute: true }),
  logout: () => post('/auth/logout'),
  company: (data) => post('/company', data),
  importOptions: (signal) => request('/imports/options', { signal }),
  jobs: (signal) => request('/imports', { signal }),
  upload: (data, key) => post('/imports', data, { key }),
  job: (id, signal) => request(jobPath(id), { signal }),
  confirmImport: (id, data, key) => post(jobPath(id) + '/confirm', data, { key }),
  cancelImport: (id) => post(jobPath(id) + '/cancel'),
  dashboard: (signal) => request('/dashboard', { signal }),
  ask: (data, key) => post('/chat', data, { key }),
  reminders: (signal) => request('/reminders', { signal }),
  saveReminders: (data) => request('/reminders', { method: 'PUT', data }),
  contacts: (query, type, signal) => request('/contacts?' + new URLSearchParams({ query, type }), { signal }),
  contact: (id, signal) => request(contactPath(id), { signal }),
  agreements: (id, data) => post(contactPath(id) + '/agreements', data),
  timeline: (id, signal) => request(contactPath(id) + '/timeline', { signal }),
  note: (id, data) => post(contactPath(id) + '/timeline/notes', data),
  confirmPromise: (id, entryId, data, key) =>
    post(contactPath(id) + '/timeline/' + segment(entryId) + '/confirm', data, { key }),
  collectionPreview: (id, data, signal) => post(contactPath(id) + '/collections/preview', data, { signal }),
  sendCollection: (id, data, key) => post(contactPath(id) + '/collections/send', data, { key }),
  deals: (signal) => request('/deals', { signal }),
  moveDeal: (id, data) => request('/deals/' + segment(id), { method: 'PATCH', data }),
};
