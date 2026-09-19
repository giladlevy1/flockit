import clsx from "clsx";
import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export interface Option {
  value: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
}

/** A compact filter pill that opens a searchable checklist. */
export function MultiSelect({
  label,
  options,
  value,
  onChange,
  searchable,
}: {
  label: string;
  options: Option[];
  value: string[];
  onChange: (next: string[]) => void;
  searchable?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q) || o.hint?.toLowerCase().includes(q)) : options;
  }, [options, query]);

  const selected = options.filter((o) => value.includes(o.value));
  const summary =
    selected.length === 0 ? null : selected.length === 1 ? selected[0].label : `${selected.length} selected`;

  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={clsx(
          "inline-flex h-8 max-w-[240px] items-center gap-1.5 rounded-lg border px-2.5 text-[13px] transition-colors",
          selected.length
            ? "border-accent/40 bg-accent-soft text-accent-ink"
            : "border-line bg-surface text-ink-2 hover:bg-surface-2",
        )}
      >
        <span className={clsx(selected.length ? "font-medium" : "")}>{label}</span>
        {summary && <span className="truncate text-ink">· {summary}</span>}
        <ChevronDown className="size-3.5 shrink-0 opacity-60" />
      </button>
      {open && (
        <div className="absolute left-0 z-30 mt-1.5 w-72 overflow-hidden rounded-xl border border-line bg-surface shadow-xl">
          {(searchable ?? options.length > 7) && (
            <div className="flex items-center gap-2 border-b border-line px-3">
              <Search className="size-3.5 text-muted" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={`Search ${label.toLowerCase()}…`}
                className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted"
              />
            </div>
          )}
          <ul className="max-h-72 overflow-y-auto p-1" role="listbox" aria-multiselectable>
            {filtered.length === 0 && <li className="px-3 py-2 text-sm text-muted">Nothing matches</li>}
            {filtered.map((o) => {
              const on = value.includes(o.value);
              return (
                <li key={o.value}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={on}
                    onClick={() => toggle(o.value)}
                    className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-surface-2"
                  >
                    <span
                      className={clsx(
                        "flex size-4 shrink-0 items-center justify-center rounded border",
                        on ? "border-accent bg-accent text-white" : "border-line-strong",
                      )}
                    >
                      {on && <Check className="size-3" strokeWidth={3} />}
                    </span>
                    {o.icon}
                    <span className="min-w-0 flex-1 truncate">{o.label}</span>
                    {o.hint && <span className="shrink-0 truncate text-xs text-muted">{o.hint}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
          {value.length > 0 && (
            <div className="border-t border-line p-1">
              <button
                type="button"
                onClick={() => onChange([])}
                className="w-full rounded-lg px-2.5 py-1.5 text-left text-[13px] text-muted hover:bg-surface-2 hover:text-ink"
              >
                Clear {label.toLowerCase()}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
