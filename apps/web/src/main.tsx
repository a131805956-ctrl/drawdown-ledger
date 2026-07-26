import "@fontsource-variable/sora";
import "@fontsource-variable/noto-sans-tc";
import "@fontsource-variable/jetbrains-mono";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { BrowserRouter } from "./lib/router";
import "./styles/tokens.css";
import "./styles/global.css";

const root = document.getElementById("root");

if (root === null) {
    throw new Error("Application root element is missing");
}

createRoot(root).render(
    <StrictMode>
        <BrowserRouter basename={import.meta.env.BASE_URL}>
            <App />
        </BrowserRouter>
    </StrictMode>,
);
