import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
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
