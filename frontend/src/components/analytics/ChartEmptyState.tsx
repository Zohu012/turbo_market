interface Props {
  message?: string;
}

export default function ChartEmptyState({ message }: Props) {
  return (
    <div className="flex items-center justify-center h-full min-h-[120px] text-gray-400 text-sm">
      {message ?? "Məlumat yoxdur"}
    </div>
  );
}
