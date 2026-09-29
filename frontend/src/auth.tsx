/* Authentication context.
 *
 * The JWT lives in localStorage and is attached to every request by
 * `app/api.ts`. This provider owns the current user and the login/register/logout
 * actions, and clears the session on any 401 so a revoked token (logout
 * elsewhere, or a password change) does not leave the UI in a half-authenticated
 * state.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError, auth, getToken, setToken } from "./api";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName?: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  /** Attach the session to the profile so it follows the user. */
  saveTheme: (theme: string) => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(() => getToken() !== null);

  const clear = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const loadUser = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await auth.me());
    } catch (err) {
      // An expired or revoked token must not strand the session.
      if (err instanceof ApiError && err.status === 401) clear();
      else setUser(null);
    } finally {
      setLoading(false);
    }
  }, [clear]);

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await auth.login(email, password);
    setToken(res.access_token);
    setUser(res.user);
  }, []);

  const register = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const res = await auth.register(email, password, displayName);
      setToken(res.access_token);
      setUser(res.user);
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await auth.logout();
    } catch {
      // Revoking server-side is best effort; drop the local token regardless.
    } finally {
      clear();
    }
  }, [clear]);

  const saveTheme = useCallback(async (theme: string) => {
    if (!getToken()) return;
    try {
      setUser(await auth.setTheme(theme));
    } catch {
      // Theme persistence is a convenience, never a blocker.
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, loading, login, register, logout, refresh: loadUser, saveTheme }),
    [user, loading, login, register, logout, loadUser, saveTheme],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
