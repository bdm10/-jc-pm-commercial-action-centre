import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { en } from "./en";
import { es, type MessageKey, type Messages } from "./es";

export type Lang = "es" | "en";
const CATALOGS: Record<Lang, Messages> = { es, en };
const STORAGE_KEY = "cac.lang";

export type Params = Record<string, string | number | null | undefined>;

export function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, k: string) => {
    const v = params[k];
    return v === undefined || v === null ? "" : String(v);
  });
}

export function translate(lang: Lang, key: string, params?: Params): string {
  const msg = (CATALOGS[lang] as Record<string, string>)[key] ?? (CATALOGS.es as Record<string, string>)[key];
  return msg === undefined ? key : interpolate(msg, params);
}

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: (key: MessageKey | string, params?: Params) => string; locale: string };
const I18nContext = createContext<Ctx | null>(null);

function initialLang(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "es" || stored === "en") return stored;
  } catch {
    /* storage unavailable: fall back to Spanish */
  }
  return "es";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
    document.documentElement.lang = l;
  }, []);
  const value = useMemo<Ctx>(
    () => ({ lang, setLang, t: (key, params) => translate(lang, key, params), locale: lang === "es" ? "es-ES" : "en-GB" }),
    [lang, setLang],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): Ctx {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n outside I18nProvider");
  return ctx;
}
