import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Dev server proxies /api to the gateway, so no .env is needed (set VITE_API_BASE to call a different host).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true, proxy: { "/api": "http://localhost:8000" } },
});
