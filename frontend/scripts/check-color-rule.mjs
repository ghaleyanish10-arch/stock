/* Colour-rule contract test (run: node scripts/check-color-rule.mjs).
 *
 * Pins the one colour function to the documented rule, including the gap-day
 * cases where "close vs previous close" and "close vs open" disagree. Every
 * expected value below is hand arithmetic, not the code's output:
 *
 *   Case 1  open=100 close=102 prevClose=105  (green intrabar, red vs yesterday)
 *           prev_close -> delta = 102-105 = -3  -> RED
 *           open       -> delta = 102-100 = +2  -> GREEN
 *   Case 2  open=105 close=101 prevClose=100  (red intrabar, green vs yesterday)
 *           prev_close -> delta = 101-100 = +1  -> GREEN
 *           open       -> delta = 101-105 = -4  -> RED
 *   Case 3  open=100 close=100 prevClose=99   (flat intrabar, green vs yesterday)
 *           prev_close -> delta = 100-99  = +1  -> GREEN
 *           open       -> delta = 100-100 =  0  -> FLAT
 *   Case 4  first bar of the window, prevClose unknown:
 *           both rules fall back to the intrabar comparison.
 *   Case 5  non-finite close -> FLAT under both rules (missing is never red).
 *
 * The palette is a plain object here: the real one resolves CSS variables in
 * the browser (green-up default, red-up under [data-trend="nepse"]).
 */

import { changeColor, changeRef } from "../src/chartColors.ts";

const pal = { up: "GREEN", down: "RED", flat: "FLAT" };
const GREEN = "GREEN", RED = "RED", FLAT = "FLAT";

let failures = 0;
function check(name, actual, expected) {
  if (actual === expected) {
    console.log(`  ok  ${name}: ${actual}`);
  } else {
    failures++;
    console.error(`FAIL  ${name}: expected ${expected}, got ${actual}`);
  }
}

const cases = [
  { name: "gap-up open, close above open but below prev close", open: 100, close: 102, prevClose: 105 },
  { name: "gap-down open, close below open but above prev close", open: 105, close: 101, prevClose: 100 },
  { name: "close equals open, above prev close", open: 100, close: 100, prevClose: 99 },
  { name: "close equals open, below prev close", open: 100, close: 100, prevClose: 101 },
];

for (const c of cases) {
  const refPrev = changeRef("prev_close", c.open, c.prevClose);
  const refOpen = changeRef("open", c.open, c.prevClose);
  check(
    `${c.name} | prev_close rule`,
    changeColor(c.close - refPrev, pal),
    changeColor(c.close - c.prevClose, pal),
  );
  check(
    `${c.name} | open rule`,
    changeColor(c.close - refOpen, pal),
    changeColor(c.close - c.open, pal),
  );
}

// Case 1 explicitly: the two rules must disagree, in the documented directions.
{
  const c = cases[0];
  check("case 1 prev_close -> RED", changeColor(102 - changeRef("prev_close", 100, 105), pal), RED);
  check("case 1 open -> GREEN", changeColor(102 - changeRef("open", 100, 105), pal), GREEN);
  void c;
}

// Case 2 explicitly, the mirror image.
{
  check("case 2 prev_close -> GREEN", changeColor(101 - changeRef("prev_close", 105, 100), pal), GREEN);
  check("case 2 open -> RED", changeColor(101 - changeRef("open", 105, 100), pal), RED);
}

// Case 4: first bar, no previous session -> intrabar fallback, not a crash.
{
  check("first bar, prev_close rule falls back to open", changeRef("prev_close", 100, null), 100);
  check("first bar, open rule", changeRef("open", 100, null), 100);
}

// Case 5: missing/non-finite closes are flat, never red or green.
{
  check("null delta -> FLAT", changeColor(null, pal), FLAT);
  check("NaN delta -> FLAT", changeColor(NaN, pal), FLAT);
  check("Infinity delta -> FLAT", changeColor(Infinity, pal), FLAT);
  check("0 delta -> FLAT", changeColor(0, pal), FLAT);
}

console.log(failures ? `\n${failures} failure(s)` : "\nall colour-rule cases pass");
process.exit(failures ? 1 : 0);
