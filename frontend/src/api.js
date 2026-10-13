import { useEffect, useState } from "react";

const BASE = import.meta.env.VITE_API_BASE ?? "";

export async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  } catch (e) {
    throw new Error("Cannot reach the API gateway. Is it running on port 8000?");
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) throw new Error(body?.detail || `Request failed (${res.status})`);
  return body;
}

/** GET hook. Pass null to skip. Re-fetches when the path changes. */
export function useApi(path) {
  const [state, set] = useState({ data: null, error: null, loading: !!path });
  useEffect(() => {
    if (!path) { set({ data: null, error: null, loading: false }); return; }
    let live = true;
    set((s) => ({ ...s, loading: true, error: null }));
    api(path).then((data) => live && set({ data, error: null, loading: false }))
             .catch((error) => live && set({ data: null, error: error.message, loading: false }));
    return () => { live = false; };
  }, [path]);
  return state;
}

export const qs = (o) => {
  const p = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return p.length ? "?" + p.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&") : "";
};
