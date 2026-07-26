import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";

const [, , rawPort, rawMount, rawDirectory] = process.argv;
const port = Number(rawPort);
if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new TypeError("A valid unprivileged port is required");
}
if (
    typeof rawMount !== "string" ||
    !/^\/[A-Za-z0-9._~-]+(?:\/[A-Za-z0-9._~-]+)*\/?$/.test(rawMount)
) {
    throw new TypeError("A valid public mount path is required");
}
if (typeof rawDirectory !== "string" || rawDirectory.length === 0) {
    throw new TypeError("A static directory is required");
}

const mount = rawMount.replace(/\/+$/, "");
const root = resolve(rawDirectory);
const indexPath = resolve(root, "index.html");
if (!statSync(indexPath).isFile()) {
    throw new Error(`SPA entry point is missing: ${indexPath}`);
}

const mediaTypes = new Map([
    [".css", "text/css; charset=utf-8"],
    [".html", "text/html; charset=utf-8"],
    [".ico", "image/x-icon"],
    [".js", "text/javascript; charset=utf-8"],
    [".json", "application/json; charset=utf-8"],
    [".png", "image/png"],
    [".svg", "image/svg+xml"],
    [".webm", "video/webm"],
    [".woff2", "font/woff2"],
]);

function sendFile(request, response, filePath) {
    const metadata = statSync(filePath);
    response.writeHead(200, {
        "Content-Length": String(metadata.size),
        "Content-Type":
            mediaTypes.get(extname(filePath).toLowerCase()) ??
            "application/octet-stream",
        "Cache-Control": filePath === indexPath
            ? "no-store"
            : "public, max-age=31536000, immutable",
    });
    if (request.method === "HEAD") {
        response.end();
        return;
    }
    createReadStream(filePath).pipe(response);
}

const server = createServer((request, response) => {
    if (request.method !== "GET" && request.method !== "HEAD") {
        response.writeHead(405, { Allow: "GET, HEAD" });
        response.end();
        return;
    }
    let pathname;
    try {
        pathname = decodeURIComponent(
            new URL(request.url ?? "/", "http://127.0.0.1").pathname,
        );
    } catch {
        response.writeHead(400);
        response.end();
        return;
    }
    if (pathname !== mount && !pathname.startsWith(`${mount}/`)) {
        response.writeHead(404);
        response.end();
        return;
    }
    const stripped = pathname.slice(mount.length) || "/";
    if (
        stripped.includes("\\") ||
        stripped.split("/").some((segment) => segment === "..")
    ) {
        response.writeHead(400);
        response.end();
        return;
    }
    if (stripped === "/api" || stripped.startsWith("/api/")) {
        response.writeHead(404);
        response.end();
        return;
    }
    const candidate = resolve(root, stripped.replace(/^\/+/, ""));
    const rootPrefix = `${root}${sep}`;
    if (candidate !== root && !candidate.startsWith(rootPrefix)) {
        response.writeHead(400);
        response.end();
        return;
    }
    try {
        if (candidate !== root && statSync(candidate).isFile()) {
            sendFile(request, response, candidate);
            return;
        }
    } catch {
        // Client-side routes fall back to the SPA entry point.
    }
    sendFile(request, response, indexPath);
});

server.listen(port, "127.0.0.1");

for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => {
        server.close(() => process.exit(0));
    });
}
