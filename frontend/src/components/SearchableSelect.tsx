import { useEffect, useRef, useState } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  options: Array<{ value: string; label: string }>;
}

export default function SearchableSelect({ value, onChange, placeholder, options }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const currentLabel = options.find((o) => o.value === value)?.label ?? "";

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = query
    ? options.filter((o) => o.label.toLowerCase().includes(query.toLowerCase()))
    : options;

  return (
    <div ref={containerRef} className="relative">
      <input
        type="text"
        className="border rounded px-2 py-1.5 text-sm w-full bg-white"
        placeholder={placeholder}
        value={open ? query : currentLabel}
        onFocus={() => setOpen(true)}
        onChange={(e) => { setOpen(true); setQuery(e.target.value); }}
      />
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-white border rounded shadow-lg max-h-52 overflow-y-auto">
          <div
            className="px-3 py-1.5 text-sm text-gray-400 cursor-pointer hover:bg-gray-50"
            onMouseDown={() => { onChange(""); setOpen(false); }}
          >
            {placeholder}
          </div>
          {filtered.map((o) => (
            <div
              key={o.value}
              className={`px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 ${value === o.value ? "bg-blue-50 text-blue-700 font-medium" : ""}`}
              onMouseDown={() => { onChange(o.value); setOpen(false); }}
            >
              {o.label}
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="px-3 py-1.5 text-sm text-gray-400">Tapılmadı</div>
          )}
        </div>
      )}
    </div>
  );
}
