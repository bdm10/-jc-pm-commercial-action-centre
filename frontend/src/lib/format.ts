// Locale-aware formatting. Dates from the API are ISO strings; plain dates are parsed as local dates to avoid TZ shifts.

export function parseDate(iso: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(iso);
}

export function fmtDate(iso: string | null | undefined, locale: string, withYear = true): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}) }).format(parseDate(iso));
}

export function fmtLongDate(iso: string, locale: string): string {
  const s = new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "long" }).format(parseDate(iso));
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function fmtDateTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" }).format(new Date(iso));
}

export function fmtMoney(v: number, locale: string, unit = "EUR"): string {
  const currency = /^[A-Z]{3}$/.test(unit) ? unit : "EUR";
  return new Intl.NumberFormat(locale, { style: "currency", currency, maximumFractionDigits: 0 }).format(v);
}

export function fmtPct(v: number, locale: string, signed = false): string {
  const s = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1, ...(signed ? { signDisplay: "exceptZero" } : {}) });
  return s.format((signed ? v : Math.abs(v)) / 100);
}

export function fmtNumber(v: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(v);
}

export function fmtMonthRange(start: string, end: string, locale: string): string {
  const a = parseDate(start);
  const b = parseDate(end);
  const m = (d: Date) => new Intl.DateTimeFormat(locale, { month: "short" }).format(d).replace(".", "");
  return a.getFullYear() === b.getFullYear() ? `${m(a)}–${m(b)} ${b.getFullYear()}` : `${m(a)} ${a.getFullYear()}–${m(b)} ${b.getFullYear()}`;
}

export function addDays(iso: string, days: number): string {
  const d = parseDate(iso);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
