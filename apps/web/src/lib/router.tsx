/* eslint-disable react-refresh/only-export-components */
import {
    Children,
    createContext,
    isValidElement,
    type MouseEvent,
    type ReactNode,
    useContext,
    useEffect,
    useMemo,
    useState,
} from "react";

export interface RouterLocation {
    pathname: string;
    search: string;
}

interface RouterContextValue {
    basename: string;
    location: RouterLocation;
    navigate: (target: string, replace?: boolean) => void;
}

const RouterContext = createContext<RouterContextValue | null>(null);
const OutletContext = createContext<ReactNode>(null);

function normaliseBasename(value: string): string {
    const withLeadingSlash = value.startsWith("/") ? value : `/${value}`;
    const withoutTrailingSlash = withLeadingSlash.replace(/\/+$/, "");
    return withoutTrailingSlash === "/" ? "" : withoutTrailingSlash;
}

function parseTarget(target: string): RouterLocation {
    const url = new URL(target, "https://drawdown-ledger.invalid");
    return {
        pathname: url.pathname || "/",
        search: url.search,
    };
}

function locationFromWindow(basename: string): RouterLocation {
    const pathname = window.location.pathname.startsWith(basename)
        ? window.location.pathname.slice(basename.length) || "/"
        : window.location.pathname;
    return { pathname, search: window.location.search };
}

interface BrowserRouterProps {
    children: ReactNode;
    basename?: string;
}

export function BrowserRouter({
    children,
    basename = "/",
}: BrowserRouterProps) {
    const resolvedBasename = useMemo(
        () => normaliseBasename(basename),
        [basename],
    );
    const [location, setLocation] = useState(() =>
        locationFromWindow(resolvedBasename),
    );

    useEffect(() => {
        const updateLocation = () =>
            setLocation(locationFromWindow(resolvedBasename));
        window.addEventListener("popstate", updateLocation);
        return () => window.removeEventListener("popstate", updateLocation);
    }, [resolvedBasename]);

    const value = useMemo<RouterContextValue>(
        () => ({
            basename: resolvedBasename,
            location,
            navigate: (target, replace = false) => {
                const parsed = parseTarget(target);
                const href = `${resolvedBasename}${parsed.pathname}${parsed.search}`;
                window.history[replace ? "replaceState" : "pushState"](
                    null,
                    "",
                    href,
                );
                setLocation(parsed);
            },
        }),
        [location, resolvedBasename],
    );

    return (
        <RouterContext.Provider value={value}>
            {children}
        </RouterContext.Provider>
    );
}

interface MemoryRouterProps {
    children: ReactNode;
    initialEntries?: readonly string[];
}

export function MemoryRouter({
    children,
    initialEntries = ["/"],
}: MemoryRouterProps) {
    const [location, setLocation] = useState(() =>
        parseTarget(initialEntries[0] ?? "/"),
    );
    const value = useMemo<RouterContextValue>(
        () => ({
            basename: "",
            location,
            navigate: (target) => setLocation(parseTarget(target)),
        }),
        [location],
    );

    return (
        <RouterContext.Provider value={value}>
            {children}
        </RouterContext.Provider>
    );
}

function useRouter(): RouterContextValue {
    const value = useContext(RouterContext);
    if (value === null) {
        throw new Error("Router components must be rendered inside a router");
    }
    return value;
}

export function useLocation(): RouterLocation {
    return useRouter().location;
}

export function useSearchParams(): readonly [URLSearchParams] {
    const { search } = useLocation();
    return useMemo(() => [new URLSearchParams(search)] as const, [search]);
}

interface LinkProps {
    to: string;
    children: ReactNode;
    className?: string | undefined;
    "aria-current"?: "page" | "true" | undefined;
    "aria-label"?: string | undefined;
}

export function Link({
    to,
    children,
    className,
    "aria-current": ariaCurrent,
    "aria-label": ariaLabel,
}: LinkProps) {
    const { basename, navigate } = useRouter();
    const parsed = parseTarget(to);
    const href = `${basename}${parsed.pathname}${parsed.search}`;

    const followLink = (event: MouseEvent<HTMLAnchorElement>) => {
        if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
        ) {
            return;
        }
        event.preventDefault();
        navigate(to);
    };

    return (
        <a
            href={href}
            className={className}
            aria-current={ariaCurrent}
            aria-label={ariaLabel}
            onClick={followLink}
        >
            {children}
        </a>
    );
}

interface NavLinkState {
    isActive: boolean;
}

interface NavLinkProps extends Omit<LinkProps, "className" | "aria-current"> {
    end?: boolean;
    className?: string | ((state: NavLinkState) => string);
}

export function NavLink({
    to,
    end = false,
    className,
    ...props
}: NavLinkProps) {
    const { pathname } = useLocation();
    const targetPath = parseTarget(to).pathname;
    const isActive = end
        ? pathname === targetPath
        : pathname === targetPath ||
          (targetPath !== "/" && pathname.startsWith(`${targetPath}/`));
    const resolvedClassName =
        typeof className === "function" ? className({ isActive }) : className;

    return (
        <Link
            {...props}
            to={to}
            className={resolvedClassName}
            aria-current={isActive ? "page" : undefined}
        />
    );
}

export interface RouteProps {
    path?: string;
    index?: boolean;
    element?: ReactNode;
    children?: ReactNode;
}

export function Route(props: RouteProps) {
    void props;
    return null;
}

function routeMatches(pathname: string, route: RouteProps): boolean {
    if (route.index) {
        return pathname === "/";
    }
    if (route.path === "*") {
        return true;
    }
    const routePath = `/${route.path?.replace(/^\/+|\/+$/g, "") ?? ""}`;
    return pathname === routePath;
}

function routeProps(node: ReactNode): RouteProps | null {
    if (!isValidElement<RouteProps>(node) || node.type !== Route) {
        return null;
    }
    return node.props;
}

export function Routes({ children }: { children: ReactNode }) {
    const { pathname } = useLocation();
    const root = Children.toArray(children)
        .map(routeProps)
        .find((candidate) => candidate !== null);

    if (root === undefined || root === null) {
        return null;
    }

    const childRoutes = Children.toArray(root.children)
        .map(routeProps)
        .filter((candidate): candidate is RouteProps => candidate !== null);
    const match =
        childRoutes.find(
            (candidate) =>
                candidate.path !== "*" && routeMatches(pathname, candidate),
        ) ?? childRoutes.find((candidate) => candidate.path === "*");

    return (
        <OutletContext.Provider value={match?.element ?? null}>
            {root.element}
        </OutletContext.Provider>
    );
}

export function Outlet() {
    return useContext(OutletContext);
}
