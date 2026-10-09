"use strict";
const $ = (id) => document.getElementById(id);

async function loadStatus() {
  const r = await fetch("/api/status", { credentials: "same-origin" });
  if (!r.ok) throw new Error("status " + r.status);
  const s = await r.json();
  const dl = $("status");
  dl.replaceChildren();
  for (const [k, v] of Object.entries(s)) {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = String(v);
    dl.append(dt, dd);
  }
}

async function main() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  $("signed-in").hidden = false;
  try { await loadStatus(); $("msg").textContent = ""; }
  catch (e) { $("msg").textContent = "Could not load status (" + e.message + ")."; }
}
main();
