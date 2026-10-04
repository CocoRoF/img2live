// SPDX-License-Identifier: Apache-2.0
// A browser's MediaRecorder writes a "live" WebM: no Duration, so some players show 0:00 and many editors cannot seek.
// Insert the Duration element into the Info element (the file has no SeekHead/Cues that would point past it).

const readVint = (b, i, keepMarker = false) => {
  let n = 1;
  while (n <= 8 && !(b[i] & (0x80 >> (n - 1)))) n++;
  if (n > 8) throw new Error("bad EBML vint");
  let v = keepMarker ? b[i] : b[i] & ((0x80 >> (n - 1)) - 1);
  for (let k = 1; k < n; k++) v = v * 256 + b[i + k];
  return [v, n];
};
const encodeSize = (v) => {
  let n = 1;
  while (v >= 2 ** (7 * n) - 1) n++;                 // all-ones is "unknown": stay below it
  const out = new Uint8Array(n);
  let x = v;
  for (let k = n - 1; k >= 0; k--) { out[k] = x % 256; x = Math.floor(x / 256); }
  out[0] |= 0x80 >> (n - 1);
  return out;
};

/** Returns a copy of ``blob`` (a MediaRecorder WebM) whose Info element carries ``ms`` as its Duration. Never throws:
 *  a file it does not understand comes back unchanged. */
export async function fixWebmDuration(blob, ms) {
  try {
    const b = new Uint8Array(await blob.slice(0, 8192).arrayBuffer());
    let i = 0;
    const [ebmlId, n0] = readVint(b, 0, true);
    if (ebmlId !== 0x1a45dfa3) return blob;
    const [ebmlSize, m0] = readVint(b, n0);
    i = n0 + m0 + ebmlSize;                                   // after the EBML header
    const [segId, n1] = readVint(b, i, true);
    if (segId !== 0x18538067) return blob;
    const [, m1] = readVint(b, i + n1);
    i += n1 + m1;                                              // inside the Segment (its size is "unknown" in a live file)
    for (let guard = 0; guard < 16 && i < b.length - 8; guard++) {
      const [id, n] = readVint(b, i, true);
      const [size, m] = readVint(b, i + n);
      if (id !== 0x1549a966) { i += n + m + size; continue; }  // skip SeekHead / Void / ... until Info
      const dataStart = i + n + m, dataEnd = dataStart + size;
      // timecode scale (ns per tick), default 1 ms
      let scale = 1e6, hasDuration = false;
      for (let j = dataStart; j < dataEnd;) {
        const [cid, cn] = readVint(b, j, true);
        const [csz, cm] = readVint(b, j + cn);
        if (cid === 0x2ad7b1) { scale = 0; for (let k = 0; k < csz; k++) scale = scale * 256 + b[j + cn + cm + k]; }
        if (cid === 0x4489) hasDuration = true;
        j += cn + cm + csz;
      }
      if (hasDuration) return blob;                            // already has one
      const dur = new Uint8Array(11);
      dur.set([0x44, 0x89, 0x88]);
      new DataView(dur.buffer).setFloat64(3, (ms * 1e6) / scale);
      const body = new Uint8Array(size + dur.length);
      body.set(b.subarray(dataStart, dataEnd)); body.set(dur, size);
      return new Blob([b.subarray(0, i + n), encodeSize(body.length), body, blob.slice(dataEnd)], { type: blob.type });
    }
    return blob;
  } catch (e) {
    console.warn("webm duration fix skipped:", e);
    return blob;
  }
}
