// Every call to the backend lives here, so components never build URLs themselves.
const BASE = import.meta.env.VITE_API_BASE_URL || "";

export class ApiError extends Error {
  constructor(message, details = []) {
    super(message);
    this.details = details;
  }
}

async function request(path, options) {
  let res;
  try {
    res = await fetch(BASE + path, options);
  } catch {
    throw new ApiError("Can't reach the server. Check that the backend is running and try again.");
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON response */
  }
  if (!res.ok) {
    const e = body?.error;
    throw new ApiError(e?.message || `Request failed (${res.status}).`, e?.details || []);
  }
  return body;
}

export const getDays = () => request("/api/v1/days");

export const getReport = (date, clinicId) =>
  request(`/api/v1/days/${date}/report` + (clinicId ? `?clinic_id=${encodeURIComponent(clinicId)}` : ""));

export const getNarrative = (date, clinicId, refresh = false) => {
  const q = new URLSearchParams();
  if (clinicId) q.set("clinic_id", clinicId);
  if (refresh) q.set("refresh", "true");
  return request(`/api/v1/days/${date}/narrative?${q}`);
};

export const uploadDay = (records, businessDate) =>
  request("/api/v1/days", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ records, ...(businessDate ? { business_date: businessDate } : {}) }),
  });
