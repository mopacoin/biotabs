// Preisverlauf: Klick auf einen "Verlauf"-Button (button.hist mit data-shop/-product/-variant/-size) lädt
// /api/verlauf und zeigt den Preis über alle Läufe als Stufenlinie im Dialog #hist-dialog.
(function () {
  const $ = id => document.getElementById(id);
  const euro = v => v.toLocaleString("de-DE", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " €";
  const day = t => new Date(t).toLocaleDateString("de-DE", {day: "2-digit", month: "2-digit", year: "numeric"});
  const dayShort = t => new Date(t).toLocaleDateString("de-DE", {day: "2-digit", month: "2-digit"});
  const dateTime = t => new Date(t).toLocaleString("de-DE", {day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit"});
  const SVG = "http://www.w3.org/2000/svg";
  const dialog = $("hist-dialog");
  let current = null;  // {points, title} des offenen Verlaufs, für Neuzeichnen bei Größenänderung

  function el(tag, attrs, parent) {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  function niceStep(range, target) {
    const raw = range / target, mag = 10 ** Math.floor(Math.log10(raw));
    return [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => s >= raw) || 10 * mag;
  }

  function render(points) {
    const box = $("hist-chart");
    box.textContent = "";
    if (!points.length) { box.textContent = "Keine Daten."; return; }
    const W = Math.max(box.clientWidth, 280), H = 240, m = {l: 64, r: 16, t: 12, b: 28};
    const ts = points.map(p => new Date(p.t).getTime()), prices = points.map(p => p.price);
    let t0 = ts[0], t1 = ts[ts.length - 1];
    if (t1 - t0 < 36e5) { t0 -= 432e5; t1 += 432e5; }  // ein einzelner Lauf: halber Tag Luft
    let lo = Math.min(...prices), hi = Math.max(...prices);
    const pad = hi - lo < 0.01 ? Math.max(1, hi * 0.05) : (hi - lo) * 0.15;
    const step = niceStep(hi - lo + 2 * pad, 4);
    lo = Math.floor((lo - pad) / step) * step; hi = Math.ceil((hi + pad) / step) * step;
    lo = Math.max(0, lo);
    const x = t => m.l + (t - t0) / (t1 - t0) * (W - m.l - m.r);
    const y = v => m.t + (hi - v) / (hi - lo) * (H - m.t - m.b);

    const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Preisverlauf, Details in der Tabelle darunter"}, box);
    for (let v = lo; v <= hi + step / 2; v += step) {
      el("line", {x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: "var(--grid)", "stroke-width": 1}, svg);
      const label = el("text", {x: m.l - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 12, fill: "var(--muted)"}, svg);
      label.textContent = euro(v);
    }
    const ticks = Math.min(6, Math.max(2, Math.floor((W - m.l - m.r) / 90)));
    for (let i = 0; i <= ticks; i++) {
      const t = t0 + (t1 - t0) * i / ticks;
      const label = el("text", {x: x(t), y: H - 8, "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle", "font-size": 12, fill: "var(--muted)"}, svg);
      label.textContent = dayShort(t);
    }

    // Tiefstpreis (lieferbar) als gestrichelte Bezugslinie
    const buyable = points.filter(p => p.available).map(p => p.price);
    if (buyable.length) {
      const low = Math.min(...buyable);
      el("line", {x1: m.l, x2: W - m.r, y1: y(low), y2: y(low), stroke: "var(--muted)", "stroke-width": 1, "stroke-dasharray": "4 4"}, svg);
    }

    // Stufenlinie: ein Preis gilt bis zum nächsten Lauf
    let d = `M${x(ts[0])},${y(prices[0])}`;
    for (let i = 1; i < points.length; i++) d += `H${x(ts[i])}V${y(prices[i])}`;
    el("path", {d, fill: "none", stroke: "var(--series)", "stroke-width": 2, "stroke-linejoin": "round"}, svg);
    points.forEach((p, i) => {
      if (!p.available) el("circle", {cx: x(ts[i]), cy: y(p.price), r: 4, fill: "var(--bg)", stroke: "var(--series)", "stroke-width": 2}, svg);
    });
    const last = points.length - 1;
    el("circle", {cx: x(ts[last]), cy: y(prices[last]), r: 5, fill: "var(--series)", stroke: "var(--bg)", "stroke-width": 2}, svg);

    // Hover und Tastatur: Fadenkreuz rastet auf dem nächsten Lauf ein
    const cross = el("line", {y1: m.t, y2: H - m.b, stroke: "var(--muted)", "stroke-width": 1, visibility: "hidden"}, svg);
    const dot = el("circle", {r: 5, fill: "var(--series)", stroke: "var(--bg)", "stroke-width": 2, visibility: "hidden"}, svg);
    const hit = el("rect", {x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: "transparent", tabindex: 0, "aria-label": "Mit Pfeiltasten durch die Läufe"}, svg);
    const tip = document.createElement("div");
    tip.className = "hist-tip";
    tip.hidden = true;
    box.appendChild(tip);
    let idx = last;

    function show(i) {
      idx = i;
      const p = points[i], px = x(ts[i]), py = y(p.price);
      for (const [n, a] of [[cross, {x1: px, x2: px}], [dot, {cx: px, cy: py}]]) {
        for (const [k, v] of Object.entries(a)) n.setAttribute(k, v);
        n.setAttribute("visibility", "visible");
      }
      tip.textContent = "";
      const strong = document.createElement("b");
      strong.textContent = euro(p.price);
      tip.append(strong, document.createElement("br"), dateTime(p.t) + (p.available ? "" : " · ausverkauft"));
      tip.hidden = false;
      const scale = box.clientWidth / W;
      let left = px * scale + 12;  // rechts neben dem Punkt, am Rand auf die linke Seite
      if (left + tip.offsetWidth > box.clientWidth) left = px * scale - tip.offsetWidth - 12;
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = Math.max(0, py * scale - tip.offsetHeight - 8) + "px";
    }
    function hide() {
      cross.setAttribute("visibility", "hidden");
      dot.setAttribute("visibility", "hidden");
      tip.hidden = true;
    }
    hit.addEventListener("pointermove", e => {
      const r = svg.getBoundingClientRect(), t = t0 + ((e.clientX - r.left) * W / r.width - m.l) / (W - m.l - m.r) * (t1 - t0);
      let best = 0;
      ts.forEach((v, i) => { if (Math.abs(v - t) < Math.abs(ts[best] - t)) best = i; });
      show(best);
    });
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", () => show(idx));
    hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", e => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        show(Math.min(last, Math.max(0, idx + (e.key === "ArrowRight" ? 1 : -1))));
      }
    });
  }

  function fill(points) {
    const stats = $("hist-stats"), table = $("hist-table");
    stats.textContent = "";
    table.textContent = "";
    if (!points.length) return;
    // Tiefstpreis wie beim Alarm nur aus Läufen, in denen der Artikel lieferbar war
    const buyable = points.filter(p => p.available);
    const lowPoint = buyable.reduce((a, p) => (!a || p.price < a.price ? p : a), null);
    const high = Math.max(...points.map(p => p.price));
    const cur = points[points.length - 1];
    for (const [label, value, note] of [
      ["Aktuell", euro(cur.price), cur.available ? day(cur.t) : "ausverkauft"],
      ["Tiefstpreis", lowPoint ? euro(lowPoint.price) : "–", lowPoint ? "lieferbar am " + day(lowPoint.t) : "nie lieferbar"],
      ["Höchstpreis", euro(high), ""],
      ["Läufe", String(points.length), "seit " + day(points[0].t)],
    ]) {
      const div = document.createElement("div");
      const b = document.createElement("b");
      b.textContent = value;
      const small = document.createElement("span");
      small.className = "muted";
      small.textContent = note;
      div.append(label + ": ", b, " ", small);
      stats.appendChild(div);
    }
    // Tabelle: nur Läufe, in denen sich Preis oder Verfügbarkeit geändert hat, neueste zuerst
    const head = table.insertRow();
    for (const h of ["Seit", "Preis", "Verfügbar"]) {
      const th = document.createElement("th");
      th.textContent = h;
      head.appendChild(th);
    }
    const changes = points.filter((p, i) => i === 0 || p.price !== points[i - 1].price || p.available !== points[i - 1].available);
    for (const p of changes.reverse()) {
      const row = table.insertRow();
      row.insertCell().textContent = dateTime(p.t);
      const c = row.insertCell();
      c.className = "num";
      c.textContent = euro(p.price);
      row.insertCell().textContent = p.available ? "ja" : "nein";
    }
  }

  async function open(btn) {
    const {shop, product, variant, size} = btn.dataset;
    $("hist-title").textContent = `${product} (${size})`;
    $("hist-sub").textContent = shop + (variant ? " · " + variant : "");
    $("hist-stats").textContent = "";
    $("hist-table").textContent = "";
    $("hist-chart").textContent = "Lade …";
    dialog.showModal();
    try {
      const r = await fetch("/api/verlauf?" + new URLSearchParams({shop, product, variant}));
      if (!r.ok) throw new Error(r.status);
      current = await r.json();
      fill(current);
      render(current);
    } catch (e) {
      current = null;
      $("hist-chart").textContent = "Verlauf konnte nicht geladen werden.";
    }
  }

  document.addEventListener("click", e => {
    const btn = e.target.closest("button.hist");
    if (btn) open(btn);
  });
  $("hist-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); });  // Klick auf den Hintergrund
  window.addEventListener("resize", () => { if (dialog.open && current) render(current); });
})();
