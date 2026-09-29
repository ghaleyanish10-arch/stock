import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server runs on 5174 (5173 is commonly taken) and proxies /api to the
// FastAPI backend, so no CORS setup is needed during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
