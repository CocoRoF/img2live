// SPDX-License-Identifier: Apache-2.0
// Thin client for the studio REST API (see plan/08-studio.md §4).  Every call is keyed by the job's private id.
// The UI modules take an object shaped like the one returned here, so tests can pass a fake.

async function json(r) {
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(j.detail || `오류 ${r.status}`); e.status = r.status; throw e; }
  return j;
}
const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) }).then(json);

/** Canvas (any content; red/alpha/luma > 127 counts as selected) -> base64 PNG of an 8-bit grey mask. */
export function maskToBase64(canvas, { channel = "alpha" } = {}) {
  const w = canvas.width, h = canvas.height;
  const src = canvas.getContext("2d", { willReadFrequently: true }).getImageData(0, 0, w, h).data;
  const out = document.createElement("canvas"); out.width = w; out.height = h;
  const octx = out.getContext("2d"); const img = octx.createImageData(w, h);
  for (let i = 0; i < w * h; i++) {
    const v = channel === "alpha" ? src[i * 4 + 3] : src[i * 4];
    img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v; img.data[i * 4 + 3] = 255;
  }
  octx.putImageData(img, 0, 0);
  return out.toDataURL("image/png").split(",")[1];
}

export function studioApi(jobId) {
  const base = `/api/jobs/${jobId}/studio`;
  const L = (tag) => `${base}/layer/${encodeURIComponent(tag)}`;
  return {
    jobId,
    state: () => fetch(base, { cache: "no-store" }).then(json),
    /** URL of a layer version in its full edit grid (use with <img> or fetch). */
    layerImageUrl: (tag, v = "current", rev = 0) => `${L(tag)}/image?v=${encodeURIComponent(v)}&r=${rev}`,
    layerThumbUrl: (tag, v = "current", rev = 0) => `${L(tag)}/thumb?v=${encodeURIComponent(v)}&r=${rev}`,
    sourceUrl: (grid = "canvas", rev = 0) => `${base}/source?grid=${grid}&r=${rev}`,
    /** op: erase | restore | move | clean | fill_hole ; mask: base64 PNG (grid-sized, > 127 selected) */
    edit: (tag, payload) => post(`${L(tag)}/edit`, payload),
    select: (tag, version) => post(`${L(tag)}/select`, { version }),
    flags: (tag, flags) => post(`${L(tag)}/flags`, flags),
    deleteVersion: (tag, vid) => fetch(`${L(tag)}/version/${encodeURIComponent(vid)}`, { method: "DELETE" }).then(json),
    rebuild: () => post(`${base}/rebuild`),
    reset: () => post(`${base}/reset`),
    regen: (payload) => post(`${base}/regen`, payload),
  };
}
