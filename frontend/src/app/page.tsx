import {
  ArrowRight,
  Lightbulb,
  MousePointerClick,
  PencilRuler,
  Route,
  ShoppingCart,
  Sofa,
  Sparkles,
  Wand2,
} from "lucide-react";
import Link from "next/link";

const STEPS = [
  {
    icon: PencilRuler,
    title: "Draw your room",
    body: "Sketch walls, doors and windows in real measurements - or start from a template.",
  },
  {
    icon: Sofa,
    title: "Get guided, piece by piece",
    body: "ZORY reads your layout and recommends the right product, size and spot - sofa first, decor last.",
  },
  {
    icon: ShoppingCart,
    title: "Shop the whole room",
    body: "Best match, budget and premium picks for every step. Add the full setup to cart in one tap.",
  },
];

const FEATURES = [
  { icon: Route, title: "Walkways stay clear", body: "Door swings and walking paths are protected automatically." },
  { icon: Wand2, title: "Auto-fix placements", body: "Bad spot? One tap nudges furniture to where it works." },
  { icon: Lightbulb, title: "Explained choices", body: "Every pick comes with why this product, size and position." },
  { icon: Sparkles, title: "3D & AI previews", body: "Orbit your room in interactive 3D, or generate a photoreal AI preview." },
];

/** Hero illustration: a miniature of the actual planner canvas, drawn as SVG. */
function HeroFloorPlan() {
  return (
    <svg viewBox="0 0 560 430" role="img" aria-label="Example floor plan with a highlighted sofa zone" className="w-full drop-shadow-sm">
      {/* floor + walls */}
      <rect x="40" y="36" width="480" height="354" rx="6" fill="#F3EDE3" stroke="#292524" strokeWidth="12" />
      {/* door opening + swing (top-left) */}
      <line x1="80" y1="36" x2="160" y2="36" stroke="#FAFAF8" strokeWidth="16" />
      <path d="M 80 38 A 80 80 0 0 1 160 118" fill="rgba(41,37,36,0.05)" stroke="#A8A29E" strokeWidth="1.5" strokeDasharray="5 4" />
      <line x1="80" y1="38" x2="80" y2="118" stroke="#57534E" strokeWidth="3" strokeLinecap="round" />
      {/* window (bottom) */}
      <line x1="220" y1="390" x2="360" y2="390" stroke="#FAFAF8" strokeWidth="16" />
      <rect x="220" y="384" width="140" height="12" fill="#FFFFFF" stroke="#57534E" strokeWidth="1.5" />
      {/* rug */}
      <rect x="120" y="118" width="246" height="196" rx="6" fill="#E7DCC7" stroke="#D6C9B4" strokeWidth="2" />
      <rect x="134" y="131" width="218" height="170" rx="4" fill="none" stroke="#D6C9B4" strokeWidth="1.5" />
      {/* recommended zone (right wall) */}
      <rect x="396" y="78" width="112" height="276" rx="8" fill="rgba(217,119,6,0.10)" stroke="#D97706" strokeWidth="2" strokeDasharray="9 6" />
      {/* sofa inside the zone (back to the right wall) with cushions */}
      <g>
        <rect x="412" y="106" width="84" height="220" rx="10" fill="#D9CDB8" stroke="#B5A48B" strokeWidth="1.5" />
        <rect x="474" y="110" width="18" height="212" rx="6" fill="#CFC2AA" />
        <rect x="418" y="114" width="52" height="98" rx="5" fill="#E3D9C5" />
        <rect x="418" y="218" width="52" height="98" rx="5" fill="#E3D9C5" />
      </g>
      {/* tv unit (left wall, opposite the sofa) */}
      <rect x="48" y="150" width="30" height="150" rx="3" fill="#8A6748" />
      <rect x="80" y="178" width="5" height="94" rx="2" fill="#3A3531" />
      {/* coffee table (round) */}
      <circle cx="250" cy="216" r="36" fill="#C9A876" stroke="#A87E51" strokeWidth="1.5" />
      <circle cx="250" cy="216" r="27" fill="none" stroke="#A87E51" strokeWidth="1" opacity="0.6" />
      {/* accent chair (top-centre, angled toward seating) */}
      <g transform="rotate(152 235 96)">
        <rect x="205" y="66" width="60" height="60" rx="12" fill="#E3D9C5" stroke="#B5A48B" strokeWidth="1.5" />
        <rect x="209" y="70" width="52" height="14" rx="6" fill="#CFC2AA" />
      </g>
      {/* plants */}
      <g>
        <circle cx="78" cy="352" r="17" fill="#6C8159" /><circle cx="90" cy="342" r="11" fill="#5F7350" /><circle cx="68" cy="340" r="9" fill="#7B9067" />
      </g>
      {/* floor lamp */}
      <circle cx="180" cy="352" r="15" fill="#F6EFE2" stroke="#B08D4F" strokeWidth="1.5" />
      <circle cx="180" cy="352" r="5" fill="#B08D4F" />
      {/* dimension labels */}
      <text x="280" y="20" textAnchor="middle" fontFamily="Inter, sans-serif" fontSize="11" fill="#78716C">4.80 m</text>
      <text x="22" y="216" textAnchor="middle" fontFamily="Inter, sans-serif" fontSize="11" fill="#78716C" transform="rotate(-90 22 216)">3.60 m</text>
      {/* zone label chip + price chip drawn last so nothing covers them */}
      <g>
        <rect x="332" y="56" width="160" height="27" rx="13.5" fill="#FDE9CC" stroke="#D97706" strokeWidth="1" />
        <text x="412" y="74" textAnchor="middle" fontFamily="Inter, sans-serif" fontSize="12.5" fontWeight="700" fill="#92400E">Best wall for sofa</text>
      </g>
      <g>
        <rect x="394" y="394" width="126" height="27" rx="13.5" fill="#1C1917" />
        <text x="457" y="412" textAnchor="middle" fontFamily="Inter, sans-serif" fontSize="12" fontWeight="600" fill="#FAFAF8">SAR 10,530</text>
      </g>
    </svg>
  );
}

export default function Home() {
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-5">
        <span className="text-xl font-black tracking-tight">ZORY</span>
        <Link
          href="/planner"
          className="rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-accent-ink transition-colors hover:bg-ink-soft"
        >
          Start planning
        </Link>
      </header>

      <main className="flex-1">
        {/* hero */}
        <section className="mx-auto grid w-full max-w-6xl items-center gap-10 px-5 py-12 sm:py-16 lg:grid-cols-2 lg:gap-14">
          <div className="max-w-xl">
            <p className="inline-flex items-center gap-1.5 rounded-full border border-amber/30 bg-amber-soft px-3 py-1 text-xs font-semibold text-amber-deep">
              <Sparkles className="h-3.5 w-3.5" />
              Guided shopping, built on your floor plan
            </p>
            <h1 className="mt-5 text-4xl font-black leading-tight tracking-tight text-ink sm:text-5xl 3xl:text-6xl">
              Plan your room and shop the right products in one guided experience.
            </h1>
            <p className="mt-4 text-base leading-7 text-ink-soft sm:text-lg">
              Draw your floor plan, and ZORY guides you one decision at a time - what to place, where it
              goes, and why it fits. From empty room to shoppable layout.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              <Link
                href="/planner"
                className="inline-flex items-center gap-2 rounded-full bg-accent px-6 py-3.5 text-sm font-semibold text-accent-ink transition-colors hover:bg-ink-soft"
              >
                Plan my living room
                <ArrowRight className="h-4 w-4" />
              </Link>
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-faint">
                <MousePointerClick className="h-4 w-4" />
                No sign-up needed
              </span>
            </div>
          </div>

          {/* miniature of the real planner canvas */}
          <div className="mx-auto w-full max-w-lg" aria-hidden>
            <HeroFloorPlan />
          </div>
        </section>

        {/* how it works */}
        <section className="border-y border-line bg-surface">
          <div className="mx-auto w-full max-w-6xl px-5 py-12 sm:py-16">
            <h2 className="text-center text-2xl font-bold tracking-tight sm:text-3xl">
              From floor plan to furnished room
            </h2>
            <div className="mt-10 grid gap-6 sm:grid-cols-3">
              {STEPS.map(({ icon: Icon, title, body }, i) => (
                <div key={title} className="rounded-xl border border-line bg-bg p-6">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-soft text-amber-deep">
                      <Icon className="h-5 w-5" />
                    </span>
                    <span className="text-xs font-bold text-ink-faint">STEP {i + 1}</span>
                  </div>
                  <h3 className="mt-4 text-base font-bold">{title}</h3>
                  <p className="mt-1.5 text-sm leading-6 text-ink-soft">{body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* features */}
        <section className="mx-auto w-full max-w-6xl px-5 py-12 sm:py-16">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="rounded-xl border border-line bg-surface p-5">
                <Icon className="h-5 w-5 text-amber-deep" />
                <h3 className="mt-3 text-sm font-bold">{title}</h3>
                <p className="mt-1 text-xs leading-5 text-ink-soft">{body}</p>
              </div>
            ))}
          </div>
          <div className="mt-12 flex justify-center">
            <Link
              href="/planner"
              className="inline-flex items-center gap-2 rounded-full bg-accent px-7 py-4 text-sm font-semibold text-accent-ink transition-colors hover:bg-ink-soft"
            >
              Start with a sample room
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-line bg-surface">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-2 px-5 py-6 text-xs text-ink-faint">
          <span className="font-bold text-ink">ZORY</span>
          <span>Guided shopping & spatial planning - demo build</span>
        </div>
      </footer>
    </div>
  );
}
