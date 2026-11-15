// Shared by overview.html and offers.html: quality criteria, scoring and the criterion explainer.
// Needs: DATA.criteria (data/criteria.json), DATA.amenities (data/amenities.json), DATA.districts ({name: {lat, lon}}).
const QC = (() => {
  const CRITS = DATA.criteria.criteria, BY = Object.fromEntries(CRITS.map(c => [c.id, c]));
  const GROUPS = DATA.criteria.groups;
  const AM = (DATA.amenities && DATA.amenities.districts) || {};
  const e = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const m = v => v == null ? "–" : v >= 1000 ? (v / 1000).toFixed(1) + " km" : Math.round(v / 10) * 10 + " m";

  // District used for neighbourhood facts: exact name, else the nearest district centre.
  function districtOf(name, lat, lon) {
    if (name && AM[name]) return name;
    if (lat == null || !DATA.districts) return null;
    let best = null, bd = 1e9;
    for (const [n, d] of Object.entries(DATA.districts)) {
      if (!AM[n]) continue;
      const dd = (d.lat - lat) ** 2 + ((d.lon - lon) * 0.63) ** 2;
      if (dd < bd) { bd = dd; best = n; }
    }
    return best;
  }
  function step(c, v) {
    if (v == null) return null;
    for (const [lim, s] of c.thresholds) if (v <= lim) return s;
    return c.else;
  }
  // Score one computed neighbourhood criterion for a district → {s, why} or null.
  function area(id, district) {
    const a = AM[district], c = BY[id];
    if (!a || !c) return null;
    const at = ` from the ${e(district)} centre`;
    if (id === "nature") {
      if (a.forest) return {s: step(c, a.forest.m), why: `${e(a.forest.name || "Forest")} ${m(a.forest.m)}${at}`};
      if (a.park) return {s: Math.max(1, step(c, a.park.m) - 1), why: `No forest within 2.5 km; park ${e(a.park.name)} ${m(a.park.m)}`};
      return {s: 1, why: "No forest or park within 2.5 km"};
    }
    if (id === "shopping") {
      const s0 = step(c, a.supermarket?.m) ?? 1, bonus = a.supermarkets_1km >= 3 ? 0.5 : 0;
      return {s: Math.min(5, s0 + bonus), why: a.supermarket ? `${e(a.supermarket.name || "Supermarket")} ${m(a.supermarket.m)}${at}; ${a.supermarkets_1km} within 1 km` : "No supermarket within 2.5 km"};
    }
    if (id === "schools") {
      const parts = [["Kita", a.kindergarten], ["Grundschule", a.primary_school], ["Secondary", a.secondary_school]];
      const avg = parts.reduce((t, [, x]) => t + (x ? x.m : 3000), 0) / 3;
      return {s: step(c, avg), why: parts.map(([l, x]) => `${l} ${x ? m(x.m) : "> 2.5 km"}${x?.name ? ` (${e(x.name)})` : ""}`).join(" · ")};
    }
    if (id === "transport") {
      if (a.rail && a.rail.m <= 1500) return {s: step(c, a.rail.m), why: `${e(a.rail.name || "Stop")} (Stadtbahn/train) ${m(a.rail.m)}${at}; ${a.bus_stops_500m} bus stops within 500 m`};
      return {s: a.bus_stops_500m >= 3 ? 2.5 : a.bus_stops_500m ? 2 : 1, why: `No Stadtbahn/train within 1.5 km; ${a.bus_stops_500m} bus stops within 500 m`};
    }
    if (id === "city") return {s: step(c, a.hbf_km), why: `${a.hbf_km} km to Bonn Hbf (≈ ${Math.round(a.hbf_km * 4)} min by bike), ${a.godesberg_km} km to Bad Godesberg`};
    return null;
  }
  function space(size) {
    if (!size) return null;
    const s = Math.max(0, Math.min(5, (size - 90) / 20));
    return {s: Math.round(s * 10) / 10, why: `${size} m² → (${size} − 90) / 20 = ${s.toFixed(1)}`};
  }
  // All criteria for a shortlist home → {id: {s, why}}
  function forListing(l) {
    const out = {}, d = districtOf(l.district, l.lat, l.lon);
    for (const c of CRITS) {
      if (c.id === "space") out[c.id] = space(l.size_m2);
      else if (c.kind === "computed") out[c.id] = area(c.id, d);
      else out[c.id] = l.features?.[c.id] ?? null;
    }
    return out;
  }
  function weighted(scores, W) {
    let n = 0, d = 0;
    for (const c of CRITS) { const x = scores[c.id]; if (x && x.s != null && W[c.id]) { n += W[c.id] * x.s; d += W[c.id]; } }
    return d ? n / d : 0;
  }
  // Scale step a score falls on, e.g. 4.5 → "4 = …" (the step at or below the score).
  function rule(id, sc) {
    const c = BY[id]; if (!c || sc == null) return "";
    const k = Math.max(1, Math.min(5, Math.floor(sc + 1e-9)));
    const txt = c.scale[String(k)];
    return txt ? `<div class="rule">${k} = ${e(txt)}${c.id === "space" ? "" : ""}</div>` : "";
  }
  const bar = s => `<span class="qbar"><span style="width:${(s ?? 0) * 20}%"></span></span>`;
  const label = id => `<button type="button" class="crit" data-crit="${id}">${e(BY[id].label)}</button>`;
  function breakdown(scores, W) {
    return GROUPS.map(g => {
      const rows = CRITS.filter(c => c.group === g.id).map(c => {
        const x = scores[c.id];
        return `<tr><td>${label(c.id)}</td><td class="num">${x ? x.s : "–"}</td><td>${bar(x?.s)}</td><td class="note num">${W ? W[c.id] : c.weight}</td><td class="why">${x ? x.why + rule(c.id, x.s) : "<span class='note'>no data yet</span>"}</td></tr>`;
      }).join("");
      return `<tr class="grp"><td colspan="5">${e(g.label)}</td></tr>${rows}`;
    }).join("");
  }
  const breakdownTable = (scores, W) => `<table class="qtable"><thead><tr><th>Criterion</th><th class="num">Score</th><th></th><th class="num">Weight</th><th>Why</th></tr></thead><tbody>${breakdown(scores, W)}</tbody></table>`;

  // Explainer dialog. `examples(id)` may return rows [[name, {s, why}, href]] to show how homes score.
  let dlg = null, examplesFn = null;
  function explain(id) {
    const c = BY[id]; if (!c) return;
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.className = "critdlg"; document.body.appendChild(dlg);
      dlg.addEventListener("click", ev => { if (ev.target === dlg || ev.target.closest(".critclose")) dlg.close(); });
    }
    const ex = examplesFn ? examplesFn(id) : [];
    const src = c.kind === "computed" && c.id !== "space"
      ? `<p class="note">Source: ${e(DATA.amenities?.source || "OpenStreetMap")}. Homes are only placed at district level, so these are district facts, not the exact address.</p>`
      : c.kind === "judged" ? `<p class="note">Judged per home from the listing text and photos; the reason is shown next to each score.</p>` : "";
    dlg.innerHTML = `<div class="critbody"><button class="critclose" aria-label="Close">✕</button>
      <div class="note">${e(GROUPS.find(g => g.id === c.group)?.label)} · default weight ${c.weight}</div>
      <h3>${e(c.label)}</h3><p>${e(c.what)}</p>
      <table class="qtable"><tbody>${Object.entries(c.scale).sort((a, b) => b[0] - a[0]).map(([s, t]) => `<tr><td class="num"><b>${s}</b></td><td>${bar(+s)}</td><td>${e(t)}</td></tr>`).join("")}</tbody></table>
      ${src}
      ${ex.length ? `<h4>How the homes score</h4><table class="qtable"><tbody>${ex.map(([n, x, href]) => `<tr><td>${href ? `<a href="${href}">${e(n)}</a>` : e(n)}</td><td class="num">${x ? x.s : "–"}</td><td>${bar(x?.s)}</td><td class="why">${x ? x.why + rule(id, x.s) : ""}</td></tr>`).join("")}</tbody></table>` : ""}</div>`;
    dlg.querySelectorAll("a").forEach(a => a.addEventListener("click", () => dlg.close()));
    dlg.showModal();
  }
  document.addEventListener("click", ev => { const b = ev.target.closest("button.crit"); if (b) { ev.preventDefault(); ev.stopPropagation(); explain(b.dataset.crit); } }, true);
  return {rule, CRITS, BY, GROUPS, AM, districtOf, area, space, forListing, weighted, breakdownTable, label, bar, explain, m, setExamples: f => { examplesFn = f; }};
})();
