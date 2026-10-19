// Warenkorb-Rechner: findet die insgesamt günstigste Aufteilung gewählter Produkte auf einen oder mehrere Shops,
// inklusive Versandkosten (Gewichts-/Wertstaffeln, versandkostenfrei-Grenzen, Mindestbestellwert) und
// Gutscheinen, die für das ganze Sortiment gelten. Erwartet die globale Variable DATA
// ({offers, shipping, promos, groups}) und die Elemente mit den IDs cart-*.
(function () {
  const MAX_SHOPS_PER_ITEM = 10;  // je Produkt nur die günstigsten Shops durchsuchen
  const MAX_NODES = 2_000_000;    // Notbremse für sehr große Warenkörbe

  const $ = id => document.getElementById(id);
  const esc = v => v == null ? "–" : String(v).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const euro = v => v.toLocaleString("de-DE", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " €";

  function estimateWeight(size, unit) {
    if (size == null) return 0.5;
    if (unit === "Stück") return size * 0.022 + 0.05;
    if (unit === "l") return size * 1.1 + 0.05;
    return size * 1.05 + 0.05;
  }

  function shippingCost(shop, subtotal, weight) {
    const rule = DATA.shipping[shop] || {weight: [[31.5, 8]], free_from: null, estimated: true};  // wie DEFAULT_SHIPPING
    if (subtotal < (rule.min_order || 0)) return null;
    if (rule.free_from != null && subtotal >= rule.free_from) return 0;
    const byValue = [...(rule.by_value || [])].sort((a, b) => b[0] - a[0]);
    for (const [from, cost] of byValue) if (subtotal >= from) return cost;
    for (const [maxKg, cost] of rule.weight) if (weight <= maxKg) return cost;
    return rule.weight[rule.weight.length - 1][1];
  }

  function couponFor(shop, useCoupons) {
    if (!useCoupons) return null;
    const best = (DATA.promos[shop] || []).filter(p => p.sitewide && p.percent).sort((a, b) => b.percent - a.percent)[0];
    return best || null;
  }

  function optimize(items, useCoupons) {
    // Kandidaten: je Produkt und Shop das günstigste verfügbare Angebot
    const cands = items.map(item => {
      const byShop = new Map();
      for (const o of DATA.offers) {
        if (!o.available || o.group !== item.group || o.size_label !== item.size_label) continue;
        if (!byShop.has(o.shop) || o.price < byShop.get(o.shop).price) byShop.set(o.shop, o);
      }
      return [...byShop.values()].map(o => {
        const c = couponFor(o.shop, useCoupons);
        return {offer: o, unit: o.price * (1 - (c ? c.percent / 100 : 0))};
      }).sort((a, b) => a.unit - b.unit).slice(0, MAX_SHOPS_PER_ITEM);
    });
    const missing = items.filter((_, i) => !cands[i].length);
    if (missing.length) return {missing};

    // Teure Positionen zuerst, damit frühe Lösungen gut sind und die Schranke greift
    const order = items.map((_, i) => i).sort((a, b) => cands[b][0].unit * items[b].qty - cands[a][0].unit * items[a].qty);
    const restMin = new Array(order.length + 1).fill(0);
    for (let k = order.length - 1; k >= 0; k--) restMin[k] = restMin[k + 1] + cands[order[k]][0].unit * items[order[k]].qty;

    const baskets = new Map();  // shop -> {value, weight}
    const choice = new Array(items.length);
    let best = null, bestCost = Infinity, nodes = 0, truncated = false;

    function basketCost() {
      let total = 0;
      for (const [shop, b] of baskets) {
        const ship = shippingCost(shop, b.value, b.weight);
        if (ship == null) return Infinity;  // Mindestbestellwert nicht erreicht
        total += b.value + ship;
      }
      return total;
    }

    function dfs(k, itemsValue) {
      if (++nodes > MAX_NODES) { truncated = true; return; }
      if (itemsValue + restMin[k] >= bestCost) return;  // Versand ist nie negativ: untere Schranke
      if (k === order.length) {
        const cost = basketCost();
        if (cost < bestCost) { bestCost = cost; best = choice.slice(); }
        return;
      }
      const i = order[k], qty = items[i].qty;
      for (const c of cands[i]) {
        const shop = c.offer.shop;
        const b = baskets.get(shop) || {value: 0, weight: 0};
        const add = c.unit * qty, w = estimateWeight(c.offer.size, c.offer.unit) * qty;
        baskets.set(shop, {value: b.value + add, weight: b.weight + w});
        choice[i] = c;
        dfs(k + 1, itemsValue + add);
        if (b.value === 0) baskets.delete(shop); else baskets.set(shop, b);
      }
    }
    dfs(0, 0);
    if (!best) return {impossible: true};
    return {plan: describe(items, best, useCoupons), truncated};
  }

  function describe(items, chosen, useCoupons) {
    const shops = new Map();
    items.forEach((item, i) => {
      const c = chosen[i];
      const s = shops.get(c.offer.shop) || {shop: c.offer.shop, lines: [], gross: 0, value: 0, weight: 0};
      s.lines.push({item, offer: c.offer, qty: item.qty});
      s.gross += c.offer.price * item.qty;
      s.value += c.unit * item.qty;
      s.weight += estimateWeight(c.offer.size, c.offer.unit) * item.qty;
      shops.set(c.offer.shop, s);
    });
    let total = 0;
    for (const s of shops.values()) {
      s.coupon = couponFor(s.shop, useCoupons);
      s.shipping = shippingCost(s.shop, s.value, s.weight);
      s.total = s.value + s.shipping;
      total += s.total;
    }
    return {shops: [...shops.values()].sort((a, b) => b.total - a.total), total};
  }

  function bestSingleShop(items, useCoupons) {
    let best = null;
    for (const shop of new Set(DATA.offers.map(o => o.shop))) {
      const r = optimizeRestricted(items, useCoupons, shop);
      if (r && (!best || r.total < best.total)) best = r;
    }
    return best;
  }

  function optimizeRestricted(items, useCoupons, shop) {
    const chosen = [];
    for (const item of items) {
      const offers = DATA.offers.filter(o => o.shop === shop && o.available && o.group === item.group && o.size_label === item.size_label);
      if (!offers.length) return null;
      const o = offers.sort((a, b) => a.price - b.price)[0];
      const c = couponFor(shop, useCoupons);
      chosen.push({offer: o, unit: o.price * (1 - (c ? c.percent / 100 : 0))});
    }
    const plan = describe(items, chosen, useCoupons);
    return plan.shops.every(s => s.shipping != null) ? plan : null;
  }

  // --- Oberfläche ---------------------------------------------------------------

  const sizesFor = group => [...new Map(DATA.offers.filter(o => o.group === group && o.size != null)
    .sort((a, b) => (a.unit || "").localeCompare(b.unit || "") || a.size - b.size).map(o => [o.size_label, 1])).keys()];

  let cart = [];
  try { cart = JSON.parse(localStorage.getItem("biotabs-warenkorb") || "[]"); } catch (e) { cart = []; }
  // Beispiel-Warenkorb beim ersten Besuch
  if (!cart.length) cart = [{group: "Düngetabletten", size_label: "100 Stück", qty: 2}, {group: "Mycotrex", size_label: "500 g", qty: 1}, {group: "Bio PK 5-8", size_label: "1 l", qty: 1}];
  const save = () => { try { localStorage.setItem("biotabs-warenkorb", JSON.stringify(cart)); } catch (e) { /* ohne Speicher weiter */ } };

  function renderCart() {
    $("cart-items").innerHTML = cart.map((it, i) => {
      const sizes = sizesFor(it.group);
      if (!sizes.includes(it.size_label)) it.size_label = sizes[0];
      return `<div class="cart-row">
        <label class="sr" for="cart-g-${i}">Produkt</label>
        <select id="cart-g-${i}" data-i="${i}" data-f="group">${DATA.groups.map(g => `<option${g === it.group ? " selected" : ""}>${esc(g)}</option>`).join("")}</select>
        <label class="sr" for="cart-s-${i}">Größe</label>
        <select id="cart-s-${i}" data-i="${i}" data-f="size_label">${sizes.map(s => `<option${s === it.size_label ? " selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <label class="sr" for="cart-q-${i}">Menge</label>
        <input id="cart-q-${i}" type="number" min="1" max="20" value="${it.qty}" data-i="${i}" data-f="qty" aria-label="Menge">
        <button type="button" class="cart-del" data-del="${i}" aria-label="Entfernen">Entfernen</button></div>`;
    }).join("");
    calculate();
  }

  function planTable(plan) {
    return plan.shops.map(s => {
      const est = DATA.shipping[s.shop] && DATA.shipping[s.shop].estimated;
      const lines = s.lines.map(l => `<tr><td>${l.qty}×</td><td><a href="${esc(l.offer.url)}" target="_blank" rel="noopener">${esc(l.offer.product)}</a> <span class="muted">${esc(l.item.size_label)}</span></td><td class="num">${euro(l.offer.price * l.qty)}</td></tr>`).join("");
      const discount = s.gross - s.value > 0.005 ? `<tr><td></td><td>Gutschein <b>${esc(s.coupon.code || "")}</b> (−${s.coupon.percent} %)</td><td class="num">−${euro(s.gross - s.value)}</td></tr>` : "";
      const rule = DATA.shipping[s.shop] || {};
      const freeHint = rule.free_from != null && s.shipping > 0 ? ` <span class="muted">(frei ab ${euro(rule.free_from)}, fehlen ${euro(rule.free_from - s.value)})</span>` : "";
      return `<div class="cart-shop"><h4>${esc(s.shop)} <span class="num">${euro(s.total)}</span></h4><table>${lines}${discount}
        <tr><td></td><td>Versand${est ? ' <span class="est" title="Shop nennt keine Beträge, Wert geschätzt">geschätzt</span>' : ""}${freeHint}</td><td class="num">${s.shipping ? euro(s.shipping) : "frei"}</td></tr></table></div>`;
    }).join("");
  }

  function calculate() {
    const useCoupons = $("cart-coupons").checked;
    const items = cart.filter(it => it.size_label && it.qty > 0);
    if (!items.length) { $("cart-result").innerHTML = '<p class="muted">Füge oben Produkte hinzu.</p>'; return; }
    const r = optimize(items, useCoupons);
    if (r.missing) {
      $("cart-result").innerHTML = `<p>Gerade nirgends verfügbar: ${r.missing.map(m => esc(m.group + " " + m.size_label)).join(", ")}.</p>`;
      return;
    }
    if (r.impossible) { $("cart-result").innerHTML = "<p>Keine Kombination erreicht die Mindestbestellwerte.</p>"; return; }
    const single = bestSingleShop(items, useCoupons);
    const sum = items.reduce((a, it) => a + it.qty, 0);
    let compare;
    if (!single) compare = "Kein einzelner Shop hat alle Produkte vorrätig.";
    else if (single.total - r.plan.total < 0.005) compare = `Alles bei einem Shop ist hier am günstigsten.`;
    else compare = `Günstigster Einzelshop: ${esc(single.shops[0].shop)} für ${euro(single.total)}. Die Aufteilung spart <b>${euro(single.total - r.plan.total)}</b>, trotz ${r.plan.shops.length}× Versand.`;
    $("cart-result").innerHTML = `<div class="cart-total"><span>Günstigste Option für ${sum} Artikel</span><strong>${euro(r.plan.total)}</strong>
      <span class="muted">${r.plan.shops.length === 1 ? "bei einem Shop" : `aufgeteilt auf ${r.plan.shops.length} Shops`} · inkl. Versand</span></div>
      <p>${compare}</p>${planTable(r.plan)}${r.truncated ? '<p class="muted">Sehr großer Warenkorb: Suche nach 2 Mio. Schritten beendet, Ergebnis ist die beste gefundene Lösung.</p>' : ""}`;
  }

  document.addEventListener("change", e => {
    const t = e.target;
    if (t.id === "cart-coupons") return calculate();
    if (t.dataset.i == null) return;
    const it = cart[+t.dataset.i];
    if (t.dataset.f === "qty") it.qty = Math.max(1, Math.min(20, parseInt(t.value, 10) || 1));
    else it[t.dataset.f] = t.value;
    if (t.dataset.f === "group") it.size_label = sizesFor(it.group)[0];
    save(); renderCart();
  });
  document.addEventListener("click", e => {
    const del = e.target.closest("[data-del]");
    if (del) { cart.splice(+del.dataset.del, 1); save(); renderCart(); }
    if (e.target.id === "cart-add") { cart.push({group: DATA.groups[0], size_label: sizesFor(DATA.groups[0])[0], qty: 1}); save(); renderCart(); }
  });

  window.biotabsWarenkorb = {optimize, shippingCost, estimateWeight};
  renderCart();
})();
