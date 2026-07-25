interface RouteStateProps {
    kind: "loading" | "empty" | "error";
    title: string;
    message: string;
    actionLabel?: string;
    onAction?: () => void;
}

export function RouteState({
    kind,
    title,
    message,
    actionLabel,
    onAction,
}: RouteStateProps) {
    if (kind === "error") {
        return (
            <section
                className="route-state route-state--error"
                role="alert"
                aria-label={title}
            >
                <span className="route-state__index" aria-hidden="true">
                    !
                </span>
                <div>
                    <h2>{title}</h2>
                    <p>{message}</p>
                    {actionLabel && onAction ? (
                        <button type="button" onClick={onAction}>
                            {actionLabel}
                        </button>
                    ) : null}
                </div>
            </section>
        );
    }

    return (
        <section
            className={`route-state route-state--${kind}`}
            role="status"
            aria-live="polite"
        >
            <span className="route-state__index" aria-hidden="true">
                {kind === "loading" ? "···" : "—"}
            </span>
            <div>
                <h2>{title}</h2>
                <p>{message}</p>
            </div>
        </section>
    );
}
