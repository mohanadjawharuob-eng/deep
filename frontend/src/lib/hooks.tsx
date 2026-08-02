/**
 * Session, theme, and the two data hooks every screen uses.
 *
 * Deliberately small. A data layer with caching, invalidation and
 * subscriptions is the right answer for an application whose screens fight
 * over the same records; this one mostly loads a list, shows it, and reloads
 * when something changes. `useQuery` below is forty lines and does that
 * correctly, including cancelling on unmount — which is the bug an ad-hoc
 * `useEffect` fetch always eventually has.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  ApiError,
  SESSION_ENDED,
  api,
  tokens,
  type CurrentUser,
  type ModuleAccess,
  type ModuleName,
} from "./api";

/* --------------------------------------------------------------------------
 * Theme
 * ----------------------------------------------------------------------- */
type Theme = "light" | "dark" | "system";

const ThemeContext = createContext<{
  theme: Theme;
  resolved: "light" | "dark";
  setTheme: (theme: Theme) => void;
}>({ theme: "system", resolved: "light", setTheme: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem("archeo.theme") as Theme) ?? "system",
  );
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, []);

  const resolved = theme === "system" ? (systemDark ? "dark" : "light") : theme;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  const setTheme = useCallback((next: Theme) => {
    localStorage.setItem("archeo.theme", next);
    setThemeState(next);
  }, []);

  const value = useMemo(() => ({ theme, resolved, setTheme }), [theme, resolved, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);

/* --------------------------------------------------------------------------
 * Session
 * ----------------------------------------------------------------------- */
type Session = {
  user: CurrentUser | null;
  access: ModuleAccess | null;
  loading: boolean;
  signIn: (identifier: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Fetch the account again. Called after changing something the session
      carries a copy of — a photograph, a module grant. */
  reload: () => Promise<void>;
  /** The level held in a module, or null. Administrators hold every module. */
  levelIn: (module: ModuleName) => string | null;
  can: (module: ModuleName, minimum: string) => boolean;
};

const LEVELS = ["viewer", "contributor", "editor", "supervisor", "administrator"];

const SessionContext = createContext<Session>({
  user: null,
  access: null,
  loading: true,
  signIn: async () => {},
  signOut: async () => {},
  reload: async () => {},
  levelIn: () => null,
  can: () => false,
});

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [access, setAccess] = useState<ModuleAccess | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!tokens.access()) {
      setUser(null);
      setAccess(null);
      setLoading(false);
      return;
    }
    try {
      const [me, modules] = await Promise.all([
        api.get<CurrentUser>("/auth/me"),
        api.get<ModuleAccess>("/users/me/access"),
      ]);
      setUser(me);
      setAccess(modules);
    } catch {
      setUser(null);
      setAccess(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const ended = () => {
      setUser(null);
      setAccess(null);
    };
    window.addEventListener(SESSION_ENDED, ended);
    return () => window.removeEventListener(SESSION_ENDED, ended);
  }, [load]);

  const signIn = useCallback(
    async (identifier: string, password: string) => {
      await api.login(identifier, password);
      setLoading(true);
      await load();
    },
    [load],
  );

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
    setAccess(null);
  }, []);

  const levelIn = useCallback(
    (module: ModuleName) => {
      if (!access) return null;
      if (access.is_platform_admin) return "administrator";
      return access.access[module] ?? null;
    },
    [access],
  );

  const can = useCallback(
    (module: ModuleName, minimum: string) => {
      const held = levelIn(module);
      if (!held) return false;
      return LEVELS.indexOf(held) >= LEVELS.indexOf(minimum);
    },
    [levelIn],
  );

  const value = useMemo(
    () => ({ user, access, loading, signIn, signOut, reload: load, levelIn, can }),
    [user, access, loading, signIn, signOut, load, levelIn, can],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export const useSession = () => useContext(SessionContext);

/* --------------------------------------------------------------------------
 * Branding
 *
 * Whose installation this is. Loaded once and shared, because the sidebar, the
 * sign-in page and the browser tab all want it and none of them should each be
 * making the request.
 *
 * Above `SessionProvider` on purpose: the sign-in page has nobody signed in
 * and still has to draw the mark, so this must not depend on a session.
 * ----------------------------------------------------------------------- */
export type Branding = {
  organisation_name: string | null;
  tagline: string | null;
  footer_note: string | null;
  logo_url: string | null;
  display_name: string;
};

const FALLBACK: Branding = {
  organisation_name: null,
  tagline: null,
  footer_note: null,
  logo_url: null,
  display_name: "Stratum",
};

const BrandingContext = createContext<{
  branding: Branding;
  /** Called by the administration screen after changing it, so every page
      updates without a reload. */
  refresh: () => Promise<void>;
}>({ branding: FALLBACK, refresh: async () => {} });

export function BrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<Branding>(FALLBACK);

  const refresh = useCallback(async () => {
    try {
      setBranding(await api.get<Branding>("/branding"));
    } catch {
      // An installation that has set nothing, or an API not up yet. The
      // platform's own name is a perfectly good answer, and a failure here
      // must never keep the sign-in page off the screen.
      setBranding(FALLBACK);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // The tab, too. Somebody with nine tabs open needs to know which is theirs.
  useEffect(() => {
    document.title = branding.display_name;
  }, [branding.display_name]);

  const value = useMemo(() => ({ branding, refresh }), [branding, refresh]);
  return <BrandingContext.Provider value={value}>{children}</BrandingContext.Provider>;
}

export const useBranding = () => useContext(BrandingContext);

/* --------------------------------------------------------------------------
 * Data
 * ----------------------------------------------------------------------- */
export type QueryState<T> = {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

/**
 * Load something once, and again whenever `deps` change.
 *
 * The abort controller is the point: a screen navigated away from mid-request
 * must not set state when the response lands, and must not surface the
 * resulting "aborted" as an error to the user.
 */
export function useQuery<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
  options: { enabled?: boolean } = {},
): QueryState<T> {
  const enabled = options.enabled ?? true;
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [nonce, setNonce] = useState(0);

  // Kept in a ref so a caller passing an inline arrow does not re-run the
  // effect on every render.
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    loaderRef
      .current(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof ApiError ? cause.message : "Something went wrong");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { data, error, loading, reload };
}

/** A value that only updates once typing pauses — for search-as-you-type. */
export function useDebounced<T>(value: T, delay = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

/**
 * Run an action, tracking whether it is in flight and what it complained about.
 *
 * The action is held in a ref, and this is not a detail. `run` has to keep a
 * stable identity — callers pass it to `onClick` — but memoising it with an
 * empty dependency list would also freeze the *closure*, so the callback would
 * for ever read the state as it stood on the first render. A Save button
 * written the obvious way then posts an empty change set and reports success:
 * the screen closes, nothing is written, and nobody finds out until they
 * reopen the record.
 *
 * The ref is refreshed on every render, so `run` is stable and what it reads
 * is current.
 */
export function useAction<Args extends unknown[], Result>(
  action: (...args: Args) => Promise<Result>,
) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const actionRef = useRef(action);
  actionRef.current = action;

  const run = useCallback(async (...args: Args) => {
    setRunning(true);
    setError(null);
    try {
      return await actionRef.current(...args);
    } catch (cause) {
      setError(
        cause instanceof ApiError || cause instanceof Error
          ? cause.message
          : "Something went wrong",
      );
      return undefined;
    } finally {
      setRunning(false);
    }
  }, []);

  return { run, running, error, clearError: () => setError(null) };
}
