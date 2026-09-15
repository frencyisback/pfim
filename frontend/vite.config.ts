import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Specification §2.2
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // The client calls the backend at the absolute VITE_API_BASE_URL.
  // Configure it in frontend/.env.example; a proxy on /api would not be used.
  // Backend CORS allows communication between the frontend and backend ports.
  // Keep the backend origins aligned with the frontend address.
  // Development and preview use the same configured backend URL.
  server: {
    port: 5173,
  },
});
