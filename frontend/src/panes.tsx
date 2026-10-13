import { Component, lazy, Suspense, type ReactNode } from "react";

/**
 * The analysis panes are loaded on demand. Together they carry Recharts and most of
 * the app's code, and a visitor on the landing page or the Simulator needs none of it, so
 * keeping them out of the first bundle is the largest single speed-up available.
 *
 * Loading stays invisible in practice: the panes are fetched in the background once the
 * page is idle, and again the moment a tab is hovered or focused, so a click lands on code
 * that has usually already arrived. If it has not, a skeleton the same shape as the pane
 * holds the space so nothing jumps.
 */
export type PaneKey = "comparison" | "hosting" | "regions" | "control" | "results" | "signals" | "india";

const loaders: Record<PaneKey, () => Promise<unknown>> = {
  comparison: () => import("./Comparison"),
  hosting: () => import("./Hosting"),
  regions: () => import("./Regions"),
  control: () => import("./Control"),
  results: () => import("./Results"),
  signals: () => import("./Signals"),
  india: () => import("./India"),
};

export const Comparison = lazy(() => import("./Comparison"));
export const Hosting = lazy(() => import("./Hosting"));
export const Regions = lazy(() => import("./Regions"));
export const Control = lazy(() => import("./Control"));
export const Results = lazy(() => import("./Results"));
export const Signals = lazy(() => import("./Signals"));
export const India = lazy(() => import("./India"));

/** Start fetching one pane's code. Safe to call repeatedly; the browser caches the module. */
export function prefetch(key: string): void {
  loaders[key as PaneKey]?.().catch(() => {
    /* a failed prefetch just means a normal load later */
  });
}

/** Fetch every pane when the browser has nothing better to do. */
export function prefetchAll(): void {
  const run = () => (Object.keys(loaders) as PaneKey[]).forEach((k, i) => setTimeout(() => prefetch(k), i * 120));
  const ric = (window as unknown as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => void }).requestIdleCallback;
  if (ric) ric(run, { timeout: 4000 });
  else setTimeout(run, 2000);
}

/** The shape of a pane (a hero and two cards), so loading holds the space and nothing shifts. */
export function PaneSkeleton() {
  return (
    <div aria-busy="true" aria-live="polite" aria-label="Loading">
      <div className="skel" style={{ height: 150, marginBottom: 16, borderRadius: "var(--radius)" }} />
      <div className="skel" style={{ height: 280, marginBottom: 16, borderRadius: "var(--radius)" }} />
      <div className="skel" style={{ height: 220, borderRadius: "var(--radius)" }} />
    </div>
  );
}

/**
 * A pane's code is a separate file with a hashed name. A visitor who keeps a tab open across a
 * deploy asks for a file that no longer exists, and without a boundary the page goes blank.
 * This turns that into a one-click reload, and reloads once on its own.
 */
class PaneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(err: unknown) {
    console.warn("A pane failed to load", err);
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="errorState" role="alert">
        <div className="errorStateBody">
          <strong>This section could not load</strong>
          <p>The site was probably updated while this tab was open. Reloading fetches the new version.</p>
        </div>
        <button className="errorStateBtn" type="button" onClick={() => window.location.reload()}>Reload</button>
      </div>
    );
  }
}

export function Pane({ children }: { children: ReactNode }) {
  return (
    <PaneBoundary>
      <Suspense fallback={<PaneSkeleton />}>{children}</Suspense>
    </PaneBoundary>
  );
}

// Vite fires this when a dynamic import's file is gone. Reload once, then leave it to the boundary.
if (typeof window !== "undefined") {
  window.addEventListener("vite:preloadError", () => {
    try {
      if (sessionStorage.getItem("gs-reloaded")) return;
      sessionStorage.setItem("gs-reloaded", "1");
    } catch { /* private mode: fall through to the boundary */ }
    window.location.reload();
  });
}
