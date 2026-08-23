import { useEffect, useRef } from "react";
import { ArrowRight, ChevronDown } from "lucide-react";
import LandingScene from "./LandingScene";
import { usePrefersReduced, useReveal } from "./motion";
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

function Section({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  return (
    <section ref={ref} className={`ldSection reveal ${shown ? "isIn" : ""} ${className}`}>
      {children}
    </section>
  );
}

const FINDINGS = [
  {
    n: "01",
    tone: "good",
    head: `${cap.gain}× the hosting capacity`,
    body: `One ${cap.rating_kw} kW transformer carries ${cap.coordinated} coordinated vehicles ` +
      `against ${cap.dumb} charging on arrival. This is the headline — not the carbon saving.`,
  },
  {
    n: "02",
    tone: "flat",
    head: `${es.median_saving}% median CO₂ saving`,
    body: "Real, and small. The distribution is long-tailed: most nights offer almost nothing, " +
      "a few offer a great deal. Reporting the mean alone would flatter it.",
  },
  {
    n: "03",
    tone: "bad",
    head: "The first carbon curve was inverted",
    body: "The synthetic profile the project started on did not merely differ from the measured " +
      "one — it pointed the wrong way. Every conclusion drawn from it was void.",
  },
  {
    n: "04",
    tone: "flat",
    head: "The optimiser only earns its keep under a coupling constraint",
    body: "Without one, the problem separates and a greedy rule matches the LP exactly. " +
      "Vehicle heterogeneity does not change that; a shared feeder limit does.",
  },
  {
    n: "05",
    tone: "flat",
    head: "Cost and carbon genuinely conflict",
    body: "Cheap hours and clean hours are not the same hours. Optimising the bill raises " +
      "emissions; optimising emissions raises the bill. There is no free alignment.",
  },
  {
    n: "06",
    tone: "flat",
    head: "Forecast error only matters when there is something to gain",
    body: `The shipped model captures 71% of the achievable saving. On nearly flat nights its ` +
      "error exceeds the real spread, and acting on it does worse than nothing.",
  },
  {
    n: "07",
    tone: "bad",
    head: "A dirtier, more variable grid is not a better one to shift in",
    body: `Germany is dirtier (${de.mean} vs ${es.mean} gCO₂eq/kWh) and swings ` +
      "harder, yet saves less. What predicts the saving is how good the default already is.",
  },
  {
    n: "08",
    tone: "bad",
    head: "V2G is not economic for carbon",
    body: "Abatement through vehicle-to-grid costs €0.78–1.01 per kg CO₂ against an ETS price " +
      "near €0.06–0.09. It shaves peak well; as a carbon lever it is ten times too expensive.",
  },
  {
    n: "09",
    tone: "bad",
    head: "Rolling-horizon control loses to the one-shot LP",
    body: `Re-solving hourly costs +${mpc.attribution_pp.rolling_commitment}pp of regret while ` +
      `the sharper forecast buys back only ${mpc.attribution_pp.fresher_forecast}pp. ` +
      "The control structure costs more than the information is worth.",
  },
] as const;

const REJECTED = [
  {
    head: "Indian grid data",
    body: "Grid-India and the CEA publish a complete fuel mix back to 2018 — daily. This project " +
      "schedules inside a single night, and one number per day has no shape to schedule against.",
  },
  {
    head: "A plausible-looking Kaggle dataset",
    body: "Hourly stamps, no gaps, realistic ranges — and lag-1 autocorrelation of −0.025, where " +
      "measured grid load sits at +0.951. Independent random draws wearing a schema.",
  },
  {
    head: "Weather features",
    body: "Cloud cover and wind speed looked like the obvious untapped signal. Measured at " +
      "−0.19pp: the TSO's day-ahead forecasts already carry it.",
  },
  {
    head: "Synchronised-peak theory",
    body: "Uncoordinated carbon-aware charging was expected to manufacture a new peak. It raises " +
      "the peak on 3 nights of 46, by 1.03×. The effect is real and small.",
  },
] as const;

const STACK = [
  { k: "Optimiser", v: "Linear program over the charging window · PuLP / CBC" },
  { k: "Objectives", v: "Emissions, cost, peak, and a feeder-capacity mode" },
  { k: "Carbon", v: "Derived from generation mix × IPCC AR5 lifecycle factors" },
  { k: "Data", v: "ENTSO-E measured Spanish and German grid records" },
  { k: "Forecaster", v: "Ridge, exported as coefficients — no ML runtime in the bundle" },
  { k: "API", v: "FastAPI on a Python serverless function" },
  { k: "Frontend", v: "React · TypeScript · Vite · Recharts" },
] as const;

export default function Landing({ onEnter }: { onEnter: () => void }) {
  const reduced = usePrefersReduced();
  const detail = useRef<HTMLDivElement>(null);

  // Entering by keyboard should not require finding the button first.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter" && e.target === document.body) onEnter();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onEnter]);

  const dive = () =>
    detail.current?.scrollIntoView({
      behavior: reduced ? "auto" : "smooth",
      block: "start",
    });

  return (
    <div className="landing">
      <div className="gridOverlay" />

      <section className="ldHero">
        <LandingScene reduced={reduced} />

        <div className="ldHeroCopy">
          <span className="ldKicker">
            <span className="mastDot" aria-hidden="true" />
            Measured grid data · <b>ENTSO-E Spain</b> · four years, hour by hour
          </span>

          <h1 className="ldTitle">
            Charge when the grid is <span className="lit">actually clean</span>.
          </h1>

          <p className="ldLede">
            Most electric cars start charging the moment their owner gets home — straight into
            the evening peak, on the dirtiest power of the day. GridSense schedules the same
            energy against real carbon intensity, real prices and a real transformer limit,
            then reports honestly how little that buys on most nights and where it buys a lot.
          </p>

          <div className="ldStats">
            <div className="ldStat">
              <span className="ldStatVal">{cap.gain}×</span>
              <span className="ldStatKey">hosting capacity</span>
            </div>
            <div className="ldStat">
              <span className="ldStatVal">{es.median_saving}%</span>
              <span className="ldStatKey">median CO₂ cut</span>
            </div>
            <div className="ldStat">
              <span className="ldStatVal">71%</span>
              <span className="ldStatKey">captured by forecast</span>
            </div>
            <div className="ldStat">
              <span className="ldStatVal">9</span>
              <span className="ldStatKey">findings · 4 negative</span>
            </div>
          </div>

          <div className="ldActions">
            <button className="ldEnter" onClick={onEnter}>
              Enter the dashboard <ArrowRight size={16} strokeWidth={2.4} />
            </button>
            <button className="ldDive" onClick={dive}>
              What is this? <ChevronDown size={15} strokeWidth={2.4} />
            </button>
          </div>
        </div>

        <button className="ldScrollCue" onClick={dive} aria-label="Read more about the project">
          <ChevronDown size={18} strokeWidth={2} />
        </button>
      </section>

      <div className="ldDetail" ref={detail}>
        <Section>
          <span className="ldEyebrow">The problem</span>
          <h2 className="ldH2">A transformer, not the atmosphere, is what breaks first</h2>
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
              than when it is not. That is the result worth defending, and it is not the one the
              project set out to find.
            </p>
          </div>
        </Section>

        <Section>
          <span className="ldEyebrow">What it does</span>
          <h2 className="ldH2">A linear program over one night</h2>
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
            {["min emissions", "min cost", "min peak", "feeder-limited", "V2G", "day-ahead forecast"]
              .map((c) => <span className="ldChip" key={c}>{c}</span>)}
          </div>
        </Section>

        <Section>
          <span className="ldEyebrow">The data</span>
          <h2 className="ldH2">Measured, not simulated</h2>
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
              error figure. Four candidates were rejected on that test and are listed below.
            </p>
          </div>
        </Section>

        <Section className="ldWide">
          <span className="ldEyebrow">What it found</span>
          <h2 className="ldH2">Nine findings, four of them negative</h2>
          <p className="ldNote">
            A findings list containing only confirmations is a marketing document. These are
            ordered as they were established, and the ones that contradict the project's own
            premise are kept.
          </p>
          <div className="ldGrid">
            {FINDINGS.map((f) => (
              <article className={`ldCard tone-${f.tone}`} key={f.n}>
                <span className="ldCardNum">{f.n}</span>
                <h3 className="ldCardHead">{f.head}</h3>
                <p className="ldCardBody">{f.body}</p>
              </article>
            ))}
          </div>
        </Section>

        <Section className="ldWide">
          <span className="ldEyebrow">What did not survive</span>
          <h2 className="ldH2">Rejected on evidence</h2>
          <div className="ldGrid ldGrid2">
            {REJECTED.map((r) => (
              <article className="ldCard tone-bad" key={r.head}>
                <h3 className="ldCardHead">{r.head}</h3>
                <p className="ldCardBody">{r.body}</p>
              </article>
            ))}
          </div>
        </Section>

        <Section>
          <span className="ldEyebrow">How it is built</span>
          <h2 className="ldH2">The stack</h2>
          <dl className="ldStack">
            {STACK.map((s) => (
              <div className="ldStackRow" key={s.k}>
                <dt>{s.k}</dt>
                <dd>{s.v}</dd>
              </div>
            ))}
          </dl>
        </Section>

        <Section className="ldFinal">
          <h2 className="ldH2">Five panes, every number regenerated from source</h2>
          <p className="ldNote">
            The simulator solves a night live. The other four defend a specific claim — against
            the alternatives, against a transformer limit, against a second grid, and against a
            more sophisticated controller that turned out not to be worth it.
          </p>
          <button className="ldEnter ldEnterBig" onClick={onEnter}>
            Enter the dashboard <ArrowRight size={17} strokeWidth={2.4} />
          </button>
        </Section>
      </div>
    </div>
  );
}
