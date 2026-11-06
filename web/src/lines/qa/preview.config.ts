import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Optional QA-only production preview; shared Vite config is deliberately unchanged.
export default defineConfig({ plugins: [react()], build: { rollupOptions: { input: "qa.html" } } });
