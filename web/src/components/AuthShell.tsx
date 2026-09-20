import { Database, MoonStar, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import { Logo } from "./Logo";

const POINTS = [
  { icon: MoonStar, title: "Sessions that never stop", text: "A closed laptop hands the work to your own AI developer, mid-task." },
  { icon: Database, title: "Agents that test their work", text: "Each one develops against your schema and your data, not a guess." },
  { icon: ShieldCheck, title: "Your network, your data", text: "One compose file. Secrets stripped on the laptop. No telemetry, ever." },
];

export function AuthShell({ title, sub, children }: { title: string; sub: ReactNode; children: ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-[#0d1729] p-12 text-white lg:flex lg:flex-col">
        <div className="[&_.fill-ink]:fill-white/10 [&_span]:text-white">
          <Logo />
        </div>
        <div className="my-auto max-w-md">
          <h2 className="text-[34px] leading-[1.15] font-semibold tracking-tight">
            The control plane for an <span className="text-[#f07a45]">AI-native SDLC.</span>
          </h2>
          <p className="mt-4 text-[15px] leading-relaxed text-white/65">
            Your team already writes code with agents. This is the layer underneath: every session captured, work
            handed between people and AI developers, and nothing lost when a machine goes away.
          </p>
          <ul className="mt-10 space-y-5">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3.5">
                <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/8 ring-1 ring-white/10">
                  <Icon className="size-4 text-[#f07a45]" />
                </span>
                <span>
                  <span className="block text-sm font-medium">{title}</span>
                  <span className="block text-sm text-white/55">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <Formation />
      </aside>
      <section className="flex items-center justify-center px-5 py-12">
        <div className="w-full max-w-[380px]">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <div className="mt-1.5 mb-7 text-sm text-muted">{sub}</div>
          {children}
        </div>
      </section>
    </div>
  );
}

/** Decorative flock drifting across the brand panel. */
function Formation() {
  const birds = [
    [340, 120, 1],
    [380, 150, 0.8],
    [300, 150, 0.8],
    [420, 180, 0.6],
    [260, 180, 0.6],
    [460, 210, 0.45],
    [220, 210, 0.45],
  ];
  return (
    <svg className="pointer-events-none absolute -right-24 bottom-10 opacity-[0.18]" width="560" height="300" aria-hidden>
      {birds.map(([x, y, s], i) => (
        <path
          key={i}
          d={`M${x - 14 * s} ${y + 8 * s}l${14 * s} -${10 * s} ${14 * s} ${10 * s}`}
          fill="none"
          stroke="#f07a45"
          strokeWidth={3}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  );
}
