/* CreditWise — interface (commerçant / institution financière). Vanilla JS + Chart.js local. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = () => $("#app");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const money = (v) => (v === null || v === undefined ? "—" : nf0.format(v) + " FCFA");
const mfcfa = (v) => (v === null || v === undefined ? "—" : (v / 1e6).toLocaleString("fr-FR", { maximumFractionDigits: 2 }) + " M");
const pct = (v, d = 1) => (v === null || v === undefined ? "—" : v.toLocaleString("fr-FR", { maximumFractionDigits: d, minimumFractionDigits: d }) + " %");
const signed = (v) => (v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + pct(v));
const STATUS = { declare: "déclaré", extrait: "extrait auto.", verifie: "vérifié", estime: "estimé" };
const SEV = { elevee: "Élevée", attention: "Attention", info: "Info" };
const KIND = { etat_financier: "États financiers (XLSX/CSV)", etat_financier_long: "États financiers (format long)", etat_financier_pdf: "États financiers PDF",
  balance_generale: "Balance générale", grand_livre: "Grand livre / journal", dossier_creditwise: "Dossier CreditWise signé", inconnu: "Non reconnu" };
let ME = null;
let SEQ = 0; // numéro de navigation : une réponse arrivée après un changement de page est ignorée
const charts = [];

function fmtRatio(r) {
  if (r.value === null) return `<span class="nc">Non calculable</span>`;
  if (r.unit === "FCFA") return money(r.value);
  if (r.unit === "%") return pct(r.value);
  if (r.unit === "jours") return nf0.format(r.value) + " j";
  return r.value.toLocaleString("fr-FR", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 3500); }

async function api(path, opts = {}) {
  const seq = SEQ;
  const o = { credentials: "same-origin", ...opts };
  if (o.json) { o.body = JSON.stringify(o.json); o.headers = { "Content-Type": "application/json" }; o.method = o.method || "POST"; delete o.json; }
  const r = await fetch(path, o);
  if (seq !== SEQ) throw Object.assign(new Error("navigation"), { stale: true });
  if (r.status === 401 && !path.endsWith("/login")) { ME = null; location.hash = "#/login"; throw new Error("Connexion requise"); }
  if (!r.ok) { let d; try { d = (await r.json()).detail; } catch { d = r.statusText; } throw new Error(typeof d === "string" ? d : JSON.stringify(d)); }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r;
}
async function download(path, fallbackName) {
  try {
    const r = await api(path);
    const blob = await r.blob();
    const cd = r.headers.get("content-disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: m ? decodeURIComponent(m[1]) : fallbackName });
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (e) { toast(e.message); }
}
function destroyCharts() { while (charts.length) charts.pop().destroy(); }

// ------------------------------------------------------------------ routeur
async function route() {
  SEQ++;
  destroyCharts();
  const h = location.hash.slice(2).split("/");
  if (!ME) { try { ME = await api("/api/me"); } catch (e) { if (e.stale) return; ME = null; } }
  renderTop(h);
  if (!ME || h[0] === "login" || h[0] === "") { if (ME && h[0] !== "login") return (location.hash = ME.role === "merchant" ? "#/m/tableau" : "#/i/dossiers"); return viewLogin(); }
  try {
    if (ME.role === "merchant") {
      const cid = ME.companies[0]?.id;
      if (h[1] === "documents") return await viewDocuments(cid);
      if (h[1] === "donnees") return await viewData(cid);
      if (h[1] === "partage") return await viewSharing(cid);
      return await viewMerchantDashboard(cid);
    }
    if (h[1] === "dossier") return await viewDossier(+h[2], h[3] ? +h[3] : null);
    if (h[1] === "televerser") return await viewInstitutionUpload(h[2] ? +h[2] : null);
    if (h[1] === "modele") return await viewModel();
    return await viewDossiers();
  } catch (e) { if (!e.stale) app().innerHTML = `<div class="card notice warn">${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", route);
window.addEventListener("load", route);

function renderTop(h) {
  const nav = $("#nav"), who = $("#who");
  if (!ME) { nav.innerHTML = ""; who.innerHTML = ""; return; }
  const links = ME.role === "merchant"
    ? [["tableau", "Tableau de bord"], ["documents", "Documents"], ["donnees", "Données"], ["partage", "Partage et accès"]].map(([k, l]) => [`#/m/${k}`, l, h[1] === k || (!h[1] && k === "tableau")])
    : [["dossiers", "Dossiers de crédit"], ["televerser", "Téléverser un dossier"], ["modele", "Modèle et méthode"]].map(([k, l]) => [`#/i/${k}`, l, h[1] === k || (k === "dossiers" && (h[1] === "dossier" || !h[1]))]);
  nav.innerHTML = links.map(([href, l, a]) => `<a href="${href}" class="${a ? "active" : ""}">${l}</a>`).join("");
  who.innerHTML = `<span>${esc(ME.display_name)}${ME.organisation ? " · " + esc(ME.organisation) : ""} <span class="chip neutral">${ME.role === "merchant" ? "Commerçant" : "Institution"}</span></span>
    <button class="btn sm" id="logout">Déconnexion</button>`;
  $("#logout").onclick = async () => { await api("/api/logout", { method: "POST" }); ME = null; location.hash = "#/login"; };
}

// ------------------------------------------------------------------ connexion
function viewLogin() {
  app().innerHTML = `
  <div class="login-wrap">
    <div class="hero">
      <h1>Mieux connaître un commerçant avant de lui prêter</h1>
      <p>CreditWise rassemble les données financières d'un commerçant, calcule les ratios, suit l'évolution mois par mois, signale les anomalies et prépare une synthèse explicable pour l'analyste crédit.</p>
    </div>
    <div class="grid g2">
      <div class="card">
        <h2>Connexion</h2>
        <form id="login">
          <div class="field"><label>Identifiant</label><input name="username" autocomplete="username" required></div>
          <div class="field"><label>Mot de passe</label><input name="password" type="password" autocomplete="current-password" required></div>
          <button class="btn primary" style="width:100%;justify-content:center">Se connecter</button>
        </form>
        <details style="margin-top:16px"><summary>Créer un compte</summary>
          <form id="register" style="margin-top:12px">
            <div class="row"><div class="field"><label>Profil</label><select name="role"><option value="merchant">Commerçant</option><option value="institution">Institution financière</option></select></div>
            <div class="field"><label>Nom affiché</label><input name="display_name" required></div></div>
            <div class="row"><div class="field"><label>Identifiant</label><input name="username" required minlength="3"></div>
            <div class="field"><label>Mot de passe</label><input name="password" type="password" required minlength="4"></div></div>
            <div class="row"><div class="field"><label>Commerce / organisation</label><input name="company_name"></div>
            <div class="field"><label>Ville</label><input name="city"></div></div>
            <button class="btn">Créer le compte</button>
          </form>
        </details>
      </div>
      <div class="card demo-accounts">
        <h2>Comptes de démonstration</h2>
        <p class="muted small">Entreprises et personnes fictives. Mot de passe : <b>demo</b>.</p>
        ${[["analyste", "Institution financière", "Microfinance Démo — analyste crédit"],
           ["akwaba", "Commerçant A", "Boutique de vêtements — activité stable"],
           ["solidite", "Commerçant B", "Quincaillerie — ventes en baisse"],
           ["bonprix", "Commerçant C", "Alimentation — données avec anomalies"],
           ["nouveau", "Nouveau commerçant", "Aucune donnée : import en direct"]]
          .map(([u, t, d]) => `<button class="btn" data-demo="${u}"><span><b>${t}</b><br><span class="muted small">${d}</span></span><span class="muted">${u} →</span></button>`).join("")}
      </div>
    </div>
  </div>`;
  const go = async (username, password) => {
    try { const r = await api("/api/login", { json: { username, password } }); ME = await api("/api/me"); location.hash = r.role === "merchant" ? "#/m/tableau" : "#/i/dossiers"; }
    catch (e) { toast(e.message); }
  };
  $("#login").onsubmit = (e) => { e.preventDefault(); const f = new FormData(e.target); go(f.get("username"), f.get("password")); };
  $$("[data-demo]").forEach((b) => (b.onclick = () => go(b.dataset.demo, "demo")));
  $("#register").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    if (f.role === "institution") { f.organisation = f.company_name; delete f.company_name; }
    try { await api("/api/register", { json: f }); ME = await api("/api/me"); location.hash = ME.role === "merchant" ? "#/m/documents" : "#/i/dossiers"; }
    catch (err) { toast(err.message); }
  };
}

// ------------------------------------------------------------------ graphiques
function monthlyChart(canvas, a) {
  const ms = a.monthly;
  const c = new Chart(canvas, {
    data: {
      labels: ms.map((m) => m.month),
      datasets: [
        { type: "bar", label: "Chiffre d'affaires", data: ms.map((m) => m.ventes), backgroundColor: ms.map((m) => (m.has_pnl ? "#2e6da4" : "#e3e8ef")), order: 3 },
        { type: "line", label: "Résultat net", data: ms.map((m) => m.resultat_net), borderColor: "#e8833a", backgroundColor: "#e8833a", tension: 0.25, pointRadius: 2, order: 1 },
        { type: "line", label: "Trésorerie nette (caisse + banque – découverts)", data: ms.map((m) => m.tresorerie_nette_constatee), borderColor: "#1f9d7a", backgroundColor: "#1f9d7a", borderDash: [5, 4], pointRadius: 2, order: 2 },
      ],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: { label: (x) => `${x.dataset.label} : ${money(x.parsed.y)}`, afterBody: (items) => { const m = ms[items[0].dataIndex]; return [m.var_mom !== null ? `Vs mois précédent : ${signed(m.var_mom)}` : "", m.var_yoy !== null ? `Vs même mois N-1 : ${signed(m.var_yoy)}` : ""].filter(Boolean); } } } },
      scales: { y: { ticks: { callback: (v) => mfcfa(v) } }, x: { ticks: { font: { size: 10 } } } },
    },
  });
  charts.push(c);
}

function scoreRing(score, capped = false) {
  const s = score ?? 0, r = 64, C = 2 * Math.PI * r;
  const col = score === null ? "#98a2b3" : capped ? "#d08a19" : s >= 80 ? "#1f9d7a" : s >= 60 ? "#d08a19" : "#b42318";
  return `<div class="score-ring"><svg width="150" height="150"><circle cx="75" cy="75" r="${r}" stroke="#eef1f5" stroke-width="12" fill="none"/>
    <circle cx="75" cy="75" r="${r}" stroke="${col}" stroke-width="12" fill="none" stroke-linecap="round" stroke-dasharray="${(C * s) / 100} ${C}"/></svg>
    <div class="center"><b style="color:${col}">${score === null ? "—" : Math.round(s)}</b><span class="muted small">/ 100</span></div></div>`;
}
const noteColor = (n) => (n === null ? "#98a2b3" : n >= 75 ? "#1f9d7a" : n >= 50 ? "#d08a19" : "#b42318");

function alertsHtml(alerts, empty = "Aucune anomalie détectée par les contrôles programmés.") {
  if (!alerts.length) return `<div class="notice ok">${empty}</div>`;
  return alerts.map((x) => `<div class="alert-item"><div><span class="chip ${x.severity}">${SEV[x.severity]}</span></div><div>
    <div class="title">${esc(x.title)}</div><div>${esc(x.reason)}</div>
    ${x.explanation ? `<div class="expl">${esc(x.explanation)}</div>` : ""}<div class="method">Méthode : ${esc(x.method)}${x.period ? " · période " + esc(x.period) : ""}</div></div></div>`).join("");
}

function kpis(a) {
  const R = Object.fromEntries(a.ratios.map((r) => [r.key, r]));
  const last = a.monthly.filter((m) => m.has_pnl).slice(-1)[0];
  return `<div class="grid g4">
    <div class="card kpi"><div class="label">CA 12 derniers mois</div><div class="value">${mfcfa(a.ttm.ventes)}</div><div class="sub">${a.coverage.annualised ? "annualisé (moins de 12 mois)" : "FCFA, " + a.coverage.ttm_months[0] + " → " + a.coverage.ttm_months.slice(-1)[0]}</div></div>
    <div class="card kpi"><div class="label">Évolution trimestrielle</div><div class="value">${R.evol_ca_trimestrielle.value === null ? "—" : signed(R.evol_ca_trimestrielle.value)}</div><div class="sub">dernier trimestre complet vs précédent</div></div>
    <div class="card kpi"><div class="label">Marge nette</div><div class="value">${R.marge_nette.value === null ? "—" : pct(R.marge_nette.value)}</div><div class="sub">résultat net / CA</div></div>
    <div class="card kpi"><div class="label">Trésorerie nette</div><div class="value">${mfcfa(last ? a.monthly.filter((m) => m.tresorerie_nette_constatee !== null).slice(-1)[0]?.tresorerie_nette_constatee : null)}</div><div class="sub">caisse + banque – découverts, ${esc(a.coverage.last_balance || "—")}</div></div>
  </div>`;
}

// ------------------------------------------------------------------ COMMERÇANT
async function viewMerchantDashboard(cid) {
  const a = await api(`/api/companies/${cid}/analysis`);
  if (a.empty) {
    app().innerHTML = `<div class="page-head"><div><h1>${esc(ME.companies[0].name)}</h1><p class="muted">Aucune donnée financière pour le moment.</p></div></div>
    <div class="card"><h2>Commencez par importer vos documents</h2><p>Deux possibilités :</p>
    <ul><li><b>Vous avez un logiciel comptable</b> : exportez vos états financiers, votre balance ou votre grand livre (XLSX, CSV, PDF).</li>
    <li><b>Vous n'avez pas de logiciel</b> : importez votre journal de caisse / mobile money ou les états préparés par votre comptable.</li></ul>
    <a class="btn primary" href="#/m/documents">Importer des documents</a></div>`;
    return;
  }
  const extr = a.coverage.status_counts.extrait || 0;
  app().innerHTML = `
  <div class="page-head"><div><h1>${esc(a.company.name)}</h1><p class="muted">${esc(a.company.sector || "")} · ${esc(a.company.city || "")} · données de ${a.coverage.first_month} à ${a.coverage.last_month}</p></div>
  <div class="row"><a class="btn" href="#/m/documents">Importer</a><a class="btn primary" href="#/m/partage">Partager mon dossier</a></div></div>
  ${extr ? `<div class="notice warn" style="margin-bottom:16px">${extr} valeur(s) ont été <b>extraites automatiquement</b> d'un PDF et ne sont pas encore vérifiées. <a href="#/m/donnees">Les vérifier</a></div>` : ""}
  ${kpis(a)}
  <div class="grid g3" style="margin-top:16px">
    <div class="card span2"><h2>Évolution mensuelle</h2><div class="chart-box"><canvas id="ch"></canvas></div></div>
    <div class="card"><h2>Points à vérifier avant transmission</h2><p class="muted small">Ces signaux seront visibles par l'institution financière. Expliquez-les ou corrigez vos données.</p>
      <div style="max-height:300px;overflow:auto">${alertsHtml(a.alerts.filter((x) => x.severity !== "info"), "Aucun point bloquant détecté.")}</div></div>
  </div>
  <div class="card" style="margin-top:16px"><h2>Mes indicateurs</h2>${ratiosTable(a.ratios.filter((r) => !r.key.startsWith("dscr")))}</div>`;
  monthlyChart($("#ch"), a);
}

async function viewDocuments(cid, lastResults = "") {
  const [docs, demo] = await Promise.all([api(`/api/companies/${cid}/documents`), api("/api/demo-files")]);
  app().innerHTML = `
  <div class="page-head"><div><h1>Documents</h1><p class="muted">PDF, XLSX ou CSV : états financiers, balance générale, grand livre, journal de caisse ou dossier CreditWise.</p></div></div>
  <div class="grid g3">
    <div class="span2 stack">
      <label class="dropzone" id="dz"><input type="file" id="file" multiple accept=".pdf,.xlsx,.xls,.csv" hidden>
        <div style="font-size:28px">⇪</div><b>Déposez vos fichiers ici</b><div class="muted small">ou cliquez pour choisir — plusieurs fichiers possibles</div></label>
      <div id="results">${lastResults}</div>
      <div class="card"><h2>Documents importés (${docs.length})</h2>${docs.length ? `<div class="table-wrap"><table><thead><tr><th>Fichier</th><th>Type reconnu</th><th class="num">Valeurs</th><th class="num">Opérations</th><th>Importé le</th><th></th></tr></thead><tbody>
      ${docs.map((d) => `<tr><td>${esc(d.filename)}${d.warnings.length ? `<div class="muted small">${d.warnings.map(esc).join("<br>")}</div>` : ""}</td><td>${KIND[d.kind] || esc(d.kind)}</td>
      <td class="num">${d.n_values}</td><td class="num">${d.n_transactions}</td><td class="small">${esc(d.uploaded_at.slice(0, 16))}</td>
      <td><button class="btn sm danger" data-del="${d.id}">Supprimer</button></td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">Aucun document.</p>`}</div>
    </div>
    <div class="card"><h2>Fichiers d'exemple</h2><p class="muted small">Jeu de démonstration (commerçants fictifs). Téléchargez-les puis déposez-les à gauche.</p>
      ${["A", "B", "C"].map((k) => `<h3 style="margin-top:12px">Commerçant ${k}</h3>` + demo.filter((f) => f.company === k).map((f) => `<div><a href="${f.url}" download>${esc(f.name)}</a></div>`).join("")).join("")}
      <h3 style="margin-top:16px">Formats reconnus</h3>
      <ul class="small muted" style="padding-left:18px">
        <li>Tableau « poste × mois » (export logiciel)</li><li>Format long : periode_debut, periode_fin, poste, montant</li>
        <li>Balance : periode, compte, intitule, debit, credit</li><li>Grand livre : date, reference, tiers, libelle, compte, debit, credit</li>
        <li>PDF texte avec tableaux (lecture automatique, à vérifier)</li><li>Photos de reçus : prévu après le prototype (OCR)</li></ul>
    </div>
  </div>`;
  const dz = $("#dz"), input = $("#file");
  const send = async (files) => {
    if (!files.length) return;
    const fd = new FormData(); [...files].forEach((f) => fd.append("files", f));
    $("#results").innerHTML = `<div class="card">Analyse de ${files.length} fichier(s)…</div>`;
    try {
      const r = await api(`/api/companies/${cid}/documents`, { method: "POST", body: fd });
      const html = r.results.map((x) => `<div class="card" style="margin-bottom:12px"><div class="row" style="justify-content:space-between;align-items:center">
        <div><b>${esc(x.filename)}</b> <span class="chip neutral">${KIND[x.kind] || esc(x.kind)}</span></div>
        <div>${Object.entries(x.status_summary || {}).map(([s, n]) => `<span class="chip ${s}">${n} ${STATUS[s]}</span>`).join(" ")}</div></div>
        <p>${x.n_values} valeur(s) financière(s)${x.n_transactions ? `, ${x.n_transactions} opération(s)` : ""}${x.periods ? ` · période ${x.periods[0]} → ${x.periods[1]}` : ""}.</p>
        ${x.unmatched?.length ? `<div class="notice warn">Postes non reconnus (non additionnés) : ${x.unmatched.map(esc).join(", ")}</div>` : ""}
        ${(x.warnings || []).map((w) => `<div class="notice ${/authentique/.test(w) ? "ok" : "warn"}" style="margin-top:6px">${esc(w)}</div>`).join("")}
        ${x.status_summary?.extrait ? `<p class="small"><a href="#/m/donnees">Vérifier les valeurs extraites →</a></p>` : ""}</div>`).join("");
      toast("Import terminé"); await viewDocuments(cid, html);
    } catch (e) { $("#results").innerHTML = `<div class="notice warn">${esc(e.message)}</div>`; }
  };
  input.onchange = () => send(input.files);
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("over"); };
  dz.ondragleave = () => dz.classList.remove("over");
  dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("over"); send(e.dataTransfer.files); };
  $$("[data-del]").forEach((b) => (b.onclick = async () => { if (!confirm("Supprimer ce document et ses données ?")) return; await api(`/api/documents/${b.dataset.del}`, { method: "DELETE" }); viewDocuments(cid); }));
}

async function viewData(cid) {
  const vals = await api(`/api/companies/${cid}/values`);
  const docs = [...new Map(vals.map((v) => [v.document_id, v.source_name])).entries()];
  const counts = vals.reduce((o, v) => ((o[v.status] = (o[v.status] || 0) + 1), o), {});
  let filter = counts.extrait ? "extrait" : "";
  app().innerHTML = `
  <div class="page-head"><div><h1>Données financières normalisées</h1><p class="muted">Chaque valeur conserve sa source, sa période et son niveau de fiabilité. Une valeur extraite automatiquement doit être vérifiée.</p></div></div>
  <div class="card">
    <div class="row" style="margin-bottom:12px">
      <div class="field"><label>Statut</label><select id="st"><option value="">Tous (${vals.length})</option>${Object.entries(counts).map(([s, n]) => `<option value="${s}" ${s === filter ? "selected" : ""}>${STATUS[s]} (${n})</option>`).join("")}</select></div>
      <div class="field"><label>Document</label><select id="doc"><option value="">Tous</option>${docs.map(([id, n]) => `<option value="${id}">${esc(n)}</option>`).join("")}</select></div>
      <div class="field"><label>Recherche (poste ou mois)</label><input id="q" placeholder="ex. trésorerie, 2026-03"></div>
      <button class="btn teal" id="verifyDoc">Valider les valeurs extraites affichées</button>
    </div>
    <div class="table-wrap"><table><thead><tr><th>Période</th><th>Poste</th><th class="num">Montant</th><th>Statut</th><th>Source</th><th>Libellé d'origine</th><th></th></tr></thead><tbody id="tb"></tbody></table></div>
    <p class="muted small" id="cnt"></p>
  </div>`;
  const draw = () => {
    const st = $("#st").value, dId = $("#doc").value, q = $("#q").value.toLowerCase();
    const rows = vals.filter((v) => (!st || v.status === st) && (!dId || String(v.document_id) === dId) && (!q || (v.item_label + v.period_end).toLowerCase().includes(q)));
    $("#tb").innerHTML = rows.slice(0, 400).map((v) => `<tr><td class="small">${v.period_start.slice(0, 7)}${v.period_start.slice(0, 7) !== v.period_end.slice(0, 7) ? " → " + v.period_end.slice(0, 7) : ""}</td>
      <td>${esc(v.item_label)}</td><td class="num">${money(v.amount)}</td><td><span class="chip ${v.status}">${STATUS[v.status]}</span>${v.confidence !== null && v.confidence < 1 ? `<div class="small muted">confiance ${Math.round(v.confidence * 100)} %</div>` : ""}</td>
      <td class="small">${esc(v.source_name)}</td><td class="small muted">${esc(v.source_label || "")}${v.comment ? `<div>${esc(v.comment)}</div>` : ""}</td>
      <td><button class="btn sm" data-edit="${v.id}" data-amount="${v.amount}">Corriger</button></td></tr>`).join("");
    $("#cnt").textContent = `${rows.length} valeur(s)${rows.length > 400 ? " — 400 premières affichées" : ""}`;
    $$("[data-edit]").forEach((b) => (b.onclick = async () => {
      const nv = prompt("Montant corrigé (FCFA) :", b.dataset.amount); if (nv === null) return;
      const amount = parseFloat(nv.replace(/\s/g, "").replace(",", ".")); if (isNaN(amount)) return toast("Montant invalide");
      const comment = prompt("Motif de la correction (facultatif) :") || null;
      await api(`/api/values/${b.dataset.edit}`, { method: "PATCH", json: { amount, comment } }); toast("Valeur corrigée et marquée vérifiée"); viewData(cid);
    }));
    $("#verifyDoc").onclick = async () => {
      const ids = rows.filter((v) => v.status === "extrait").map((v) => v.id);
      if (!ids.length) return toast("Aucune valeur extraite à valider dans cette sélection");
      if (!confirm(`Confirmer que ces ${ids.length} valeurs correspondent à vos documents ?`)) return;
      const r = await api(`/api/companies/${cid}/values/verify`, { json: { ids } }); toast(`${r.verified} valeur(s) vérifiée(s)`); viewData(cid);
    };
  };
  ["st", "doc", "q"].forEach((id) => ($("#" + id).oninput = draw));
  draw();
}

async function viewSharing(cid) {
  const [inst, shares, log] = await Promise.all([api("/api/institutions"), api(`/api/companies/${cid}/shares`), api(`/api/companies/${cid}/access-log`)]);
  const active = shares.filter((s) => !s.revoked_at);
  const ACTIONS = { connexion: "Connexion", import_document: "Import de document", consultation_analyse: "Consultation de l'analyse", autorisation_partage: "Autorisation de partage",
    retrait_partage: "Retrait du partage", telechargement_rapport: "Téléchargement du rapport", decision_credit: "Décision de crédit", export_dossier_pdf: "Export du dossier PDF",
    creation_demande_credit: "Création d'une demande de crédit", verification_valeurs: "Vérification de valeurs", correction_valeur: "Correction d'une valeur", suppression_document: "Suppression de document" };
  app().innerHTML = `
  <div class="page-head"><div><h1>Partage et accès</h1><p class="muted">Vous décidez quelle institution peut consulter votre dossier. Chaque accès est tracé.</p></div></div>
  <div class="grid g2">
    <div class="card"><h2>Autoriser une institution financière</h2>
      ${inst.map((i) => { const s = active.find((x) => x.institution_user_id === i.id);
        return `<div class="row" style="justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)"><div><b>${esc(i.organisation || i.display_name)}</b><div class="small muted">${esc(i.display_name)}</div></div>
        ${s ? `<div><span class="chip good">Autorisée depuis le ${esc(s.granted_at.slice(0, 10))}</span> <button class="btn sm danger" data-revoke="${s.id}">Retirer</button></div>` : `<button class="btn sm primary" data-share="${i.id}">Autoriser</button>`}</div>`; }).join("")}
      <h2 style="margin-top:24px">Dossier financier PDF sécurisé</h2>
      <p class="small muted">Synthèse lisible + données normalisées <b>signées</b> en pièce jointe. L'institution peut le téléverser dans CreditWise : toute modification invalide la signature.</p>
      <div class="row"><div class="field"><label>Mot de passe d'ouverture (facultatif, AES-256)</label><input id="pw" type="password" placeholder="à communiquer séparément"></div>
      <button class="btn primary" id="exp">Générer le PDF</button></div>
    </div>
    <div class="card"><h2>Journal des accès à mon dossier</h2><div class="table-wrap" style="max-height:440px"><table><thead><tr><th>Date</th><th>Qui</th><th>Action</th></tr></thead><tbody>
      ${log.map((l) => `<tr><td class="small">${esc(l.at.slice(0, 16))}</td><td class="small">${esc(l.role === "institution" ? l.organisation || l.display_name : "Vous")}</td><td class="small">${esc(ACTIONS[l.action] || l.action)}${l.detail ? ` <span class="muted">— ${esc(l.detail)}</span>` : ""}</td></tr>`).join("")}
    </tbody></table></div></div>
  </div>`;
  $$("[data-share]").forEach((b) => (b.onclick = async () => { await api(`/api/companies/${cid}/shares`, { json: { institution_id: +b.dataset.share } }); toast("Accès autorisé"); viewSharing(cid); }));
  $$("[data-revoke]").forEach((b) => (b.onclick = async () => { if (!confirm("Retirer l'accès de cette institution ?")) return; await api(`/api/shares/${b.dataset.revoke}`, { method: "DELETE" }); toast("Accès retiré"); viewSharing(cid); }));
  $("#exp").onclick = () => download(`/api/companies/${cid}/dossier.pdf${$("#pw").value ? "?password=" + encodeURIComponent($("#pw").value) : ""}`, "Dossier_CreditWise.pdf").then(() => setTimeout(() => viewSharing(cid), 500));
}

// ------------------------------------------------------------------ INSTITUTION
async function viewDossiers() {
  const ds = await api("/api/dossiers");
  app().innerHTML = `<div class="page-head"><div><h1>Dossiers de crédit</h1><p class="muted">Dossiers partagés par les commerçants ou téléversés par votre institution.</p></div>
    <a class="btn primary" href="#/i/televerser">Téléverser un dossier reçu</a></div>
    <div class="grid g3" id="cards">${ds.map((d) => `<div class="card dossier-card" data-c="${d.id}" data-r="${d.requests[0]?.id || ""}">
      <div class="row" style="justify-content:space-between;align-items:flex-start"><div><h2 style="margin:0">${esc(d.name)}</h2><div class="muted small">${esc(d.sector || "")} · ${esc(d.city || "")}</div></div>
      <span class="chip neutral">${d.access === "partage" ? "Partagé par le commerçant" : "Téléversé"}</span></div>
      <div class="score-slot" style="margin:14px 0;min-height:44px"><span class="muted small">Calcul…</span></div>
      ${d.requests.length ? d.requests.map((q) => `<div class="small"><b>${money(q.amount)}</b> · ${q.duration_months} mois · <span class="chip ${q.decision ? (q.decision.decision.startsWith("Accord") ? "good" : q.decision.decision.startsWith("Refus") ? "bad" : "warn") : "neutral"}">${esc(q.decision ? q.decision.decision : "En analyse")}</span></div>`).join("") : `<div class="small muted">Aucune demande de crédit</div>`}
    </div>`).join("") || `<div class="card muted">Aucun dossier partagé pour le moment.</div>`}</div>`;
  $$(".dossier-card").forEach((el) => (el.onclick = () => (location.hash = `#/i/dossier/${el.dataset.c}${el.dataset.r ? "/" + el.dataset.r : ""}`)));
  for (const el of $$(".dossier-card")) {
    api(`/api/companies/${el.dataset.c}/analysis${el.dataset.r ? "?request_id=" + el.dataset.r : ""}`).then((a) => {
      const s = a.score || {}; const nHigh = (a.alerts || []).filter((x) => x.severity === "elevee").length;
      $(".score-slot", el).innerHTML = a.empty ? `<span class="muted small">Aucune donnée</span>` :
        `<div class="row" style="align-items:center;gap:10px"><b style="font-size:26px;color:${s.capped ? "#d08a19" : noteColor(s.score)}">${Math.round(s.score)}</b><span class="small">${esc(s.category)}<br><span class="muted">PD indicative ${a.pd.available ? pct(a.pd.pd * 100) : "n.d."} · ${nHigh} alerte(s) élevée(s)</span></span></div>`;
    }).catch(() => {});
  }
}

function ratiosTable(ratios) {
  const groups = [["Activité", ["evol_ca_mensuelle", "evol_ca_trimestrielle", "evol_ca_annuelle"]],
    ["Rentabilité", ["taux_marge_commerciale", "marge_nette", "resultat_exploitation", "marge_exploitation", "roa"]],
    ["Liquidité et trésorerie", ["liquidite_generale", "liquidite_immediate", "fonds_roulement", "bfr", "tresorerie_nette"]],
    ["Endettement et remboursement", ["dettes_capitaux_propres", "poids_dettes", "dscr_actuel", "dscr_avec_credit"]],
    ["Cycle d'exploitation", ["delai_stocks", "delai_clients", "delai_fournisseurs"]]];
  const R = Object.fromEntries(ratios.map((r) => [r.key, r]));
  return `<div class="table-wrap" style="max-height:none"><table><thead><tr><th>Indicateur</th><th class="num">Valeur</th><th>Formule</th><th>Lecture</th></tr></thead><tbody>
  ${groups.map(([g, ks]) => { const rows = ks.filter((k) => R[k]); return rows.length ? `<tr><td colspan="4" style="background:#f5f7fa;font-weight:700;color:var(--navy)">${g}</td></tr>` + rows.map((k) => { const r = R[k];
    return `<tr><td>${esc(r.label)}</td><td class="num"><b>${fmtRatio(r)}</b></td><td class="small muted">${esc(r.formula)}</td><td class="small">${r.value === null ? `<span class="nc">${esc(r.reason)}</span>` : esc(r.interpretation)}</td></tr>`; }).join("") : ""; }).join("")}
  </tbody></table></div>`;
}

async function viewDossier(cid, rid, sim = null) {
  const ds = await api("/api/dossiers");
  const d = ds.find((x) => x.id === cid);
  if (!d) throw new Error("Dossier non partagé avec votre institution (ou accès retiré par le commerçant).");
  const req = d.requests.find((q) => q.id === rid) || null;
  const params = sim ? `?amount=${sim.amount}&duration_months=${sim.duration_months}&annual_rate=${sim.annual_rate}` : rid ? `?request_id=${rid}` : "";
  const a = await api(`/api/companies/${cid}/analysis${params}`);
  if (a.empty) { app().innerHTML = `<div class="card"><h1>${esc(d.name)}</h1><p class="muted">Aucune donnée exploitable dans ce dossier.</p>${d.access === "televerse" ? `<a class="btn" href="#/i/televerser/${cid}">Téléverser des fichiers</a>` : ""}</div>`; return; }
  const s = a.score, p = a.pd, cr = a.credit, R = Object.fromEntries(a.ratios.map((r) => [r.key, r]));
  const cur = sim || req;
  app().innerHTML = `
  <div class="page-head"><div><a href="#/i/dossiers" class="small">← Dossiers</a><h1>${esc(a.company.name)}</h1>
    <p class="muted">${esc(a.company.sector || "")} · ${esc(a.company.city || "")} · ${d.access === "partage" ? "partagé par le commerçant le " + esc((d.granted_at || "").slice(0, 10)) : "dossier téléversé"}</p></div>
    <div class="row">${req ? `<button class="btn" id="dl">Télécharger le rapport PDF</button>` : ""}<button class="btn primary" id="newreq">Nouvelle demande</button></div></div>

  <div class="card" style="margin-bottom:16px"><div class="row" style="align-items:flex-end">
    <div class="field" style="max-width:260px"><label>Demande</label><select id="reqsel">${d.requests.map((q) => `<option value="${q.id}" ${q.id === rid ? "selected" : ""}>#${q.id} — ${money(q.amount)} · ${q.duration_months} mois</option>`).join("")}<option value="" ${!rid ? "selected" : ""}>Sans demande</option></select></div>
    <div class="field"><label>Montant (FCFA)</label><input id="s_amount" type="number" step="50000" value="${cur?.amount ?? ""}"></div>
    <div class="field"><label>Durée (mois)</label><input id="s_dur" type="number" value="${cur?.duration_months ?? 12}"></div>
    <div class="field"><label>Taux annuel (%)</label><input id="s_rate" type="number" step="0.5" value="${cur ? +(cur.annual_rate * 100).toFixed(2) : 15}"></div>
    <button class="btn" id="simbtn">Simuler « et si »</button>
    ${sim ? `<button class="btn primary" id="savereq">Enregistrer comme demande</button>` : ""}
  </div>${sim ? `<div class="notice" style="margin-top:8px">Simulation : rien n'est enregistré.</div>` : req?.purpose ? `<div class="small muted">Objet : ${esc(req.purpose)}</div>` : ""}</div>

  <div class="grid g3">
    <div class="card"><h2>Score de risque (règles)</h2><div class="row" style="align-items:center;flex-wrap:nowrap">${scoreRing(s.score, s.capped)}<div><b>${esc(s.category)}</b><div class="small muted" style="margin-top:6px">25 % rentabilité · 20 % liquidité · 20 % endettement · 20 % stabilité · 15 % qualité des données</div></div></div>
      <div style="margin-top:12px">${s.dimensions.map((x) => `<div style="margin-bottom:8px"><div class="row small" style="justify-content:space-between"><span>${esc(x.label)} <span class="muted">(${x.weight * 100} %)</span></span><b>${x.note === null ? "n.c." : Math.round(x.note)}</b></div><div class="bar"><span style="width:${x.note ?? 0}%;background:${noteColor(x.note)}"></span></div></div>`).join("")}</div></div>
    <div class="card"><h2>Probabilité de défaut indicative</h2>${p.available ? `
      <div class="kpi" style="padding:0"><div class="value" style="font-size:30px">${pct(p.pd * 100)}</div><div class="sub">à 1 an · ${p.relative_to_base.toLocaleString("fr-FR")} × le taux moyen du jeu d'entraînement (${pct(p.base_rate * 100)})</div></div>
      <div style="margin-top:10px">${p.factors.map((f) => `<div class="row small" style="justify-content:space-between;flex-wrap:nowrap;border-bottom:1px solid var(--line);padding:4px 0"><span>${esc(f.label)}${f.imputed ? ' <span class="chip neutral">imputé</span>' : ""}</span><span class="chip ${f.effect.startsWith("augmente") ? "bad" : "good"}">${f.effect}</span></div>`).join("")}</div>
      ${p.expected_loss ? `<div class="notice" style="margin-top:10px">Perte attendue EL = PD × LGD × EAD = ${pct(p.pd * 100)} × ${p.expected_loss.lgd * 100} % × ${money(p.expected_loss.ead)} = <b>${money(p.expected_loss.el)}</b></div>` : ""}
      <p class="small muted" style="margin-top:8px">Modèle ${esc(p.model)} entraîné sur des <b>données réelles</b> (${esc(p.dataset.name)}) — entreprises polonaises, pas des commerçants béninois. <a href="#/i/modele">Méthode et limites</a></p>`
      : `<p class="muted">${esc(p.reason)}</p>`}</div>
    <div class="card"><h2>Capacité de remboursement</h2><dl class="kv">
      <dt>Flux disponible annuel (EBE – impôt)</dt><dd>${money(cr.cfads_annual)}</dd>
      <dt>Échéances actuelles (12 mois)</dt><dd>${money(cr.existing_service_annual)}</dd>
      <dt>Nouvelle mensualité</dt><dd>${money(cr.new_installment)}</dd>
      <dt>DSCR actuel</dt><dd>${fmtRatio(R.dscr_actuel)}</dd>
      <dt>DSCR avec le crédit</dt><dd style="color:${R.dscr_avec_credit.value === null ? "inherit" : R.dscr_avec_credit.value >= 1.25 ? "var(--teal)" : R.dscr_avec_credit.value >= 1 ? "var(--amber)" : "var(--red)"}">${fmtRatio(R.dscr_avec_credit)}</dd>
      <dt>Mensualité max. (DSCR 1,25)</dt><dd>${money(cr.max_installment_dscr_1_25)}</dd></dl>
      <p class="small muted" style="margin-top:10px">Un DSCR supérieur à 1 indique une couverture théorique des échéances ; il ne suffit pas seul à approuver un crédit. Définition du flux à valider avec l'équipe Finance.</p></div>
  </div>

  <div class="card" style="margin-top:16px"><h2>Pourquoi ce score ?</h2><ul style="margin:0;padding-left:18px">${s.explanations.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>

  <div class="tabs" style="margin-top:20px" id="tabs">${[["evol", "Évolution"], ["alertes", `Anomalies (${a.alerts.length})`], ["ratios", "Ratios"], ["score", "Détail du score"], ["couverture", "Données et documents"], ["decision", "Décision"]].map(([k, l], i) => `<button data-t="${k}" class="${i === 0 ? "active" : ""}">${l}</button>`).join("")}</div>
  <div data-p="evol"><div class="grid g3"><div class="card span2"><h2>Évolution mensuelle</h2><div class="chart-box"><canvas id="ch"></canvas></div></div>
    <div class="card"><h2>Trimestres</h2><table><thead><tr><th>Trimestre</th><th class="num">CA</th><th class="num">vs préc.</th><th class="num">vs N-1</th></tr></thead><tbody>
      ${a.quarterly.map((q) => `<tr><td>${q.quarter}${q.complete ? "" : ` <span class="chip neutral">${q.months}/3 mois</span>`}</td><td class="num">${q.complete ? mfcfa(q.ventes) : "—"}</td><td class="num">${signed(q.var_vs_prev)}</td><td class="num">${signed(q.var_yoy)}</td></tr>`).join("")}</tbody></table>
      <p class="small muted">Les trimestres incomplets ne sont pas comparés. La comparaison avec N-1 neutralise la saisonnalité.</p></div></div>
    <div class="card" style="margin-top:16px"><h2>Détail mensuel</h2><div class="table-wrap"><table><thead><tr><th>Mois</th><th class="num">CA</th><th class="num">vs M-1</th><th class="num">vs N-1</th><th class="num">Marge commerciale</th><th class="num">Résultat net</th><th class="num">Trésorerie nette</th></tr></thead><tbody>
      ${a.monthly.slice().reverse().map((m) => `<tr><td>${m.month}${m.has_pnl ? "" : ' <span class="chip warn">sans données</span>'}</td><td class="num">${money(m.ventes)}</td><td class="num">${signed(m.var_mom)}</td><td class="num">${signed(m.var_yoy)}</td><td class="num">${money(m.marge_commerciale)}</td><td class="num">${money(m.resultat_net)}</td><td class="num">${money(m.tresorerie_nette_constatee)}</td></tr>`).join("")}</tbody></table></div></div></div>
  <div data-p="alertes" class="hidden"><div class="card"><p class="small muted">Une anomalie est un signal qui mérite une vérification : elle ne prouve pas une fraude. Chaque alerte affiche la raison et la méthode du signalement.</p>${alertsHtml(a.alerts)}</div></div>
  <div data-p="ratios" class="hidden"><div class="card">${ratiosTable(a.ratios)}<p class="small muted" style="margin-top:8px">Montants annuels calculés sur 12 mois glissants (${a.coverage.ttm_months[0]} → ${a.coverage.ttm_months.slice(-1)[0]})${a.coverage.annualised ? ", <b>annualisés</b> faute de 12 mois" : ""}. Bilan au ${esc(a.coverage.last_balance || "—")}.</p></div></div>
  <div data-p="score" class="hidden"><div class="card"><table><thead><tr><th>Dimension</th><th>Critère</th><th class="num">Valeur</th><th class="num">Note</th><th>Règle</th></tr></thead><tbody>
    ${s.dimensions.map((dm) => dm.details.map((x, i) => `<tr>${i === 0 ? `<td rowspan="${dm.details.length}"><b>${esc(dm.label)}</b><div class="small muted">poids ${dm.weight * 100} % · note ${dm.note === null ? "n.c." : Math.round(dm.note)}</div></td>` : ""}<td>${esc(x.criterion)}</td><td class="num">${esc(x.value ?? "n.c.")}</td><td class="num" style="color:${noteColor(x.note)}"><b>${x.note === null ? "—" : Math.round(x.note)}</b></td><td class="small muted">${esc(x.rule)}</td></tr>`).join("")).join("")}
    </tbody></table><p class="small muted">${esc(s.weights_note)} Un critère non calculable est retiré et sa pondération redistribuée. Ce score n'est pas un modèle prédictif et ne constitue pas une décision.</p></div></div>
  <div data-p="couverture" class="hidden"><div class="grid g2">
    <div class="card"><h2>Période couverte</h2><dl class="kv"><dt>Période</dt><dd>${a.coverage.first_month} → ${a.coverage.last_month}</dd><dt>Mois de compte de résultat</dt><dd>${a.coverage.n_months_pnl}</dd>
      <dt>Mois manquants</dt><dd>${a.coverage.missing_months.join(", ") || "aucun"}</dd><dt>Dernier bilan</dt><dd>${esc(a.coverage.last_balance || "aucun")}</dd><dt>Opérations du grand livre</dt><dd>${nf0.format(a.n_transactions)}</dd>
      <dt>Fiabilité des valeurs</dt><dd>${Object.entries(a.coverage.status_counts).map(([k, v]) => `<span class="chip ${k}">${v} ${STATUS[k]}</span>`).join(" ")}</dd></dl>
      <h3 style="margin-top:16px">Documents attendus</h3>${a.checklist.map((c) => `<div class="row small" style="justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--line)"><span>${esc(c.document)}${c.note ? ` <span class="muted">— ${esc(c.note)}</span>` : ""}</span><span class="chip ${c.ok ? "good" : "warn"}">${c.ok ? "reçu" : "manquant"}</span></div>`).join("")}</div>
    <div class="card"><h2>Fichiers sources</h2><table><thead><tr><th>Fichier</th><th>Type</th><th class="num">Valeurs</th><th class="num">Opér.</th></tr></thead><tbody>${a.documents.map((x) => `<tr><td class="small">${esc(x.filename)}</td><td class="small">${KIND[x.kind] || esc(x.kind)}</td><td class="num">${x.n_values}</td><td class="num">${x.n_transactions}</td></tr>`).join("")}</tbody></table>
      <h3 style="margin-top:16px">Limites de l'analyse</h3><ul class="small" style="padding-left:18px">${a.limits.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div></div></div>
  <div data-p="decision" class="hidden"><div class="grid g2">
    <div class="card"><h2>Décision de l'analyste</h2>${req ? `<form id="dec"><div class="field"><label>Décision</label><select name="decision">${["Accordé", "Accordé sous conditions", "Refusé", "Ajourné : pièces complémentaires"].map((x) => `<option>${x}</option>`).join("")}</select></div>
      <div class="field"><label>Motif (obligatoire, conservé dans le rapport)</label><textarea name="comment" rows="4" required minlength="5" placeholder="Ex. : DSCR de 1,41 avec le crédit, activité stable sur 24 mois ; demander les relevés bancaires des 3 derniers mois."></textarea></div>
      <button class="btn primary">Enregistrer la décision</button></form><p class="small muted">La décision reste humaine : CreditWise prépare l'analyse, l'analyste habilité décide.</p>` : `<p class="muted">Sélectionnez ou créez une demande de crédit pour enregistrer une décision.</p>`}</div>
    <div class="card"><h2>Historique</h2>${req?.decision ? `<p><span class="chip ${req.decision.decision.startsWith("Accord") ? "good" : req.decision.decision.startsWith("Refus") ? "bad" : "warn"}">${esc(req.decision.decision)}</span> par ${esc(req.decision.analyst)} le ${esc(req.decision.decided_at.slice(0, 16))}</p><p>${esc(req.decision.comment)}</p><p class="small muted">Score au moment de la décision : ${req.decision.score === null ? "—" : Math.round(req.decision.score)} · PD : ${req.decision.pd === null ? "—" : pct(req.decision.pd * 100)}</p>` : `<p class="muted">Aucune décision enregistrée.</p>`}</div></div></div>`;

  monthlyChart($("#ch"), a);
  $$("#tabs button").forEach((b) => (b.onclick = () => { $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b)); $$("[data-p]").forEach((p) => p.classList.toggle("hidden", p.dataset.p !== b.dataset.t)); }));
  $("#reqsel").onchange = (e) => (location.hash = `#/i/dossier/${cid}${e.target.value ? "/" + e.target.value : ""}`);
  const simVals = () => ({ amount: +$("#s_amount").value, duration_months: +$("#s_dur").value, annual_rate: +$("#s_rate").value / 100 });
  $("#simbtn").onclick = () => { const v = simVals(); if (!v.amount) return toast("Indiquez un montant"); destroyCharts(); viewDossier(cid, rid, v); };
  const createReq = async () => { const v = simVals(); if (!v.amount) return toast("Indiquez un montant");
    const purpose = prompt("Objet du crédit :", "Fonds de roulement") || null;
    const r = await api("/api/requests", { json: { company_id: cid, ...v, purpose } }); toast("Demande enregistrée"); location.hash = `#/i/dossier/${cid}/${r.id}`; };
  if ($("#savereq")) $("#savereq").onclick = createReq;
  $("#newreq").onclick = () => { $("#s_amount").focus(); toast("Saisissez montant, durée et taux, puis « Simuler » et « Enregistrer »"); if (!sim) { $("#s_amount").value = ""; } };
  if ($("#dl")) $("#dl").onclick = () => download(`/api/requests/${rid}/report.pdf`, "Rapport_CreditWise.pdf");
  if ($("#dec")) $("#dec").onsubmit = async (e) => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    try { await api(`/api/requests/${rid}/decision`, { json: f }); toast("Décision enregistrée et tracée"); viewDossier(cid, rid); } catch (err) { toast(err.message); } };
}

async function viewInstitutionUpload(cid) {
  app().innerHTML = `<div class="page-head"><div><h1>Téléverser un dossier reçu</h1><p class="muted">Le commerçant vous a transmis un dossier CreditWise (PDF signé) ou ses fichiers comptables : créez un dossier puis déposez-les.</p></div></div>
  <div class="grid g2"><div class="card">${cid ? `<div class="notice ok">Dossier #${cid} créé. Déposez les fichiers.</div>` : `<form id="nc"><div class="row"><div class="field"><label>Nom du commerce</label><input name="name" required></div><div class="field"><label>Ville</label><input name="city"></div></div>
    <div class="field"><label>Secteur</label><input name="sector"></div><button class="btn primary">Créer le dossier</button></form>`}
    ${cid ? `<label class="dropzone" id="dz" style="margin-top:12px"><input type="file" id="file" multiple accept=".pdf,.xlsx,.xls,.csv" hidden><b>Déposez le dossier PDF ou les fichiers</b><div class="muted small">PDF, XLSX, CSV</div></label><div id="res" style="margin-top:12px"></div>` : ""}</div>
    <div class="card"><h2>Comment ça marche ?</h2><ol class="small" style="padding-left:18px"><li>Le commerçant exporte son dossier depuis « Partage et accès » (option : mot de passe).</li>
    <li>Le PDF contient une synthèse lisible et les données normalisées <b>signées (HMAC-SHA256)</b>.</li><li>À l'import, CreditWise vérifie la signature : un fichier modifié est refusé.</li>
    <li>Les statuts d'origine (déclaré, extrait, vérifié) sont conservés.</li></ol><p class="small muted">Un PDF chiffré doit être déchiffré avant import (prototype).</p></div></div>`;
  if ($("#nc")) $("#nc").onsubmit = async (e) => { e.preventDefault(); const r = await api("/api/companies", { json: Object.fromEntries(new FormData(e.target)) }); location.hash = `#/i/televerser/${r.id}`; };
  if ($("#dz")) {
    const send = async (files) => { const fd = new FormData(); [...files].forEach((f) => fd.append("files", f));
      const r = await api(`/api/companies/${cid}/documents`, { method: "POST", body: fd });
      $("#res").innerHTML = r.results.map((x) => `<div class="notice ${x.n_values ? "ok" : "warn"}" style="margin-bottom:6px"><b>${esc(x.filename)}</b> — ${KIND[x.kind] || esc(x.kind)} : ${x.n_values} valeur(s), ${x.n_transactions} opération(s).${(x.warnings || []).map((w) => "<br>" + esc(w)).join("")}</div>`).join("") + `<a class="btn primary" href="#/i/dossier/${cid}">Voir l'analyse →</a>`; };
    $("#file").onchange = () => send($("#file").files);
    $("#dz").ondragover = (e) => { e.preventDefault(); $("#dz").classList.add("over"); };
    $("#dz").ondrop = (e) => { e.preventDefault(); $("#dz").classList.remove("over"); send(e.dataTransfer.files); };
  }
}

async function viewModel() {
  const c = await api("/api/model-card");
  const v = c.metrics_test;
  app().innerHTML = `<div class="page-head"><div><h1>Modèle et méthode</h1><p class="muted">Ce qui est calculé, comment, et ce que cela ne permet pas de conclure.</p></div></div>
  <div class="grid g2">
    <div class="card"><h2>Probabilité de défaut indicative — données réelles</h2>
      <p><b>${esc(c.dataset.name)}</b> — ${nf0.format(c.dataset.rows)} entreprises, ${nf0.format(c.dataset.positives)} faillites (${pct(c.dataset.base_rate * 100)}), licence ${esc(c.dataset.license)}.<br><span class="small muted">${esc(c.dataset.citation)} · <a href="${esc(c.dataset.url)}" target="_blank" rel="noopener">source UCI</a></span></p>
      <p class="small">Cible : ${esc(c.dataset.target)}. ${esc(c.split)}. ${esc(c.missing_values)}.</p>
      <table><thead><tr><th>Variante</th><th>Modèle</th><th class="num">ROC-AUC</th><th class="num">PR-AUC</th><th class="num">Brier</th></tr></thead><tbody>
      ${Object.entries(v).map(([k, m]) => Object.entries(m).map(([name, x]) => `<tr><td class="small">${esc(c.variants[k])}</td><td>${name === "xgboost" ? "XGBoost (retenu)" : "Régression logistique (référence)"}</td><td class="num">${x.roc_auc.toFixed(3)}</td><td class="num">${x.pr_auc.toFixed(3)}</td><td class="num">${x.brier.toFixed(3)}</td></tr>`).join("")).join("")}
      </tbody></table><p class="small muted">Jeu de test (25 %) mis de côté avant tout réglage. PR-AUC à comparer au taux de base de ${pct(c.dataset.base_rate * 100)}. XGBoost s'entraîne sur GPU avec <code>--device cuda</code> et s'exécute ensuite sans GPU.</p>
      <h3>Limites</h3><ul class="small" style="padding-left:18px">${c.limits.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div>
    <div class="card"><h2>Variables utilisées (ratios recalculés par CreditWise)</h2><table><thead><tr><th>Ratio</th><th class="num">Importance</th></tr></thead><tbody>
      ${Object.entries(c.feature_importance.complet).map(([k, imp]) => `<tr><td>${esc(c.features[k])}</td><td class="num"><div class="bar" style="width:120px;display:inline-block;vertical-align:middle"><span style="width:${imp * 400}%;background:var(--blue)"></span></div> ${pct(imp * 100)}</td></tr>`).join("")}
      </tbody></table>
      <h3 style="margin-top:16px">Score de risque à base de règles</h3><p class="small">Score = 25 % rentabilité + 20 % liquidité + 20 % endettement + 20 % stabilité + 15 % qualité des données. Seuils explicites, chaque note est expliquée ; catégorie plafonnée à « à examiner » en cas d'alerte de fiabilité non résolue. Pondérations illustratives à valider par l'équipe Finance.</p>
      <h3>Détection d'anomalies</h3><p class="small">Règles d'abord (doublons, dates impossibles, montants négatifs, bilan non équilibré, totaux grand livre ≠ états, postes absents, baisse prolongée, trésorerie négative), puis Z-score désaisonnalisé (|Z| ≥ 3, au moins 30 opérations). Isolation Forest testé puis écarté : sans signal sur ce volume de données.</p></div>
  </div>`;
}
