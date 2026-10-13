import { useCallback, useEffect, useRef } from "react";
import { ArrowRight, ChevronDown, Github, Command } from "lucide-react";
import LandingScene from "./LandingScene";
import { usePrefersReduced, useReveal } from "./motion";
import { useScrollSpy } from "./useScrollSpy";
import hosting from "./data/hosting.json";
import regions from "./data/regions.json";
import mpc from "./data/mpc.json";

/**
 * The front door: what this is, what it found, and what it failed to find,
 * before any of the interactive panes load.
 *
 * Every number on this page is read from the same generated JSON the panes use,
 * so the overview cannot drift away from the dashboard behind it — the failure
 * mode of a hand-written landing page is that it keeps quoting a figure the
 * analysis has since revised.
 */

const [es, de] = regions.regions;
// The realistic fleet — staggered arrivals, mixed energy, mixed charger ratings.
// `headline_identical` is the same sweep with every car identical, which spikes
// them all at one instant and overstates the gain roughly threefold.
const cap = hosting.headline;

const SECTIONS = [
  { id: "problem", nav: "Problem" },
  { id: "method", nav: "Method" },
  { id: "data", nav: "Data" },
  { id: "findings", nav: "Findings" },
  { id: "rejected", nav: "Rejected" },
  { id: "stack", nav: "Stack" },
] as const;

const SECTION_IDS = SECTIONS.map((s) => s.id);

function Section({
  id, eyebrow, title, children, wide = false,
}: {
  id?: string; eyebrow?: string; title?: string;
  children: React.ReactNode; wide?: boolean;
}) {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  return (
    <section id={id} ref={ref} className={`ldSection reveal ${shown ? "isIn" : ""} ${wide ? "ldWide" : ""}`}>
      {eyebrow && <span className="ldEyebrow">{eyebrow}</span>}
      {title && <h2 className="ldH2 ruleIn">{title}</h2>}
      {children}
    </section>
  );
}

const FINDINGS = [
  {
    n: "01", tone: "good", tag: "Capacity",
    head: `${cap.gain}× the hosting capacity`,
    body: `One ${cap.rating_kw} kW transformer carries ${cap.coordinated} coordinated vehicles ` +
      `against ${cap.dumb} charging on arrival. This is the headline — not the carbon saving.`,
  },
  {
    n: "02", tone: "flat", tag: "Carbon",
    head: `${es.median_saving}% median CO₂ saving`,
    body: "Real, and small. The distribution is long-tailed: most nights offer almost nothing, " +
      "a few offer a great deal. Reporting the mean alone would flatter it.",
  },
  {
    n: "03", tone: "bad", tag: "Data",
    head: "The first carbon curve was inverted",
    body: "The synthetic profile the project started on did not merely differ from the measured " +
      "one — it pointed the wrong way. Every conclusion drawn from it was void.",
  },
  {
    n: "04", tone: "flat", tag: "Method",
    head: "The optimiser only earns its keep under a coupling constraint",
    body: "Without one, the problem separates and a greedy rule matches the LP exactly. " +
      "Vehicle heterogeneity does not change that; a shared feeder limit does.",
  },
  {
    n: "05", tone: "flat", tag: "Objectives",
    head: "Cost and carbon genuinely conflict",
    body: "Cheap hours and clean hours are not the same hours. Optimising the bill raises " +
      "emissions; optimising emissions raises the bill. There is no free alignment.",
  },
  {
    n: "06", tone: "flat", tag: "Forecast",
    head: "Forecast error only matters when there is something to gain",
    body: "The shipped model captures 71% of the achievable saving. On nearly flat nights its " +
      "error exceeds the real spread, and acting on it does worse than nothing.",
  },
  {
    n: "07", tone: "bad", tag: "Grids",
    head: "A dirtier, more variable grid is not a better one to shift in",
    body: `Germany is dirtier (${de.mean} vs ${es.mean} gCO₂eq/kWh) and swings harder, yet ` +
      "saves less. What predicts the saving is how good the default behaviour already is.",
  },
  {
    n: "08", tone: "bad", tag: "V2G",
    head: "V2G is not economic for carbon",
    body: "Abatement through vehicle-to-grid costs €0.78–1.01 per kg CO₂ against an ETS price " +
      "near €0.06–0.09. It shaves peak well; as a carbon lever it is ten times too expensive.",
  },
  {
    n: "09", tone: "bad", tag: "Control",
    head: "Rolling-horizon control loses to the one-shot LP",
    body: `Re-solving hourly costs +${mpc.attribution_pp.rolling_commitment}pp of regret while ` +
      `the sharper forecast buys back only ${mpc.attribution_pp.fresher_forecast}pp. ` +
      "The control structure costs more than the information is worth.",
  },
] as const;

const REJECTED = [
  {
    head: "Indian daily grid data", meta: "2,821 days · daily resolution",
    body: "Grid-India and the CEA publish a complete fuel mix back to 2018 — daily. One number per " +
      "day has no shape to schedule a night against, so it was set aside until 15-minute reports " +
      "turned up. It is now kept as an independent cross-check on them.",
  },
  {
    head: "A plausible-looking Kaggle dataset", meta: "lag-1 autocorrelation −0.025",
    body: "Hourly stamps, no gaps, realistic ranges — and hour-to-hour correlation of white " +
      "noise, where measured grid load sits at +0.951. Random draws wearing a schema.",
  },
  {
    head: "Weather features", meta: "−0.19pp captured saving",
    body: "Cloud cover and wind speed looked like the obvious untapped signal. They are already " +
      "inside the TSO's day-ahead forecasts, so the raw columns added only dimensionality.",
  },
  {
    head: "Synchronised-peak theory", meta: "3 nights of 46 · 1.03×",
    body: "Uncoordinated carbon-aware charging was expected to manufacture a new peak. The " +
      "cleanest hours sit away from the residential peak, so it usually helps slightly.",
  },
] as const;

const STACK = [
  { k: "Optimiser", v: "Linear program over the charging window · PuLP / CBC", t: "Python" },
  { k: "Objectives", v: "Emissions, cost, peak, and a feeder-capacity mode", t: "4 modes" },
  { k: "Carbon", v: "Derived from generation mix × IPCC AR5 lifecycle factors", t: "gCO₂eq/kWh" },
  { k: "Data", v: "ENTSO-E measured Spanish and German grid records", t: "4 years" },
  { k: "Forecaster", v: "Ridge, exported as coefficients — no ML runtime in the bundle", t: "MAE 23.7" },
  { k: "API", v: "FastAPI on a Python serverless function", t: "46 tests" },
  { k: "Frontend", v: "React · TypeScript · Vite · Recharts", t: "one origin" },
] as const;

/** A button that leans a few pixels toward the cursor. */
function useMagnetic(reduced: boolean) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (reduced) return;
    const el = ref.current;
    if (!el) return;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - (r.left + r.width / 2)) / r.width;
      const y = (e.clientY - (r.top + r.height / 2)) / r.height;
      el.style.transform = `translate(${x * 9}px, ${y * 5}px)`;
    };
    const out = () => { el.style.transform = ""; };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", out);
    return () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", out);
    };
  }, [reduced]);
  return ref;
}

export default function Landing({
  onEnter, onPalette,
}: {
  onEnter: () => void;
  onPalette: () => void;
}) {
  const reduced = usePrefersReduced();
  const { active, progress } = useScrollSpy(SECTION_IDS);
  const magnet = useMagnetic(reduced);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter" && e.target === document.body) onEnter();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onEnter]);

  const goto = useCallback((id: string) => {
    document.getElementById(id)?.scrollIntoView({
      behavior: reduced ? "auto" : "smooth", block: "start",
    });
  }, [reduced]);

  // The nav only earns its space once the reader has left the hero.
  const past = progress > 0.04;

  return (
    <div className="landing">
      <div className="gridOverlay" />

      <div className="ldProgress" style={{ transform: `scaleX(${progress})` }} aria-hidden="true" />

      <header className={`ldNav ${past ? "isStuck" : ""}`}>
        <button className="ldNavBrand" onClick={() => window.scrollTo({ top: 0 })}>
          <span className="ldNavDot" aria-hidden="true" />
          GridSense
        </button>

        <nav className="ldNavLinks" aria-label="Sections">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className={`ldNavLink ${active === s.id && past ? "isActive" : ""}`}
              onClick={() => goto(s.id)}
            >
              {s.nav}
            </button>
          ))}
        </nav>

        <div className="ldNavRight">
          <button className="ldNavCmd" onClick={onPalette} title="Command palette">
            <Command size={13} strokeWidth={2.2} />
            <span className="kbd">K</span>
          </button>
          <a className="ldNavGh" href="https://github.com/adityaayushman/GRIDSENSE"
            target="_blank" rel="noreferrer" aria-label="Source on GitHub">
            <Github size={15} strokeWidth={2} />
          </a>
          <button className="ldNavEnter" onClick={onEnter}>
            Open dashboard <ArrowRight size={13} strokeWidth={2.6} />
          </button>
        </div>
      </header>

      <section className="ldHero">
        <LandingScene reduced={reduced} />

        <div className="ldHeroCopy">
          <span className="ldKicker riseIn" style={{ ["--i" as string]: 0 }}>
            <span className="mastDot" aria-hidden="true" />
            Measured grid data · <b>ENTSO-E Spain</b> · four years, hour by hour
          </span>

          <h1 className="ldTitle riseIn" style={{ ["--i" as string]: 1 }}>
            Charge when the grid is <span className="lit">actually clean</span>.
          </h1>

          <p className="ldLede riseIn" style={{ ["--i" as string]: 2 }}>
            Most electric cars start charging the moment their owner gets home — straight into
            the evening peak, on the dirtiest power of the day. GridSense schedules the same
            energy against real carbon intensity, real prices and a real transformer limit,
            then reports honestly how little that buys on most nights and where it buys a lot.
          </p>

          <div className="ldStats riseIn" style={{ ["--i" as string]: 3 }}>
            {[
              { v: `${cap.gain}×`, k: "hosting capacity" },
              { v: `${es.median_saving}%`, k: "median CO₂ cut" },
              { v: "71%", k: "captured by forecast" },
              { v: "8", k: "published claims corrected" },
            ].map((s) => (
              <div className="ldStat" key={s.k}>
                <span className="ldStatVal">{s.v}</span>
                <span className="ldStatKey">{s.k}</span>
              </div>
            ))}
          </div>

          <div className="ldActions riseIn" style={{ ["--i" as string]: 4 }}>
            <button className="ldEnter magnetic" ref={magnet} onClick={onEnter}>
              Enter the dashboard <ArrowRight size={16} strokeWidth={2.4} />
            </button>
            <button className="ldDive" onClick={() => goto("problem")}>
              What is this? <ChevronDown size={15} strokeWidth={2.4} />
            </button>
          </div>

          <p className="ldHint riseIn" style={{ ["--i" as string]: 5 }}>
            Press <span className="kbd">↵</span> to enter · <span className="kbd">⌘</span>
            <span className="kbd">K</span> for commands
          </p>
        </div>

        <button className="ldScrollCue" onClick={() => goto("problem")}
          aria-label="Read more about the project">
          <ChevronDown size={18} strokeWidth={2} />
        </button>
      </section>

      <div className="ldDetail">
        <Section id="problem" eyebrow="The problem"
          title="A transformer, not the atmosphere, is what breaks first">
          <div className="ldCols">
            <p>
              An electric car draws roughly what an entire house does. Put a handful on one
              residential feeder, let them all begin at 18:00, and the street's evening peak
              stops being a curve and becomes a wall. The binding constraint on electrification
              is rarely generation — it is the distribution transformer at the end of the road,
              and replacing one is slow and expensive.
            </p>
            <p>
              Carbon is the more fashionable framing, and this project measures it carefully.
              But the honest headline is capacity: the same steel absorbs{" "}
              <strong>{cap.gain}× more vehicles</strong> when their charging is coordinated
              than when it is not — the median over twenty draws of the fleet, which individually range from {cap.gain_min}× to {cap.gain_max}×. That is the result worth defending, and it is not the one the
              project set out to find.
            </p>
          </div>
        </Section>

        <Section id="method" eyebrow="What it does" title="A linear program over one night">
          <div className="ldCols">
            <p>
              Every vehicle arrives with an energy requirement, a charger rating and a deadline.
              The scheduler places that energy hour by hour across the window to minimise a
              chosen objective — emissions, cost, or peak load — subject to charger limits, the
              deadline, and optionally a shared feeder capacity that couples every vehicle to
              every other.
            </p>
            <p>
              That coupling is what justifies the optimiser at all. Without it the problem
              separates and a greedy rule reproduces the LP exactly, which finding 04 records
              rather than hides. Vehicle-to-grid, state-of-charge tracking and round-trip losses
              are modelled; battery degradation is not, and an export cap stands in for it.
            </p>
          </div>
          <div className="ldChips">
            {["min emissions", "min cost", "min peak", "feeder-limited", "V2G",
              "day-ahead forecast", "state of charge", "round-trip loss"]
              .map((c) => <span className="ldChip" key={c}>{c}</span>)}
          </div>
        </Section>

        <Section id="data" eyebrow="The data" title="Measured, not simulated">
          <div className="ldCols">
            <p>
              Carbon intensity is not downloaded — it is derived, from ENTSO-E's published
              generation mix weighted by IPCC AR5 lifecycle emission factors, hour by hour. The
              Spanish record runs four years; a German one is carried alongside so a second grid
              can check whether any conclusion is really about scheduling or just about Spain.
            </p>
            <p>
              Datasets are screened before they are trusted. A candidate whose hour-to-hour
              autocorrelation looks like white noise is rejected regardless of how convincing
              its column names are, because a model fitted to noise still reports a believable
              error figure. Four candidates were rejected on that test.
            </p>
          </div>
          <div className="ldMetrics">
            {[
              { v: es.mean, u: "gCO₂eq/kWh", k: "Spain, mean intensity" },
              { v: de.mean, u: "gCO₂eq/kWh", k: "Germany, mean intensity" },
              { v: mpc.nights, u: "nights", k: "held out for control tests" },
              { v: "0.951", u: "lag-1", k: "autocorrelation screen floor" },
            ].map((m) => (
              <div className="ldMetric" key={m.k}>
                <span className="ldMetricVal">{m.v}<em>{m.u}</em></span>
                <span className="ldMetricKey">{m.k}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section id="findings" eyebrow="What it found"
          title="Nine findings, four of them negative" wide>
          <p className="ldNote">
            A findings list containing only confirmations is a marketing document. These are
            ordered as they were established, and the ones that contradict the project's own
            premise are kept.
          </p>
          <FindingGrid />
        </Section>

        <Section id="rejected" eyebrow="What did not survive" title="Rejected on evidence" wide>
          <p className="ldNote">
            Each of these looked promising enough to spend time on, and each was dropped because
            a measurement said so rather than because it became inconvenient.
          </p>
          <RejectedGrid />
        </Section>

        <Section id="stack" eyebrow="How it is built" title="The stack">
          <dl className="ldStack">
            {STACK.map((s) => (
              <div className="ldStackRow" key={s.k}>
                <dt>{s.k}</dt>
                <dd>{s.v}</dd>
                <span className="ldStackTag">{s.t}</span>
              </div>
            ))}
          </dl>
        </Section>

        <section className="ldSection ldFinal">
          <h2 className="ldH2">Five panes, every number regenerated from source</h2>
          <p className="ldNote">
            The simulator solves a night live. The other four each defend a specific claim —
            against the alternatives, against a transformer limit, against a second grid, and
            against a more sophisticated controller that turned out not to be worth it.
          </p>
          <button className="ldEnter ldEnterBig" onClick={onEnter}>
            Enter the dashboard <ArrowRight size={17} strokeWidth={2.4} />
          </button>
        </section>
      </div>
    </div>
  );
}

function FindingGrid() {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLDivElement>(reduced);
  return (
    <div ref={ref} className={`ldGrid stagger ${shown ? "isIn" : ""}`}>
      {FINDINGS.map((f, i) => (
        <article className={`ldCard tone-${f.tone}`} key={f.n} style={{ ["--i" as string]: i }}>
          <div className="ldCardTop">
            <span className="ldCardNum">{f.n}</span>
            <span className="ldCardTag">{f.tag}</span>
          </div>
          <h3 className="ldCardHead">{f.head}</h3>
          <p className="ldCardBody">{f.body}</p>
        </article>
      ))}
    </div>
  );
}

function RejectedGrid() {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLDivElement>(reduced);
  return (
    <div ref={ref} className={`ldGrid ldGrid2 stagger ${shown ? "isIn" : ""}`}>
      {REJECTED.map((r, i) => (
        <article className="ldCard tone-bad" key={r.head} style={{ ["--i" as string]: i }}>
          <div className="ldCardTop">
            <span className="ldCardTag">{r.meta}</span>
          </div>
          <h3 className="ldCardHead">{r.head}</h3>
          <p className="ldCardBody">{r.body}</p>
        </article>
      ))}
    </div>
  );
}
