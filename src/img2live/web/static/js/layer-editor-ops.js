// SPDX-License-Identifier: Apache-2.0
// Pure typed-array algorithms behind the layer editor (no DOM, no canvas).  Everything works on flat w*h planes:
//   - an "alpha plane" is a Uint8Array (mask alpha, layer alpha ...), selected = value > SEL_T
//   - an "rgba" buffer is the Uint8ClampedArray of ImageData
// Flood fill (BFS, typed arrays) on 1280x1280 takes tens of milliseconds, so none of this needs a worker.

export const GRID = 1280;
export const SEL_T = 127;     // mask alpha above this counts as selected (the server uses the same rule)
export const CONTENT_T = 16;  // layer / source alpha above this counts as "has content"

/** Alpha channel of an RGBA buffer as a tight plane. */
export function alphaPlane(rgba, out) {
  const n = rgba.length >> 2;
  const a = out && out.length === n ? out : new Uint8Array(n);
  for (let i = 0, j = 3; i < n; i++, j += 4) a[i] = rgba[j];
  return a;
}

/** 0/255 plane: 255 where the plane is above `thr`. */
export function thresholdPlane(a, thr, out) {
  const n = a.length;
  const o = out && out.length === n ? out : new Uint8Array(n);
  for (let i = 0; i < n; i++) o[i] = a[i] > thr ? 255 : 0;
  return o;
}

export function equalPlanes(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0, n = a.length; i < n; i++) if (a[i] !== b[i]) return false;
  return true;
}

/**
 * Count and boxes of a mask plane.
 *   bbox : box of pixels above SEL_T (the selection proper), inclusive {x0,y0,x1,y1}, or null when empty
 *   any  : box of every non-zero pixel (soft edges included, for exact snapshots), or null
 */
export function maskStats(a, w, h) {
  let count = 0, x0 = w, y0 = h, x1 = -1, y1 = -1, ax0 = w, ay0 = h, ax1 = -1, ay1 = -1;
  for (let y = 0; y < h; y++) {
    const row = y * w;
    let lo = -1, hi = -1, alo = -1, ahi = -1;
    for (let x = 0; x < w; x++) {
      const v = a[row + x];
      if (v === 0) continue;
      if (alo < 0) alo = x;
      ahi = x;
      if (v > SEL_T) { if (lo < 0) lo = x; hi = x; count++; }
    }
    if (alo >= 0) { if (alo < ax0) ax0 = alo; if (ahi > ax1) ax1 = ahi; if (y < ay0) ay0 = y; ay1 = y; }
    if (lo >= 0) { if (lo < x0) x0 = lo; if (hi > x1) x1 = hi; if (y < y0) y0 = y; y1 = y; }
  }
  return {
    count,
    bbox: count ? { x0, y0, x1, y1 } : null,
    any: ax1 >= 0 ? { x0: ax0, y0: ay0, x1: ax1, y1: ay1 } : null,
  };
}

/** Box of the pixels above `thr` in an alpha plane (inclusive), or null. */
export function planeBBox(a, w, h, thr = CONTENT_T) {
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) {
    const row = y * w;
    let lo = -1, hi = -1;
    for (let x = 0; x < w; x++) if (a[row + x] > thr) { if (lo < 0) lo = x; hi = x; }
    if (lo >= 0) { if (lo < x0) x0 = lo; if (hi > x1) x1 = hi; if (y < y0) y0 = y; y1 = y; }
  }
  return x1 < 0 ? null : { x0, y0, x1, y1 };
}

// ------------------------------------------------------------------------------------------ magic wand
function sampleWindow(px, w, h, x, y, win) {
  if (win <= 1) { const i = (y * w + x) * 4; return [px[i], px[i + 1], px[i + 2], px[i + 3]]; }
  const half = (win - 1) >> 1;
  let r = 0, g = 0, b = 0, a = 0, n = 0;
  for (let dy = -half; dy <= half; dy++) {
    const yy = Math.min(h - 1, Math.max(0, y + dy));
    for (let dx = -half; dx <= half; dx++) {
      const xx = Math.min(w - 1, Math.max(0, x + dx));
      const i = (yy * w + xx) * 4;
      r += px[i]; g += px[i + 1]; b += px[i + 2]; a += px[i + 3]; n++;
    }
  }
  return [r / n, g / n, b / n, a / n];
}

/**
 * Magic wand.  metric: 'alpha' | 'luma' | 'rgb' (rgb = largest channel difference, alpha included for luma/rgb so that
 * transparent pixels never join an opaque seed).  Returns a 0/255 plane and its pixel count.
 * The seed pixel itself is always selected.  Contiguous = 4-connected.
 */
export function floodSelect(px, w, h, sx, sy, { metric = "rgb", tolerance = 32, contiguous = true, window = 1 } = {}) {
  const out = new Uint8Array(w * h);
  sx |= 0; sy |= 0;
  if (sx < 0 || sy < 0 || sx >= w || sy >= h) return { mask: out, area: 0 };
  const s = sampleWindow(px, w, h, sx, sy, window | 0);
  const sa = s[3];
  const sY = 0.2126 * s[0] + 0.7152 * s[1] + 0.0722 * s[2];
  const tol = +tolerance;
  let dist;
  if (metric === "alpha") dist = (i) => Math.abs(px[i + 3] - sa);
  else if (metric === "luma") {
    dist = (i) => {
      const dy = Math.abs(0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] - sY);
      const da = Math.abs(px[i + 3] - sa);
      return dy > da ? dy : da;
    };
  } else {
    dist = (i) => {
      let m = Math.abs(px[i + 3] - sa);
      const dr = Math.abs(px[i] - s[0]); if (dr > m) m = dr;
      const dg = Math.abs(px[i + 1] - s[1]); if (dg > m) m = dg;
      const db = Math.abs(px[i + 2] - s[2]); if (db > m) m = db;
      return m;
    };
  }
  let area = 0;
  if (!contiguous) {
    for (let p = 0, n = w * h; p < n; p++) if (dist(p << 2) <= tol) { out[p] = 255; area++; }
    const seed = sy * w + sx;
    if (!out[seed]) { out[seed] = 255; area++; }
    return { mask: out, area };
  }
  const seen = new Uint8Array(w * h);
  const stack = new Int32Array(w * h);
  let sp = 0;
  const start = sy * w + sx;
  seen[start] = 1;
  stack[sp++] = start;
  while (sp) {
    const i = stack[--sp];
    out[i] = 255; area++;
    const y = (i / w) | 0, x = i - y * w;
    if (x > 0 && !seen[i - 1]) { seen[i - 1] = 1; if (dist((i - 1) << 2) <= tol) stack[sp++] = i - 1; }
    if (x < w - 1 && !seen[i + 1]) { seen[i + 1] = 1; if (dist((i + 1) << 2) <= tol) stack[sp++] = i + 1; }
    if (y > 0 && !seen[i - w]) { seen[i - w] = 1; if (dist((i - w) << 2) <= tol) stack[sp++] = i - w; }
    if (y < h - 1 && !seen[i + w]) { seen[i + w] = 1; if (dist((i + w) << 2) <= tol) stack[sp++] = i + w; }
  }
  return { mask: out, area };
}

// ------------------------------------------------------------------------------------------ connected components
/** The 8-connected island of pixels above `thr` that contains (sx,sy).  Returns 0/255 plane + area, or area 0. */
export function componentFrom(alpha, w, h, sx, sy, thr = CONTENT_T) {
  const out = new Uint8Array(w * h);
  if (sx < 0 || sy < 0 || sx >= w || sy >= h || alpha[sy * w + sx] <= thr) return { mask: out, area: 0 };
  const stack = new Int32Array(w * h);
  let sp = 0, area = 0;
  const start = sy * w + sx;
  out[start] = 255; stack[sp++] = start;
  while (sp) {
    const i = stack[--sp];
    area++;
    const y = (i / w) | 0, x = i - y * w;
    for (let dy = -1; dy <= 1; dy++) {
      const yy = y + dy;
      if (yy < 0 || yy >= h) continue;
      for (let dx = -1; dx <= 1; dx++) {
        const xx = x + dx;
        if (xx < 0 || xx >= w || (dx === 0 && dy === 0)) continue;
        const j = yy * w + xx;
        if (!out[j] && alpha[j] > thr) { out[j] = 255; stack[sp++] = j; }
      }
    }
  }
  return { mask: out, area };
}

/**
 * Label every 8-connected island of pixels above `thr`.  labels[i] = island id (1-based) or 0.
 * comps[k] = {id, area, x0,y0,x1,y1}; unsorted (id order = scan order).
 */
export function labelComponents(alpha, w, h, thr = CONTENT_T) {
  const labels = new Int32Array(w * h);
  const stack = new Int32Array(w * h);
  const comps = [];
  let id = 0;
  for (let p = 0, n = w * h; p < n; p++) {
    if (labels[p] || alpha[p] <= thr) continue;
    id++;
    let sp = 0, area = 0, x0 = w, y0 = h, x1 = -1, y1 = -1;
    labels[p] = id; stack[sp++] = p;
    while (sp) {
      const i = stack[--sp];
      area++;
      const y = (i / w) | 0, x = i - y * w;
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      for (let dy = -1; dy <= 1; dy++) {
        const yy = y + dy;
        if (yy < 0 || yy >= h) continue;
        for (let dx = -1; dx <= 1; dx++) {
          const xx = x + dx;
          if (xx < 0 || xx >= w) continue;
          const j = yy * w + xx;
          if (!labels[j] && alpha[j] > thr) { labels[j] = id; stack[sp++] = j; }
        }
      }
    }
    comps.push({ id, area, x0, y0, x1, y1 });
  }
  return { labels, comps };
}

/** 0/255 plane of the pixels whose label is in `ids` (a Set of numbers). */
export function maskFromLabels(labels, ids) {
  const out = new Uint8Array(labels.length);
  for (let i = 0, n = labels.length; i < n; i++) if (labels[i] && ids.has(labels[i])) out[i] = 255;
  return out;
}

// ------------------------------------------------------------------------------------------ morphology (exact circle)
const INF = 1e20;

/** Squared Euclidean distance (pixels) from every pixel to the nearest pixel with src=1.  INF where there is none. */
function sqDistance(src, w, h) {
  const f = new Float32Array(w * h);
  const cd = new Float32Array(w).fill(INF);
  for (let y = 0; y < h; y++) {                       // downward sweep, row-major for cache friendliness
    const row = y * w;
    for (let x = 0; x < w; x++) {
      cd[x] = src[row + x] ? 0 : (cd[x] < INF ? cd[x] + 1 : INF);
      f[row + x] = cd[x];
    }
  }
  cd.fill(INF);
  for (let y = h - 1; y >= 0; y--) {                  // upward sweep
    const row = y * w;
    for (let x = 0; x < w; x++) {
      cd[x] = src[row + x] ? 0 : (cd[x] < INF ? cd[x] + 1 : INF);
      if (cd[x] < f[row + x]) f[row + x] = cd[x];
    }
  }
  for (let i = 0, n = w * h; i < n; i++) f[i] = f[i] >= INF ? INF : f[i] * f[i];
  // lower envelope of parabolas along each row (Felzenszwalb & Huttenlocher)
  const d = new Float32Array(w * h);
  const v = new Int32Array(w), z = new Float64Array(w + 1), g = new Float64Array(w);
  for (let y = 0; y < h; y++) {
    const row = y * w;
    let any = false;
    for (let x = 0; x < w; x++) { g[x] = f[row + x]; if (g[x] < INF) any = true; }
    if (!any) { for (let x = 0; x < w; x++) d[row + x] = INF; continue; }
    let k = 0;
    v[0] = 0; z[0] = -Infinity; z[1] = Infinity;
    for (let q = 1; q < w; q++) {
      if (g[q] >= INF) continue;
      let s;
      for (;;) {
        const p = v[k];
        s = ((g[q] + q * q) - (g[p] + p * p)) / (2 * q - 2 * p);
        if (s <= z[k]) { k--; if (k < 0) { k = 0; break; } } else break;
      }
      if (g[v[k]] >= INF) { v[0] = q; z[0] = -Infinity; z[1] = Infinity; k = 0; continue; }
      k++; v[k] = q; z[k] = s; z[k + 1] = Infinity;
    }
    k = 0;
    for (let q = 0; q < w; q++) {
      while (z[k + 1] < q) k++;
      const p = v[k];
      d[row + q] = (q - p) * (q - p) + g[p];
    }
  }
  return d;
}

/**
 * Grow ('grow') or shrink ('shrink') the selection by `radius` pixels with a true circular structuring element.
 * Input is thresholded at SEL_T; output is a 0/255 plane.  Shrinking never erodes from the grid border.
 */
export function morphMask(a, w, h, bbox, radius, mode) {
  const out = thresholdPlane(a, SEL_T);
  if (!bbox || !(radius > 0)) return out;
  const m = mode === "grow" ? Math.ceil(radius) : 1;
  const rx0 = Math.max(0, bbox.x0 - m), ry0 = Math.max(0, bbox.y0 - m);
  const rx1 = Math.min(w - 1, bbox.x1 + m), ry1 = Math.min(h - 1, bbox.y1 + m);
  const rw = rx1 - rx0 + 1, rh = ry1 - ry0 + 1;
  const src = new Uint8Array(rw * rh);
  const grow = mode === "grow";
  for (let y = 0; y < rh; y++) {
    const orow = (y + ry0) * w + rx0, row = y * rw;
    for (let x = 0; x < rw; x++) src[row + x] = grow ? (out[orow + x] ? 1 : 0) : (out[orow + x] ? 0 : 1);
  }
  const d2 = sqDistance(src, rw, rh);
  const r2 = radius * radius;
  for (let y = 0; y < rh; y++) {
    const orow = (y + ry0) * w + rx0, row = y * rw;
    for (let x = 0; x < rw; x++) {
      if (d2[row + x] > r2) continue;
      const o = orow + x;
      if (grow) { if (!out[o]) out[o] = 255; } else if (out[o]) out[o] = 0;
    }
  }
  return out;
}

// ------------------------------------------------------------------------------------------ feather (gaussian ~ 3 box blurs)
function boxSizes(sigma, n) {
  const wIdeal = Math.sqrt((12 * sigma * sigma) / n + 1);
  let wl = Math.floor(wIdeal);
  if (wl % 2 === 0) wl--;
  const wu = wl + 2;
  const mIdeal = (12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4);
  const m = Math.round(mIdeal);
  const sizes = [];
  for (let i = 0; i < n; i++) sizes.push(i < m ? wl : wu);
  return sizes;
}

function boxH(src, dst, w, h, r) {
  const inv = 1 / (2 * r + 1);
  for (let y = 0; y < h; y++) {
    const row = y * w;
    let sum = 0;
    for (let k = -r; k <= r; k++) sum += src[row + Math.min(w - 1, Math.max(0, k))];
    dst[row] = sum * inv;
    for (let x = 1; x < w; x++) {
      sum += src[row + Math.min(w - 1, x + r)] - src[row + Math.max(0, x - 1 - r)];
      dst[row + x] = sum * inv;
    }
  }
}

function boxV(src, dst, w, h, r) {
  const inv = 1 / (2 * r + 1);
  const col = new Float64Array(w);
  for (let k = -r; k <= r; k++) {
    const yy = Math.min(h - 1, Math.max(0, k)) * w;
    for (let x = 0; x < w; x++) col[x] += src[yy + x];
  }
  for (let x = 0; x < w; x++) dst[x] = col[x] * inv;
  for (let y = 1; y < h; y++) {
    const add = Math.min(h - 1, y + r) * w, sub = Math.max(0, y - 1 - r) * w, row = y * w;
    for (let x = 0; x < w; x++) { col[x] += src[add + x] - src[sub + x]; dst[row + x] = col[x] * inv; }
  }
}

/** Soften the mask edge: gaussian blur of the alpha plane (transition about `radius` px each side).  Returns a new plane. */
export function featherPlane(a, w, h, any, radius) {
  const out = new Uint8Array(a);
  if (!any || !(radius > 0)) return out;
  const sizes = boxSizes(radius / 2, 3).map((s) => (s - 1) >> 1);
  const margin = Math.ceil(sizes.reduce((s, r) => s + r, 0)) + 2;
  const rx0 = Math.max(0, any.x0 - margin), ry0 = Math.max(0, any.y0 - margin);
  const rx1 = Math.min(w - 1, any.x1 + margin), ry1 = Math.min(h - 1, any.y1 + margin);
  const rw = rx1 - rx0 + 1, rh = ry1 - ry0 + 1;
  let buf = new Float32Array(rw * rh), tmp = new Float32Array(rw * rh);
  for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) buf[y * rw + x] = a[(y + ry0) * w + rx0 + x];
  for (const r of sizes) {
    boxH(buf, tmp, rw, rh, r);
    boxV(tmp, buf, rw, rh, r);
  }
  for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) out[(y + ry0) * w + rx0 + x] = Math.round(buf[y * rw + x]);
  return out;
}

// ------------------------------------------------------------------------------------------ outline for the marching ants
/**
 * RGBA ImageData-sized buffer (black, alpha 255 on the outline) for the pixels of the selection that touch the outside
 * (or the grid border) - `thickness` rings deep so the line stays visible when the view is zoomed out.
 */
export function outlineRGBA(a, w, h, bbox, thickness, out) {
  const rgba = out && out.length === w * h * 4 ? out : new Uint8ClampedArray(w * h * 4);
  rgba.fill(0);
  if (!bbox) return rgba;
  const x0 = bbox.x0, y0 = bbox.y0, x1 = bbox.x1, y1 = bbox.y1;
  const lvl = new Uint8Array(w * h);                  // 0 = not outline, k = ring k (1 = outermost)
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const i = y * w + x;
      if (a[i] <= SEL_T) continue;
      if (x === 0 || y === 0 || x === w - 1 || y === h - 1 || a[i - 1] <= SEL_T || a[i + 1] <= SEL_T || a[i - w] <= SEL_T || a[i + w] <= SEL_T) lvl[i] = 1;
    }
  }
  for (let k = 2; k <= thickness; k++) {
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const i = y * w + x;
        if (lvl[i] || a[i] <= SEL_T) continue;
        if ((x > 0 && lvl[i - 1] === k - 1) || (x < w - 1 && lvl[i + 1] === k - 1) || (y > 0 && lvl[i - w] === k - 1) || (y < h - 1 && lvl[i + w] === k - 1)) lvl[i] = k;
      }
    }
  }
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) if (lvl[y * w + x]) rgba[(y * w + x) * 4 + 3] = 255;
  return rgba;
}

// ------------------------------------------------------------------------------------------ diff overlay
export const DIFF_COLORS = {
  extra: [255, 59, 92],     // the layer has pixels where the source is empty
  differs: [255, 176, 32],  // the layer has pixels whose colour differs strongly from the source
  missing: [59, 130, 255],  // the source is solid but the layer is empty
};

/**
 * RGBA highlight buffer for the "diff" overlay.
 *   extra   - layer alpha > CONTENT_T where the source alpha <= CONTENT_T            (wrong, probably another part)
 *   differs - both have content but a colour channel differs by more than `thr`, or the alphas differ by > 96
 *   missing - source alpha > SEL_T and layer alpha <= CONTENT_T                        (may belong to another layer)
 */
export function buildDiff(layer, source, thr = 48, out) {
  const n = layer.length >> 2;
  const rgba = out && out.length === layer.length ? out : new Uint8ClampedArray(layer.length);
  rgba.fill(0);
  const [er, eg, eb] = DIFF_COLORS.extra, [dr, dg, db] = DIFF_COLORS.differs, [mr, mg, mb] = DIFF_COLORS.missing;
  for (let p = 0, i = 0; p < n; p++, i += 4) {
    const la = layer[i + 3], sa = source ? source[i + 3] : 0;
    if (la > CONTENT_T) {
      if (sa <= CONTENT_T) { rgba[i] = er; rgba[i + 1] = eg; rgba[i + 2] = eb; rgba[i + 3] = 215; continue; }
      let m = Math.abs(la - sa) > 96 ? 255 : 0;
      const a = Math.abs(layer[i] - source[i]); if (a > m) m = a;
      const b = Math.abs(layer[i + 1] - source[i + 1]); if (b > m) m = b;
      const c = Math.abs(layer[i + 2] - source[i + 2]); if (c > m) m = c;
      if (m > thr) { rgba[i] = dr; rgba[i + 1] = dg; rgba[i + 2] = db; rgba[i + 3] = 205; }
    } else if (sa > SEL_T) {
      rgba[i] = mr; rgba[i + 1] = mg; rgba[i + 2] = mb; rgba[i + 3] = 105;
    }
  }
  return rgba;
}
