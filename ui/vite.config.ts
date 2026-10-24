/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev the UI proxies /api to the API on :8000; in Docker nginx does the same.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: "0.0.0.0", proxy: { "/api": { target: "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") } } },
  test: { environment: "jsdom", globals: true },
});
