import { useMemo } from "react";

import {
    capabilityFromEnvironment,
    createLiveResearchApi,
    createStaticResearchApi,
    DataCapabilityProvider,
    type DataCapability,
    type ResearchApi,
} from "../lib/api";
import { staticResearchSnapshot } from "../demo/staticSnapshot";
import { AppRoutes } from "./routes";

interface AppProps {
    api?: ResearchApi;
    capability?: DataCapability;
}

export function App({ api, capability }: AppProps) {
    const resolvedCapability = useMemo(
        () => capability ?? capabilityFromEnvironment(),
        [capability],
    );
    const resolvedApi = useMemo(
        () =>
            api ??
            (resolvedCapability.mode === "static"
                ? createStaticResearchApi(staticResearchSnapshot)
                : createLiveResearchApi()),
        [api, resolvedCapability.mode],
    );

    return (
        <DataCapabilityProvider
            api={resolvedApi}
            capability={resolvedCapability}
        >
            <AppRoutes />
        </DataCapabilityProvider>
    );
}
