// SPDX-License-Identifier: Apache-2.0
// Inline SVG icons for the layer editor (24x24 grid, stroke = currentColor).  Static, trusted markup only.

const P = {
  brush: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  eraser: '<path d="m7 21-4.3-4.3a2 2 0 0 1 0-2.8l9.6-9.6a2 2 0 0 1 2.8 0l5.6 5.6a2 2 0 0 1 0 2.8L13 21"/><path d="M22 21H7"/><path d="m5 11 9 9"/>',
  wand: '<path d="m4 20 10-10"/><path d="m12.5 8.5 3 3"/><path d="M17 3v3M15.5 4.5h3"/><path d="M20 10v2.5M18.75 11.25h2.5"/><path d="M8 4v2.5M6.75 5.25h2.5"/>',
  lasso: '<path d="M7 17.3C4.2 16.5 2.5 14.8 2.5 12.7 2.5 9.1 6.8 6 12 6s9.5 3.1 9.5 6.7-4.3 6.5-9.5 6.5c-1 0-2-.1-2.9-.3"/><circle cx="6.2" cy="17.3" r="1.7"/><path d="M5.6 19c-.3 1.3-1 2-2.1 2.4"/>',
  rect: '<rect x="4" y="5" width="16" height="14" rx="1.5" stroke-dasharray="3.2 2.6"/>',
  island: '<path d="M4.5 9.5c0-3 2.2-5 5-5s4.5 2 4 4.6c-.4 2.2-2.4 3.4-4.6 3.4-2.6 0-4.4-1-4.4-3Z"/><path d="M14 17.5c0-1.9 1.4-3 3.2-3s3.3 1.2 3.3 3-1.5 3-3.3 3-3.2-1.1-3.2-3Z"/><circle cx="19" cy="6" r="1.2"/>',
  hand: '<path d="M18 11V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2"/><path d="M14 10V4a2 2 0 0 0-2-2 2 2 0 0 0-2 2v2"/><path d="M10 10.5V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.9-6-2.3l-3.6-3.6a2 2 0 0 1 2.8-2.8L7 15"/>',
  zoom: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6M11 8v6M8 11h6"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1.1.9-1.1 1.7"/><path d="M12 17h.01"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  fit: '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12M9 7V4h6v3"/>',
  restore: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m21 16-5-5-9 9"/>',
  move: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  clean: '<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  hole: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3" stroke-dasharray="2 2"/>',
  all: '<rect x="4" y="4" width="16" height="16" rx="2" stroke-dasharray="3.2 2.6"/><path d="m8.5 12.3 2.4 2.4 4.6-5.2"/>',
  none: '<rect x="4" y="4" width="16" height="16" rx="2" stroke-dasharray="3.2 2.6"/><path d="M9 9l6 6M15 9l-6 6"/>',
  invert: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16Z" fill="currentColor"/>',
  grow: '<rect x="9" y="9" width="6" height="6" rx="1"/><path d="M4 4h16v16H4z" stroke-dasharray="2.6 2.4"/>',
  shrink: '<rect x="4" y="4" width="16" height="16" rx="1.5"/><path d="M9 9h6v6H9z" stroke-dasharray="2.2 2"/>',
  feather: '<circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="7.2" stroke-dasharray="1.5 2.2"/><circle cx="12" cy="12" r="9.6" stroke-dasharray="1 3.4" opacity=".6"/>',
  layer: '<path d="m12 3 9 5-9 5-9-5Z"/><path d="m3 13 9 5 9-5"/>',
  layerOnly: '<path d="m12 4 8 4.5-8 4.5-8-4.5Z" fill="currentColor" fill-opacity=".25"/><path d="m4 13 8 4.5 8-4.5"/>',
  source: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m21 16-5-5-9 9"/>',
  blend: '<rect x="3.5" y="5.5" width="11" height="11" rx="1.5" stroke-dasharray="2.4 2"/><rect x="9.5" y="9.5" width="11" height="9" rx="1.5"/>',
  diff: '<path d="M12 4v16"/><path d="M4 8h5M6.5 5.5v5"/><path d="M15 16h5"/><rect x="3" y="3" width="18" height="18" rx="2"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  chev: '<path d="m9 6 6 6-6 6"/>',
};

/** Markup of one icon (an <svg> string). */
export function icon(name, size = 20) {
  const body = P[name] || P.layer;
  return `<svg class="le-ico" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;
}
