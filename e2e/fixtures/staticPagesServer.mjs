import {
    copyFileSync,
    mkdirSync,
} from "node:fs";
import { delimiter, resolve } from "node:path";
import {
    spawn,
    spawnSync,
} from "node:child_process";

const [, , rawPort, rawMount] = process.argv;
if (rawPort === undefined || rawMount === undefined) {
    throw new TypeError("Port and public mount are required");
}

const npmCli = process.env.npm_execpath;
if (npmCli === undefined || npmCli.length === 0) {
    throw new Error("npm_execpath is required to build the static fixture");
}
const pythonCommand = process.env.PYTHON ?? "python";
const sourceRoot = resolve("apps/api/src");
const environment = {
    ...process.env,
    PYTHONPATH: process.env.PYTHONPATH
        ? `${sourceRoot}${delimiter}${process.env.PYTHONPATH}`
        : sourceRoot,
    VITE_DATA_MODE: "static",
    VITE_PUBLIC_BASE: rawMount,
    VITE_STATIC_DATA_DATE: "2026-07-31",
};

function run(command, arguments_) {
    const result = spawnSync(command, arguments_, {
        cwd: process.cwd(),
        env: environment,
        stdio: "inherit",
    });
    if (result.error !== undefined) {
        throw result.error;
    }
    if (result.status !== 0) {
        throw new Error(
            `${command} failed with exit code ${String(result.status)}`,
        );
    }
}

run(process.execPath, [
    npmCli,
    "--prefix",
    "apps/web",
    "run",
    "build",
    "--",
    "--outDir=dist-static",
    "--emptyOutDir",
]);

const outputRoot = resolve("apps/web/dist-static");
const reportsRoot = resolve(outputRoot, "reports");
mkdirSync(reportsRoot, { recursive: true });
run(pythonCommand, [
    "-m",
    "drawdown_lab.reports.publication",
    "reports/published",
    "--output",
    resolve(reportsRoot, "index.html"),
]);
copyFileSync(
    resolve(outputRoot, "index.html"),
    resolve(outputRoot, "404.html"),
);

const server = spawn(
    process.execPath,
    [
        resolve("e2e/fixtures/mountedSpaServer.mjs"),
        rawPort,
        rawMount,
        outputRoot,
    ],
    {
        cwd: process.cwd(),
        env: environment,
        stdio: "inherit",
    },
);

server.on("error", (error) => {
    throw error;
});
server.on("exit", (code, signal) => {
    if (signal !== null) {
        process.kill(process.pid, signal);
        return;
    }
    process.exit(code ?? 1);
});
for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => {
        server.kill(signal);
    });
}
