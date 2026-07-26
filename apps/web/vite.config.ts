import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

import { DEFAULT_PUBLIC_BASE_PATH } from "./src/lib/deploymentPath";

export default defineConfig({
    base: process.env.VITE_PUBLIC_BASE ?? DEFAULT_PUBLIC_BASE_PATH,
    plugins: [react()],
    server: {
        proxy: {
            "/api": {
                target: "http://127.0.0.1:8787",
                changeOrigin: false,
            },
        },
    },
    test: {
        environment: "jsdom",
        setupFiles: "./tests/setup.ts",
        globals: true,
        css: true,
        restoreMocks: true,
    },
});
