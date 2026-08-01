import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API is the only backend; everything under /api is proxied to it in
// development so the browser sees one origin and no CORS is involved.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.API_URL ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
