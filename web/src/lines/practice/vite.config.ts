// 独立验收页的构建配置，不修改 A 的共用 Vite 配置。
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: decodeURIComponent(new URL("../../../", import.meta.url).pathname),
  plugins: [react()],
  build: {
    outDir: "dist/practice",
    rollupOptions: { input: decodeURIComponent(new URL("./preview.html", import.meta.url).pathname) },
  },
});
