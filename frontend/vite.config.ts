/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// Dev: Vite on :5173 proxies /api to the Project Zero backend (default :8177, override with PZ_API).
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    strictPort: true,
    // changeOrigin stays false: the backend refuses writes whose Origin host differs from Host (CSRF rule), and the
    // shorthand form would rewrite Host to 127.0.0.1 while the browser's Origin says localhost.
    proxy: { "/api": { target: process.env.PZ_API ?? "http://127.0.0.1:8177", changeOrigin: false } },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    css: false,
  },
});
