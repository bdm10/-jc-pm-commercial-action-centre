import { useI18n } from "../i18n";
import { fmtMoney, parseDate } from "../lib/format";

/** Minimal monthly bar chart; each bar has a tooltip and the series is exposed as a table for screen readers. */
export function Sparkline({ data, unit }: { data: { month: string; value: number }[]; unit: string }) {
  const { locale } = useI18n();
  if (!data.length) return null;
  const max = Math.max(1, ...data.map((d) => Math.abs(d.value)));
  const w = 100 / data.length;
  const label = (m: string) => new Intl.DateTimeFormat(locale, { month: "short", year: "2-digit" }).format(parseDate(m));
  return (
    <figure style={{ margin: 0 }}>
      <svg className="sparkline" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
        <line x1="0" x2="100" y1="39.5" y2="39.5" stroke="var(--line-strong)" strokeWidth="0.3" />
        {data.map((d, i) => {
          const h = (Math.max(0, d.value) / max) * 36;
          return (
            <rect key={d.month} x={i * w + w * 0.15} width={w * 0.7} y={39.5 - h} height={h} rx="0.6" fill={i >= data.length - 12 ? "var(--ink-2)" : "var(--line-strong)"}>
              <title>{`${label(d.month)}: ${fmtMoney(d.value, locale, unit)}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className="tiny muted" style={{ display: "flex", justifyContent: "space-between" }}>
        <span>{label(data[0].month)}</span>
        <span>{label(data[data.length - 1].month)}</span>
      </div>
      <table className="visually-hidden">
        <tbody>
          {data.map((d) => (
            <tr key={d.month}>
              <td>{label(d.month)}</td>
              <td>{fmtMoney(d.value, locale, unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
