import { useEffect, useState } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  type?: string;
  className?: string;
  debounce?: number;
}

/**
 * An input that keeps local state so it feels instantly responsive,
 * and only calls `onChange` after the debounce delay.
 * Syncs back from external `value` changes (e.g., filter reset).
 */
export default function DebouncedInput({
  value,
  onChange,
  placeholder,
  type = "text",
  className = "border rounded px-2 py-1.5 text-sm w-full",
  debounce = 400,
}: Props) {
  const [local, setLocal] = useState(value);

  // Keep in sync when external value changes (reset, URL navigation, etc.)
  useEffect(() => {
    setLocal(value);
  }, [value]);

  // Fire onChange after the user stops typing
  useEffect(() => {
    if (local === value) return;
    const timer = setTimeout(() => onChange(local), debounce);
    return () => clearTimeout(timer);
  }, [local]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <input
      type={type}
      placeholder={placeholder}
      value={local}
      onChange={(e) => setLocal(e.target.value)}
      className={className}
    />
  );
}
