import { ReactNode } from "react";

type Format = "azn" | "number" | "percent" | "days" | "raw";
type Tone = "default" | "good" | "warn" | "bad";

interface Props {
  label: string;
  value: number | string | null | undefined;
  format?: Format;
  delta?: { value: number | null; period?: string };
  tone?: Tone;
  sub?: string;
  loading?: boolean;
  icon?: ReactNode;
}

const toneColor: Record<Tone, string> = {
  default: "text-blue-600",
  good: "text-green-600",
  warn: "text-orange-500",
  bad: "text-red-500",
};

function formatValue(v: number | string | null | undefined, fmt: Format): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  switch (fmt) {
    case "azn":
      return `${Math.round(v).toLocaleString()} AZN`;
    case "percent":
      return `${(v * 100).toFixed(1)}%`;
    case "days":
      return `${v.toFixed(1)} gün`;
    case "number":
      return Math.round(v).toLocaleString();
    default:
      return String(v);
  }
}

export default function KpiCard({ label, value, format = "number", delta, tone = "default", sub, loading, icon }: Props) {
  const displayValue = loading ? "…" : formatValue(value, format);

  const deltaColor =
    delta?.value == null ? "text-gray-400"
      : delta.value > 0 ? "text-green-600"
      : "text-red-500";
  const deltaArrow = delta?.value == null ? "" : delta.value > 0 ? "↑" : "↓";

  return (
    <div className="bg-white rounded-lg border p-4 flex flex-col gap-1">
      <div className="text-xs text-gray-500 font-medium truncate flex items-center gap-1">
        {icon && <span className="shrink-0">{icon}</span>}
        {label}
      </div>
      <div className={`text-xl font-bold leading-tight ${toneColor[tone]} ${loading ? "animate-pulse" : ""}`}>
        {displayValue}
      </div>
      {delta && delta.value !== null && (
        <div className={`text-xs ${deltaColor}`}>
          {deltaArrow} {Math.abs(delta.value).toFixed(1)}%
          {delta.period && <span className="text-gray-400 ml-1">{delta.period}</span>}
        </div>
      )}
      {sub && <div className="text-xs text-gray-400 truncate">{sub}</div>}
    </div>
  );
}
