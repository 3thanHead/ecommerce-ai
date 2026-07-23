// Small shared bits used across pages.

export function Meter({ label, value, invert }: { label: string; value: number; invert?: boolean }) {
  // demand: higher is better (green). saturation: lower is better, so invert.
  const good = invert ? value < 40 : value > 60;
  const mid = value >= 40 && value <= 60;
  const color = mid ? "var(--warn)" : good ? "var(--good)" : "var(--bad)";
  return (
    <div className="meter">
      <span className="muted">{label}</span>
      <div className="bar">
        <span style={{ width: `${value}%`, background: color }} />
      </div>
      <b>{value}</b>
    </div>
  );
}

export function Banner({ children }: { children: React.ReactNode }) {
  return <div className="banner">{children}</div>;
}
