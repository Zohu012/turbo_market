import { ReactNode } from "react";
import { ResponsiveContainer } from "recharts";
import ChartEmptyState from "./ChartEmptyState";

interface Props {
  title: string;
  subtitle?: string;
  height?: number;
  loading?: boolean;
  error?: string | null;
  empty?: boolean;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export default function ChartCard({
  title,
  subtitle,
  height = 280,
  loading,
  error,
  empty,
  children,
  actions,
  className = "",
}: Props) {
  const showPlaceholder = loading || error || empty;

  return (
    <div className={`bg-white rounded-lg border p-4 ${className}`}>
      <div className="flex items-start justify-between mb-3 gap-2">
        <div>
          <h3 className="font-semibold text-gray-700 text-sm">{title}</h3>
          {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
        </div>
        {actions && <div className="shrink-0 flex gap-1">{actions}</div>}
      </div>

      <div style={{ height }}>
        {showPlaceholder ? (
          <ChartEmptyState
            message={
              loading ? "Yüklənir…"
                : error ? `Xəta: ${error}`
                : undefined
            }
          />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            {children as React.ReactElement}
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
