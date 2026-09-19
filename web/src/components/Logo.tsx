/** Three birds in formation: many workers, one direction. */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-ink" />
      <path
        d="M7 19.5l4-3.5 4 3.5M13.5 13l3.5-3 3.5 3M18 21l3.5-3 3.5 3"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo() {
  return (
    <span className="inline-flex items-center gap-2">
      <LogoMark />
      <span className="text-[17px] font-semibold tracking-tight text-ink">Flockit</span>
    </span>
  );
}
