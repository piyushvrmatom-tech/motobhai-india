// Tiny fetch wrapper. All API calls go through here.
const API_BASE = window.MB_API_BASE || "https://motobhai-api.onrender.com";

async function request(path, { method = "GET", body, signal } = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const err = new Error(data?.detail?.message || data?.detail || res.statusText);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  plan: (payload) => request("/api/plan", { method: "POST", body: payload }),
  motorcycles: () => request("/api/motorcycles"),
  share: (id) => request(`/api/share/${id}`),
  log: (event, fields = {}) => request("/api/log", { method: "POST", body: { event, ...fields } }).catch(() => {}),
  otpSend: (phone) => request("/api/otp/send", { method: "POST", body: { phone } }),
  otpVerify: (phone, code) => request("/api/otp/verify", { method: "POST", body: { phone, code } }),
};

export { API_BASE };
