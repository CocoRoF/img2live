// SPDX-License-Identifier: Apache-2.0
// "My puppets": the ids of the jobs this browser made, kept in localStorage (there is no login; the id is the key to a job).
const KEY = "i2l_mine_v1";
const MAX = 500;

function read() {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v.filter((x) => x && typeof x.id === "string") : []; }
  catch (e) { return []; }
}
function write(list) { try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX))); return true; } catch (e) { return false; } }

export const mine = {
  list: read,
  has: (id) => read().some((x) => x.id === id),
  add(id, prompt = "") {
    const l = read().filter((x) => x.id !== id);
    l.unshift({ id, prompt: String(prompt).slice(0, 200), at: Math.floor(Date.now() / 1000) });
    return write(l);
  },
  remove(id) { return write(read().filter((x) => x.id !== id)); },
  keepOnly(ids) { const s = new Set(ids); return write(read().filter((x) => s.has(x.id))); },
  exportText: () => JSON.stringify(read().map((x) => x.id)),
  importText(text) {
    let ids; try { ids = JSON.parse(text); } catch (e) { return -1; }
    if (!Array.isArray(ids)) return -1;
    const have = new Set(read().map((x) => x.id)); let n = 0; const l = read();
    for (const id of ids) if (typeof id === "string" && /^[A-Za-z0-9_-]{16,40}$/.test(id) && !have.has(id)) { l.push({ id, prompt: "", at: 0 }); have.add(id); n++; }
    write(l); return n;
  },
};

export async function lookup(ids) {
  if (!ids.length) return { jobs: [], now: Date.now() / 1000 };
  const out = { jobs: [], now: Date.now() / 1000 };
  for (let i = 0; i < ids.length; i += 100) {
    const r = await fetch("/api/jobs/lookup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: ids.slice(i, i + 100) }) });
    if (!r.ok) throw new Error("lookup " + r.status);
    const d = await r.json(); out.jobs.push(...d.jobs); out.now = d.now;
  }
  return out;
}
