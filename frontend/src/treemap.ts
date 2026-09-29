/* Squarified treemap layout (Bruls, Huizing & van Wijk, 2000).
 *
 * Written out rather than pulled from a charting library for two reasons: the
 * tiling must nest inside sector groups so a sector can carry a header, and the
 * area has to be strictly proportional to the size metric so a market-cap map
 * is not lying about relative weight.
 *
 * The algorithm lays tiles along the shorter side of the remaining rectangle,
 * always adding the *next* item to a row while that improves the aspect ratio.
 * It is O(n log n) and, for 250 tiles, comfortably fast enough to recompute on
 * every resize.
 */

export interface TreemapInput {
  id: string;
  /** Non-negative; zero and negative values are dropped by the caller. */
  value: number;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LaidOutTile<T> extends Rect {
  item: T;
}

function worstRatio(row: number[], length: number): number {
  if (row.length === 0 || length <= 0) return Infinity;
  const sum = row.reduce((a, b) => a + b, 0);
  if (sum <= 0) return Infinity;
  const max = Math.max(...row);
  const min = Math.min(...row);
  const s2 = sum * sum;
  const l2 = length * length;
  return Math.max((l2 * max) / s2, s2 / (l2 * min));
}

function layoutRow<T>(
  row: T[],
  valueOf: (t: T) => number,
  rect: Rect,
  horizontal: boolean,
  out: LaidOutTile<T>[],
  scale: number,
): void {
  const total = row.reduce((a, t) => a + valueOf(t), 0);
  if (total <= 0) return;
  const thickness = (total * scale) / (horizontal ? rect.height : rect.width);
  let offset = 0;
  for (const item of row) {
    const v = valueOf(item);
    const extent = (v * scale) / thickness;
    out.push(
      horizontal
        ? {
            item,
            x: rect.x + offset,
            y: rect.y,
            width: thickness,
            height: extent,
          }
        : {
            item,
            x: rect.x,
            y: rect.y + offset,
            width: extent,
            height: thickness,
          },
    );
    offset += extent;
  }
}

/**
 * Lay out `items` inside `rect`, largest first.
 *
 * Items are sorted internally, so the caller need not pre-sort; the returned
 * order follows that sort, which also means the biggest tile is drawn first
 * and ends up top-left where the eye starts.
 */
export function squarify<T extends { value: number }>(
  items: T[],
  rect: Rect,
  valueOf: (t: T) => number,
): LaidOutTile<T>[] {
  const positive = items.filter((t) => valueOf(t) > 0);
  if (positive.length === 0 || rect.width <= 0 || rect.height <= 0) return [];

  positive.sort((a, b) => valueOf(b) - valueOf(a));

  const total = positive.reduce((a, t) => a + valueOf(t), 0);
  if (total <= 0) return [];
  // Scale converts value -> area in px^2, so a tile's area is exactly
  // proportional to its value.
  const scale = (rect.width * rect.height) / total;

  const out: LaidOutTile<T>[] = [];
  let remaining: Rect = { ...rect };
  let row: T[] = [];
  let rowValues: number[] = [];
  let index = 0;

  while (index < positive.length) {
    const horizontal = remaining.width >= remaining.height;
    const length = horizontal ? remaining.width : remaining.height;
    const nextValue = valueOf(positive[index]);
    const currentWorst =
      rowValues.length === 0 ? Infinity : worstRatio(rowValues, length);
    const withNext = worstRatio([...rowValues, nextValue], length);

    if (rowValues.length === 0 || withNext <= currentWorst) {
      row.push(positive[index]);
      rowValues.push(nextValue);
      index += 1;
      continue;
    }

    // The row is finished: commit it and shrink the remaining rectangle.
    const rowTotal = rowValues.reduce((a, b) => a + b, 0);
    const thickness = (rowTotal * scale) / length;
    layoutRow(row, valueOf, remaining, horizontal, out, scale);
    remaining = horizontal
      ? { ...remaining, x: remaining.x + thickness, width: remaining.width - thickness }
      : { ...remaining, y: remaining.y + thickness, height: remaining.height - thickness };
    row = [];
    rowValues = [];

    if (remaining.width <= 0.01 || remaining.height <= 0.01) break;
  }

  if (rowValues.length > 0) {
    layoutRow(row, valueOf, remaining, remaining.width >= remaining.height, out, scale);
  }
  return out;
}

/**
 * Split tiles into sector groups, then lay each group out inside its share of
 * the parent rect. Groups are placed largest-first so the big sectors cluster
 * at the top-left and small ones trail off, which reads better than alphabetical
 * order.
 */
export function groupBy<T extends { value: number; sector: string | null }>(
  items: T[],
  rect: Rect,
  valueOf: (t: T) => number,
  padding = 3,
): { sector: string; rect: Rect; tiles: LaidOutTile<T>[]; value: number }[] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    if (valueOf(item) <= 0) continue;
    const key = item.sector ?? "Unclassified";
    const list = groups.get(key);
    if (list) list.push(item);
    else groups.set(key, [item]);
  }

  const sectorTiles = [...groups.entries()].map(([sector, list]) => ({
    sector,
    tiles: list,
    value: list.reduce((a, t) => a + valueOf(t), 0),
  }));
  sectorTiles.sort((a, b) => b.value - a.value);

  const frames = squarify(
    sectorTiles,
    rect,
    (s) => s.value,
  );

  return frames.map((frame) => {
    const inset = padding;
    const inner: Rect = {
      x: frame.x + inset,
      y: frame.y + inset,
      width: Math.max(0, frame.width - inset * 2),
      height: Math.max(0, frame.height - inset * 2),
    };
    return {
      sector: frame.item.sector,
      rect: frame,
      value: frame.item.value,
      tiles: squarify(frame.item.tiles, inner, valueOf),
    };
  });
}

/**
 * Diverging colour for a period return, clamped to +/- `maxPct` so the legend
 * range keeps its meaning in every period. Clamping the *colour* never hides
 * the number: the tile always prints the true percentage.
 */
export function changeColor(pct: number, maxPct = 6): string {
  const t = Math.max(-1, Math.min(1, pct / maxPct));
  if (t > 0.25) return "var(--up)";
  if (t < -0.25) return "var(--down)";
  if (t >= 0) return "var(--up-soft)";
  return "var(--down-soft)";
}

/** True when a tile is too small to fit two lines of text. */
export function isTooSmall(tile: Rect, threshold = 46): boolean {
  return tile.width < threshold || tile.height < threshold * 0.62;
}
