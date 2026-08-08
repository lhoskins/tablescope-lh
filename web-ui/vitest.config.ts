import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
    },
  },
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "happy-dom",
    globals: true,
    include: ["**/*.test.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
  },
});
