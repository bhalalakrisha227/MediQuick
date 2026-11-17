import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";
const REFRESH_KEY = "mq_refresh";

const api = axios.create({ baseURL, timeout: 10000 });

// Access token lives in memory only. The refresh token is kept in sessionStorage
// (cleared when the tab closes). For production, an httpOnly cookie is safer
// against XSS; that change is planned for the hardening phase.
let accessToken = null;
let onSessionExpired = () => {};

function readRefresh() {
  try { return sessionStorage.getItem(REFRESH_KEY); } catch { return null; }
}
function writeRefresh(value) {
  try {
    if (value) sessionStorage.setItem(REFRESH_KEY, value);
    else sessionStorage.removeItem(REFRESH_KEY);
  } catch { /* storage unavailable: session just won't survive a reload */ }
}

export const tokens = {
  set(data) { accessToken = data.access_token; writeRefresh(data.refresh_token); },
  clear() { accessToken = null; writeRefresh(null); },
  hasRefresh() { return Boolean(readRefresh()); },
  setOnSessionExpired(fn) { onSessionExpired = fn; },
};

// Refresh tokens are single-use. If two refreshes ran at once (parallel requests,
// or React StrictMode running effects twice in development), the second would look
// like token theft and log the user out. So all callers share one in-flight call.
let refreshing = null;
export function refreshSession() {
  if (!refreshing) {
    const refresh_token = readRefresh();
    if (!refresh_token) return Promise.reject(new Error("no refresh token"));
    refreshing = axios
      .post(`${baseURL}/auth/refresh/`, { refresh_token }, { timeout: 10000 })
      .then((res) => { tokens.set(res.data); return res.data; })
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const isAuthCall = original?.url?.includes("/auth/");
    if (error.response?.status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true;
      try {
        await refreshSession();
        return api(original);
      } catch {
        tokens.clear();
        onSessionExpired();
      }
    }
    return Promise.reject(error);
  }
);

// Turns an API error into { message, fields } for forms.
export function apiError(error) {
  const body = error?.response?.data?.error;
  if (body) return { message: body.message, fields: body.fields || {} };
  if (error?.response?.status === 429) return { message: "Too many attempts. Please wait and try again.", fields: {} };
  return { message: "Could not reach the server. Please try again.", fields: {} };
}

export default api;
