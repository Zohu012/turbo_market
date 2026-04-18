interface Props {
  label: string;
  value: string | number | null;
  sub?: string;
  color?: string;
}

export default function StatCard({ label, value, sub, color = "text-blue-600" }: Props) {
  return (
    <div className="bg-white rounded-lg border p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>
        {value ?? "—"}
      </p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}
