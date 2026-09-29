/* Theme handling.
 *
 * Three values, matching the backend's `ThemeRequest` pattern
 * `^(light|dark|system)$`. The choice is stored locally and, once signed in,
 * also saved to the user's profile so it follows them between devices.
 */

import { useCallback, useEffect, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const KEY = "sa.theme";

function readPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // Storage unavailable; fall through to the default.
  }
  return "system";
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyPreference(pref: ThemePreference): ResolvedTheme {
  const resolved = pref === "system" ? systemTheme() : pref;
  document.documentElement.setAttribute("data-theme", resolved);
  return resolved;
}

export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    applyPreference(readPreference()),
  );

  useEffect(() => {
    setResolved(applyPreference(preference));
    try {
      window.localStorage.setItem(KEY, preference);
    } catch {
      // Non-fatal: the theme still applies for this page view.
    }
  }, [preference]);

  // Track the OS setting while the preference is "system".
  useEffect(() => {
    if (preference !== "system" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(applyPreference("system"));
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [preference]);

  const toggle = useCallback(() => {
    setPreference((prev) => {
      const current = prev === "system" ? systemTheme() : prev;
      return current === "dark" ? "light" : "dark";
    });
  }, []);

  return { preference, resolved, setPreference, toggle };
}
