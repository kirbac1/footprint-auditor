import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the UI runs on Vite (5173) and these API paths are proxied
// to FastAPI, so the browser sees one origin, the same as in production
// where FastAPI serves the built files itself.
const API = "http://127.0.0.1:8000";
const API_PATHS = [
  "/auth",
  "/me",
  "/meta",
  "/identifiers",
  "/scan",
  "/findings",
  "/impersonation-check",
  "/breach-check",
  "/remediation-plan",
];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(API_PATHS.map((p) => [p, API])),
  },
});
