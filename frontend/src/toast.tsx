import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Check, AlertTriangle, Info } from "lucide-react";

type Kind = "ok" | "warn" | "info";
interface Toast { id: number; kind: Kind; text: string }

const Ctx = createContext<(text: string, kind?: Kind) => void>(() => {});

/** Fire a transient message. Safe to call from anywhere under the provider. */
export const useToast = () => useContext(Ctx);

const ICON = { ok: Check, warn: AlertTriangle, info: Info } as const;

export function ToastHost({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const next = useRef(1);
  const timers = useRef<Map<number, number>>(new Map());

  const push = useCallback((text: string, kind: Kind = "ok") => {
    const id = next.current++;
    setItems((xs) => [...xs.slice(-2), { id, kind, text }]);
    const t = window.setTimeout(() => {
      setItems((xs) => xs.filter((x) => x.id !== id));
      timers.current.delete(id);
    }, 3200);
    timers.current.set(id, t);
  }, []);

  // A toast fired just before unmount would otherwise leave a live timer behind.
  useEffect(() => {
    const map = timers.current;
    return () => { map.forEach((t) => clearTimeout(t)); map.clear(); };
  }, []);

  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toastHost" role="status" aria-live="polite">
        {items.map((t) => {
          const Icon = ICON[t.kind];
          return (
            <div className={`toast toast-${t.kind}`} key={t.id}>
              <Icon size={14} strokeWidth={2.4} />
              <span>{t.text}</span>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}
