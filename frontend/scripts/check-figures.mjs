// Fails the build if a figure the project has since corrected is typed into the UI again.
//
// Every headline number on the site is meant to come from a generated data file, so that no two
// surfaces can disagree. The values below were each published once and later corrected
// (FINDINGS.md, LESSONS.md); seeing one back in the source means a number was typed in by hand.
// A line that needs one on purpose (history, a quotation) can say so with `figures-ok`.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const STALE = [
  [/\b3\.3%/, "3.3% (Spain median saving, now from the corrected record)"],
  [/\b10\.4%/, "10.4% (Spain fleet total, now from the corrected record)"],
  [/\b71(\.0)?%/, "71% (forecaster capture, now from results.json)"],
  [/\b1,444\b/, "1,444 (nights backtested, now from results.json)"],
  [/\b14\.4%/, "14.4% (cost/carbon coincidence on the old record)"],
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) { if (name !== "data") yield* walk(p); }
    else if (/\.(tsx?|css)$/.test(name)) yield p;
  }
}

let bad = 0;
for (const file of walk("src")) {
  readFileSync(file, "utf8").split("\n").forEach((line, i) => {
    if (line.includes("figures-ok")) return;
    for (const [re, why] of STALE) {
      if (re.test(line)) { console.error(`${file}:${i + 1}  stale figure ${why}\n    ${line.trim()}`); bad++; }
    }
  });
}
if (bad) { console.error(`\n${bad} stale figure(s). Read them from src/data/*.json instead.`); process.exit(1); }
console.log("figures ok: no corrected number is typed into the source");
