import * as Sentry from "@sentry/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import { SentryErrorFallback } from "./components/layout/SentryErrorFallback.tsx";
import "./index.css";
import { initFrontendSentry } from "./utils/sentry.ts";

initFrontendSentry();

const rootElement = document.getElementById("root");
if (!rootElement) {
    throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
    <StrictMode>
        <Sentry.ErrorBoundary fallback={() => <SentryErrorFallback />}>
            <App />
        </Sentry.ErrorBoundary>
    </StrictMode>,
);
