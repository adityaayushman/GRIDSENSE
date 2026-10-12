# What I got wrong, and how I found out

GridSense went through seven material corrections while it was being built. Each
change is recorded in [FINDINGS.md](FINDINGS.md) with the before and after. This
page is the short version: what each mistake was, what caught it, and what I do
differently now.

## The mistakes

| # | What I claimed | What was wrong | What caught it | What it became |
| --- | --- | --- | --- | --- |
| 1 | A synthetic carbon curve was good enough to schedule against | Its shape was roughly the *opposite* of the measured grid | Scoring it against real ENTSO-E data | Scheduling on it was worse than not scheduling (−26.8%). Replaced with measured data and a forecaster (finding 3) |
| 2 | Coordination hosts **14×** more EVs | Every car arrived at exactly 18:00, which maximally punishes the baseline it was compared to | Staggering arrivals tripled what charging-on-arrival could host | 6.3× (finding 1) |
| 3 | …so it is **6.3×** | The residential baseline overstated household demand about **sevenfold** (1,915 vs about 290 kWh a month) | Calibrating the Indian equivalent and noticing the Spanish one didn't match | **5.3×**. My own follow-up guess of "nearer 4×" was also wrong: I extrapolated from a simplified fleet (finding 11) |
| 4 | Germany saves less because its overnight hours "sit flat on lignite" | It was an explanation I had not tested | Measuring the within-night spread directly: Germany's was *wider* | The real reason is that charging on arrival already lands on the cleanest hour (finding 7) |
| 5 | Rolling-horizon control is **238%** worse than a one-shot plan | The baseline was accidentally reading true intensities for far-ahead hours, handing it perfect foresight | Checking what each controller was allowed to see | 28% worse. The sign survived; almost all of the magnitude did not (finding 9) |
| 6 | India carbon-aware charging saves **0.05%**, on a grid at 541 g/kWh | The parser read the wrong column for **84% of days** after Grid-India changed its spreadsheet layout twice. Coal was being weighted as gas | An hour-of-day profile showing "solar" at 15 GW at midnight | 0.12% overnight, 592 g/kWh, and a daytime window worth 1.51%. Direction held, numbers did not (finding 14) |
| 7 | **5.3×**, to one decimal place | It was one random draw of the fleet, and the best of twenty | Re-running with 20 seeds | Median about 4×, range 3.4–5.3× (finding 1) |

## What the mistakes have in common

**Inputs that looked right were never checked against physics.** Mistakes 1, 3
and 6 are the same error three times: a derived series (a carbon curve, a
household load, a fuel mix) was accepted because it was smooth, complete and
numeric. None of them failed loudly. Each one was caught by asking whether the
number could exist, not whether it parsed.

**One run was reported as the answer.** Mistake 7 is mistake 2 in another form:
the figure depended on a choice (a synchronised fleet, a random seed) that I
had not varied.

**I explained before I measured.** Mistakes 4 and 3's "nearer 4×" were plausible
stories stated as findings. Both were wrong, and both are still in FINDINGS.md
next to their corrections, because the corrections are more useful than
a clean record.

## What I do now

- **Every number is reproducible from a named script**, and the UI reads its
  figures from generated files instead of having them typed in.
- **Sanity checks before trusting a series:** each fuel's daily shape (solar must
  vanish at night) and closure (the fuels must sum to the source's own total),
  on top of the autocorrelation screen.
- **A noise band before a headline.** Vary the thing that could be chosen
  otherwise, report the range, and don't quote the favourable end.
- **Say what a sweep is not.** The sensitivity table is labelled "sensitivity to
  assumptions, not validation": it cannot catch an error that is wrong in kind.
- **Cross-check against an independent source** when one exists. The repaired
  Indian series agrees with two unrelated sources to within 1% on level.
- **Keep the negative results.** Rolling control losing to the one-shot plan, V2G
  not paying for carbon, and the gate doing little in India are all shipped.

## What is still not validated

The hosting-capacity figure rests on an assumed baseline shape, an assumed fleet
and an assumed number of homes per transformer. The sweep shows how far each
moves it; it does not show that the true value is inside that range. Closing that
needs real charging sessions and a metered feeder, neither of which I have yet.
