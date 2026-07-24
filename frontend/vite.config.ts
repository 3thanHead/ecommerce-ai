import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev the SPA runs on :5173 and proxies /api to the backend on :8820, so the
// same relative fetch('/api/...') works in dev and in the baked prod build.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8820",
    },
  },
});
