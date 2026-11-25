/* CreditWise : interface (commerçant / institution financière). Vanilla JS + Chart.js local. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = () => $("#app");
const capitalize = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const money = (v) => (v === null || v === undefined ? "-" : nf0.format(v) + " FCFA");
const mfcfa = (v) => (v === null || v === undefined ? "-" : (v / 1e6).toLocaleString("fr-FR", { maximumFractionDigits: 2 }) + " M");
const pct = (v, d = 1) => (v === null || v === undefined ? "-" : v.toLocaleString("fr-FR", { maximumFractionDigits: d, minimumFractionDigits: d }) + " %");
const signed = (v) => (v === null || v === undefined ? "-" : (v > 0 ? "+" : "") + pct(v));
const STATUS = { declare: "déclaré", extrait: "extrait auto.", verifie: "vérifié", estime: "estimé" };
const SEV = { elevee: "Élevée", attention: "Attention", info: "Info" };
const KIND = { etat_financier: "États financiers (XLSX/CSV)", etat_financier_long: "États financiers (format long)", etat_financier_pdf: "États financiers PDF",
  balance_generale: "Balance générale", grand_livre: "Grand livre / journal", dossier_creditwise: "Dossier CreditWise signé", inconnu: "Non reconnu" };
let ME = null;
let SEQ = 0; // numéro de navigation : une réponse arrivée après un changement de page est ignorée
const charts = [];

// ------------------------------------------------------------------ icônes (traits, 24×24)
const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  upload: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 17v-6M9 14l3-3 3 3"/>',
  table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  model: '<path d="M4 19h16"/><path d="M6 15l4-5 3 3 5-7"/><circle cx="18" cy="6" r="1.5"/>',
  trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  trendDown: '<path d="M3 7l6 6 4-4 8 8"/><path d="M15 17h6v-6"/>',
  wallet: '<path d="M16 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v2"/><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M16 13.5h.01"/>',
  percent: '<path d="M19 5L5 19"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/>',
  coins: '<circle cx="12" cy="12" r="9"/><path d="M14.5 9.5c0-1.1-1.1-2-2.5-2s-2.5.9-2.5 2 1.1 1.7 2.5 2 2.5.9 2.5 2-1.1 2-2.5 2-2.5-.9-2.5-2M12 6v1.5M12 16.5V18"/>',
  alert: '<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  back: '<path d="M15 18l-6-6 6-6"/>',
  scale: '<path d="M12 3v18M5 21h14M6 7h12M6 7l-3 7a3 3 0 0 0 6 0zM18 7l-3 7a3 3 0 0 0 6 0z"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
  store: '<path d="M3 9l1.5-5h15L21 9"/><path d="M3 9a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0"/><path d="M5 12v8h14v-8M10 20v-5h4v5"/>',
  bank: '<path d="M3 10l9-6 9 6"/><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
};
const icon = (n, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`;
const initials = (s) => String(s || "?").replace(/\(.*?\)/g, "").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const PALETTE = ["#0b2545", "#6b2180", "#1d4e89", "#334155", "#7c2d12", "#0e7490"]; // neutres : ne suggèrent pas un niveau de risque
const colorFor = (id) => PALETTE[(id - 1) % PALETTE.length];

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
  if (r.status === 401 && !path.endsWith("/login")) {
    ME = null;
    const page = location.hash.slice(2).split("/")[0];
    if (!PUBLIC_PAGES.includes(page)) location.hash = "#/"; // les pages publiques restent accessibles
    throw new Error("Connexion requise");
  }
  if (!r.ok) { let d; try { d = (await r.json()).detail; } catch { d = r.statusText; } throw new Error(typeof d === "string" ? d : JSON.stringify(d)); }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r;
}
async function download(path, fallbackName, opts = {}) {
  try {
    const r = await api(path, opts);
    const blob = await r.blob();
    const cd = r.headers.get("content-disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: m ? decodeURIComponent(m[1]) : fallbackName });
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast("Téléchargement lancé");
  } catch (e) { toast(e.message); }
}
function destroyCharts() { while (charts.length) charts.pop().destroy(); }
const loading = () => (app().innerHTML = `<div class="loading"><span class="spinner"></span>Chargement</div>`);

// ------------------------------------------------------------------ routeur
// Pages publiques : accueil, connexion par profil, guides. Le reste exige une session.
const SLUG = { commercant: "merchant", microfinance: "institution", etablissement: "institution" };
const PUBLIC_PAGES = ["", "connexion", "inscription", "guide", "login", "cgu", "confidentialite"];
const SLUG_OF = { merchant: "commercant", institution: "microfinance" };
const home = () => (ME.role === "merchant" ? "#/m/tableau" : "#/i/dossiers");

async function route() {
  SEQ++;
  destroyCharts();
  const h = location.hash.slice(2).split("/");
  if (!ME) { try { const r = await api("/api/session"); ME = r.authenticated ? r : null; } catch (e) { if (e.stale) return; ME = null; } }
  const isGuide = h[0] === "guide";
  const pub = !ME || ["", "connexion", "inscription", "login", "cgu", "confidentialite"].includes(h[0]);
  renderShell(h, pub && !(isGuide && ME));
  window.scrollTo(0, 0);
  if (isGuide) return viewGuide(SLUG[h[1]] || "merchant");
  if (h[0] === "cgu" || h[0] === "confidentialite") return viewLegal(h[0]);
  if (!ME) {
    if (h[0] === "connexion" || h[0] === "inscription") return viewAuth(SLUG[h[1]] || "merchant", h[0] === "inscription" ? "signup" : "login");
    return viewLanding();
  }
  if (pub) return (location.hash = home());
  loading();
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
  } catch (e) { if (!e.stale) app().innerHTML = `<div class="notice warn">${icon("alert")}<span>${esc(e.message)}</span></div>`; }
}
window.addEventListener("hashchange", route);
window.addEventListener("load", route);

function renderShell(h, pub) {
  const shell = $("#shell"), nav = $("#nav"), who = $("#who");
  shell.classList.toggle("public", pub);
  if (pub) { nav.innerHTML = ""; who.innerHTML = ""; return; }
  const links = ME.role === "merchant"
    ? [["#/m/tableau", "Tableau de bord", "dashboard", h[0] === "m" && (!h[1] || h[1] === "tableau")], ["#/m/documents", "Documents", "upload", h[1] === "documents"],
       ["#/m/donnees", "Données", "table", h[1] === "donnees"], ["#/m/partage", "Partage et accès", "shield", h[1] === "partage"]]
    : [["#/i/dossiers", "Dossiers de crédit", "folder", h[0] === "i" && (!h[1] || h[1] === "dossiers" || h[1] === "dossier")], ["#/i/televerser", "Téléverser un dossier", "upload", h[1] === "televerser"],
       ["#/i/modele", "Modèle et méthode", "model", h[1] === "modele"]];
  links.push([`#/guide/${SLUG_OF[ME.role]}`, "Guide d'utilisation", "book", h[0] === "guide"]);
  nav.innerHTML = `<div class="section">${ME.role === "merchant" ? "Espace commerçant" : "Espace établissement de crédit"}</div>` +
    links.map(([href, l, i, a]) => `<a href="${href}" class="${a ? "active" : ""}">${icon(i)}<span>${l}</span></a>`).join("");
  who.innerHTML = `<div class="user"><div class="avatar">${initials(ME.display_name)}</div><div><div class="name">${esc(ME.display_name)}</div>
    <div class="role">${esc(ME.organisation || (ME.role === "merchant" ? ME.companies[0]?.name || "Commerçant" : "Institution"))}</div></div></div>
    <button class="logout" id="logout">${icon("logout").replace("<svg ", '<svg width="14" height="14" style="vertical-align:-2px;margin-right:6px" ')}Déconnexion</button>`;
  $("#logout").onclick = async () => { await api("/api/logout", { method: "POST" }); ME = null; location.hash = "#/"; };
}

const LOGO = `<img class="mark" src="assets/logo-mark.png" alt=""><span class="word">CreditWise</span>`;
const LOGO_FULL = (cls) => `<img class="${cls}" src="assets/logo.png" alt="CreditWise, financer mieux, avancer plus">`;
function publicTop() {
  return `<header class="pub-top"><a class="brand" href="#/" aria-label="CreditWise, accueil">${LOGO.replace('class="word"', 'class="word" style="color:var(--navy)"')}</a>
    <nav aria-label="Navigation principale"><a href="#/" data-goto="etapes">Comment ça marche</a><a href="#/guide/commercant">Guide commerçant</a><a href="#/guide/microfinance">Guide établissement</a></nav>
    <div class="pub-cta"><a class="btn sm" href="#/connexion/commercant">Espace commerçant</a><a class="btn sm brand" href="#/connexion/microfinance">Espace établissement</a></div></header>`;
}

// ------------------------------------------------------------------ accueil (affiche)
const ETAPES = [
  ["Importer", "Le commerçant dépose ses états financiers, sa balance ou son journal de caisse (PDF, Excel ou CSV). CreditWise reconnaît le document et la période."],
  ["Vérifier", "Les montants lus automatiquement dans un PDF sont marqués « à vérifier ». Le commerçant les confirme ou les corrige avant de partager."],
  ["Partager", "Le commerçant choisit l'établissement de crédit qui peut voir son dossier. Il peut retirer cet accès à tout moment, chaque consultation est enregistrée."],
  ["Décider", "L'analyste lit les ratios, l'évolution mois par mois et les écarts relevés, simule le crédit, puis enregistre sa décision avec un motif obligatoire."],
];
const LEXIQUE = [
  ["Chiffre d'affaires", "Le total des ventes sur une période, encaissées ou non."],
  ["Trésorerie", "L'argent disponible en caisse et en banque, moins les découverts."],
  ["Marge nette", "La part des ventes qui reste en bénéfice, en pourcentage."],
  ["DSCR", "Capacité à payer les échéances : flux disponible divisé par les échéances. Au-dessus de 1,25, il reste une marge de sécurité."],
  ["Alerte", "Un signal à vérifier, jamais une accusation. Chaque alerte donne sa raison et sa méthode."],
];
function accordion(container, cls) {
  $$(`.${cls} > button`, container).forEach((b) => (b.onclick = () => {
    const row = b.parentElement, open = !row.classList.contains("on");
    row.classList.toggle("on", open); b.setAttribute("aria-expanded", String(open));
  }));
}
function viewLanding() {
  app().innerHTML = `${publicTop()}
  <section class="landing-hero" aria-labelledby="titre-accueil">
    <div class="hero-bars" aria-hidden="true"><i></i><i></i><i></i></div>
    <h1 class="geant" id="titre-accueil" aria-label="CreditWise"><span class="l1">Credit</span><span class="l2">Wise</span></h1>
    <div class="hero-bas">
      <p><b>Étudier une demande de crédit à partir des comptes du commerçant.</b> Le commerçant importe ses documents comptables. CreditWise calcule les ratios, compare les mois entre eux et relève les écarts. L'analyste de l'établissement de crédit décide.</p>
      <div><p class="tagline-big">Financer mieux, avancer plus.</p>
        <div class="acts"><a class="btn brand" href="#/inscription/commercant">Je suis commerçant</a><a class="btn primary" href="#/inscription/microfinance">Je suis un établissement</a></div></div>
    </div>
  </section>
  <div class="facts" role="list"><span role="listitem">PDF, Excel, CSV</span><span role="listitem">20 ratios expliqués</span><span role="listitem">Alertes justifiées</span><span role="listitem">Décision humaine</span></div>

  <section class="esp" id="espaces" aria-label="Les deux espaces">
    <article class="vol c"><div><p class="kick">Espace commerçant</p><h2>Je suis<br>commerçant</h2>
      <p class="lead">Préparez un dossier financier solide et partagez-le avec l'établissement de crédit de votre choix.</p>
      <ul><li>Importez vos états, votre balance ou votre journal de caisse</li><li>Vérifiez les chiffres lus automatiquement</li><li>Décidez qui peut consulter votre dossier</li></ul></div>
      <div class="acts"><a class="btn brand" href="#/inscription/commercant">Créer un compte</a><a class="btn" href="#/connexion/commercant">Se connecter</a><a class="btn ghost" href="#/guide/commercant">Guide</a></div></article>
    <article class="vol i"><div><p class="kick">Espace établissement</p><h2>Établissement<br>de crédits</h2>
      <p class="lead">Analysez les dossiers partagés : ratios, évolution, anomalies, score et rapport PDF.</p>
      <ul><li>Indicateurs et formules du guide Finance</li><li>Écarts signalés, score détaillé critère par critère</li><li>Décision prise et motivée par l'analyste</li></ul></div>
      <div class="acts"><a class="btn brand" href="#/inscription/microfinance">Créer un compte</a><a class="btn" href="#/connexion/microfinance">Se connecter</a><a class="btn ghost" href="#/guide/microfinance">Guide</a></div></article>
  </section>

  <section class="sec" id="etapes" aria-labelledby="titre-etapes"><p class="kick">Comment ça marche</p><h2 class="titre" id="titre-etapes">Quatre<br>étapes.</h2>
    <div id="etps">${ETAPES.map(([t, d], i) => `<div class="et${i === 0 ? " on" : ""}"><button aria-expanded="${i === 0}" aria-controls="et${i}"><span class="nu">0${i + 1}</span><span class="tt">${t}</span><span class="pl" aria-hidden="true">+</span></button>
      <div class="in" id="et${i}"><p>${d}</p></div></div>`).join("")}</div></section>
  <div class="facts inv" role="list"><span role="listitem">Données partagées avec votre accord</span><span role="listitem">Chaque consultation est tracée</span></div>

  <section class="sec" id="lexique" aria-labelledby="titre-lex"><p class="kick">Le guide</p><h2 class="titre" id="titre-lex">Les mots<br>du dossier.</h2>
    <div id="lx">${LEXIQUE.map(([t, d], i) => `<div class="lex-row"><button aria-expanded="false" aria-controls="lx${i}">${t}</button><div class="df" id="lx${i}">${d}</div></div>`).join("")}</div>
    <p style="margin-top:24px;display:flex;gap:10px;flex-wrap:wrap"><a class="btn" href="#/guide/commercant">Guide commerçant complet</a><a class="btn" href="#/guide/microfinance">Guide établissement complet</a></p></section>
  <footer class="pied">CreditWise ne prête pas d'argent et ne remplace pas le banquier. Prototype GPU Challenge 2026 : entreprises et personnes de démonstration fictives. <a href="#/cgu">Conditions générales</a>, <a href="#/confidentialite">Confidentialité</a></footer>`;
  accordion(app(), "et"); accordion(app(), "lex-row");
  $$("[data-goto]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); $("#" + a.dataset.goto)?.scrollIntoView(); }));
}

// ------------------------------------------------------------------ connexion et inscription (code par e-mail, Google)
const DEMOS = {
  merchant: [["akwaba", "Boutique Akwaba Mode", "Vêtements, activité stable", "#0f7a55"], ["solidite", "Quincaillerie La Solidité", "Ventes en baisse", "#b42318"],
             ["bonprix", "Alimentation Le Bon Prix", "Données à vérifier", "#9a5b00"], ["nouveau", "Nouveau commerçant", "Aucune donnée, import en direct", "#1d4e89"]],
  institution: [["analyste", "Analyste crédit", "Microfinance Démo, 3 dossiers reçus", "#0b2545"]],
};
const CATEGORIES = ["Vêtements et mode", "Alimentation", "Quincaillerie", "Cosmétiques", "Téléphonie", "Restauration", "Pièces auto", "Autre commerce"];
const FUNCTIONS = ["Analyste crédit", "Responsable crédit", "Direction", "Autre"];
let AUTH_CFG = null;

async function authConfig() {
  if (!AUTH_CFG) { try { AUTH_CFG = await api("/api/auth/config"); } catch { AUTH_CFG = {}; } }
  return AUTH_CFG;
}

async function viewAuth(role, mode) {
  const m = role === "merchant", signup = mode === "signup", slug = SLUG_OF[role];
  const cfg = await authConfig();
  const hero = m
    ? { title: "Préparez votre <em>dossier de crédit</em>", lead: "Importez vos documents comptables, vérifiez vos chiffres et partagez votre dossier avec l'établissement de votre choix." }
    : { title: "Les dossiers de crédit de <em>vos clients commerçants</em>", lead: "Pour chaque dossier : ratios, ventes mois par mois, écarts relevés dans les comptes et capacité de remboursement." };
  app().innerHTML = `
  <div class="auth">
    <section class="auth-hero">
      <a class="brand" href="#/">${LOGO}</a>
      <span class="space-badge">${icon(m ? "store" : "bank")}${m ? "Espace commerçant" : "Espace établissement de crédit"}</span>
      <h1>${hero.title}</h1><p class="lead">${hero.lead}</p><div class="tagline">Financer mieux, avancer plus.</div>
      <div class="preview"><a class="glass" href="#/guide/${slug}"><div><b>Première visite ?</b><div class="lbl">Le guide ${m ? "commerçant" : "établissement"} explique les 4 étapes.</div></div></a></div>
    </section>
    <section class="auth-form"><div class="auth-box" id="authbox"></div></section>
  </div>`;
  const box = $("#authbox");
  let profile = { category: null, function: null };

  const stepForm = () => {
    box.innerHTML = `
      <a href="#/" class="back-btn" aria-label="Retour à l'accueil">${icon("back")}</a>
      <h2 class="auth-title">${signup ? "Créer un compte" : "Se connecter"}</h2>
      <p class="muted" style="margin:0 0 20px">${signup ? (m ? "Quelques informations sur votre commerce avant de commencer." : "Quelques informations sur votre établissement.") : "Recevez un code de connexion par e-mail."}</p>
      <form id="authform" novalidate>
        ${signup ? `
          <div class="field"><label for="f_name">Nom complet</label><input id="f_name" name="full_name" maxlength="80" placeholder="Ex : Amivi Dossou" autocomplete="name"></div>
          <div class="field"><label for="f_org">${m ? "Nom du commerce" : "Établissement"}</label><input id="f_org" name="org" maxlength="120" placeholder="${m ? "Ex : Boutique Élégance" : "Ex : Caisse d'épargne de Cotonou"}"></div>
          <div class="field"><label>${m ? "Catégorie principale" : "Fonction"}</label><div class="pills" id="pills">${(m ? CATEGORIES : FUNCTIONS).map((c) => `<button type="button" class="pill" data-v="${c}">${c}</button>`).join("")}</div></div>
          <div class="field"><label for="f_city">${m ? "Ville ou quartier" : "Ville"} <span class="muted">(facultatif)</span></label><input id="f_city" name="city" maxlength="120" placeholder="Ex : Cotonou, Akpakpa"></div>` : ""}
        <div class="field"><label for="f_email">${m ? "Adresse e-mail" : "Adresse e-mail professionnelle"}</label><input id="f_email" name="email" type="email" maxlength="254" placeholder="Ex : nom@exemple.com" autocomplete="email" required></div>
        <div class="auth-actions">
          <button class="btn brand block" id="sendcode" disabled>Recevoir le code</button>
          ${cfg.google_client_id ? `<div class="or">ou</div><div id="gbtn" class="gbtn"></div>` : ""}
          ${signup ? `<label class="terms"><input type="checkbox" id="terms"> <span>J'accepte les <a href="#/cgu" target="_blank">Conditions générales</a> et la <a href="#/confidentialite" target="_blank">Politique de confidentialité</a>.</span></label>` : ""}
          <p class="switch-mode">${signup ? `Déjà un compte ? <a href="#/connexion/${slug}">Se connecter</a>` : `Pas encore de compte ? <a href="#/inscription/${slug}">Créer un compte</a>`}</p>
        </div>
      </form>
      ${!signup ? `<details class="demo-box"><summary>Comptes de démonstration</summary><div class="demo-list">${DEMOS[role].map(([u, t, d, c]) => `<button class="demo" data-demo="${u}"><span class="avatar" style="background:${c}">${initials(t)}</span><span><div class="t">${t}</div><div class="d">${d}</div></span></button>`).join("")}</div></details>` : ""}
      <div class="switch-space">${m ? "Vous êtes un établissement de crédit ?" : "Vous êtes commerçant ?"} <a href="#/${signup ? "inscription" : "connexion"}/${SLUG_OF[m ? "institution" : "merchant"]}">Espace ${m ? "établissement de crédit" : "commerçant"}</a></div>`;

    const form = $("#authform"), btn = $("#sendcode");
    const valid = () => {
      const email = /^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$/.test($("#f_email").value.trim());
      if (!signup) return email;
      return email && $("#f_name").value.trim().length >= 2 && $("#f_org").value.trim() && (!m || profile.category) && $("#terms").checked;
    };
    const readProfile = () => (signup ? {
      full_name: $("#f_name").value.trim(), city: $("#f_city").value.trim() || null,
      ...(m ? { company_name: $("#f_org").value.trim(), category: profile.category } : { organisation: $("#f_org").value.trim(), function: profile.function }),
    } : null);
    form.oninput = form.onchange = () => (btn.disabled = !valid());
    $$("#pills .pill").forEach((p) => (p.onclick = () => {
      $$("#pills .pill").forEach((x) => x.classList.toggle("on", x === p));
      profile[m ? "category" : "function"] = p.dataset.v; btn.disabled = !valid();
    }));
    form.onsubmit = async (e) => {
      e.preventDefault(); if (!valid()) return;
      btn.disabled = true; btn.textContent = "Envoi du code";
      const email = $("#f_email").value.trim();
      try {
        const r = await api("/api/auth/code", { json: { email, role, mode, profile: readProfile(), accept_terms: signup ? $("#terms").checked : false } });
        stepCode(r, email, readProfile());
      } catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Recevoir le code"; }
    };
    $$("[data-demo]").forEach((b) => (b.onclick = async () => {
      try { await api("/api/login", { json: { username: b.dataset.demo, password: "demo", role } }); ME = await api("/api/me"); location.hash = home(); }
      catch (err) { toast(err.message); }
    }));
    if (cfg.google_client_id) mountGoogle(cfg.google_client_id, role, mode, () => (signup ? (valid() ? readProfile() : false) : null), () => (signup ? $("#terms").checked : false));
  };

  const stepCode = (r, email, prof) => {
    let wait = 30, timer;
    box.innerHTML = `
      <button type="button" class="back-btn" id="backform" aria-label="Modifier l'adresse">${icon("back")}</button>
      <h2 class="auth-title">Saisissez le code</h2>
      <p class="muted" style="margin:0 0 18px">Un code à 6 chiffres a été envoyé à <b>${esc(r.sent_to)}</b>. Il est valable 10 minutes.</p>
      ${r.demo_code ? `<div class="notice warn" style="margin-bottom:16px">${icon("info")}<span>Prototype sans serveur d'e-mail : votre code est <b class="mono">${esc(r.demo_code)}</b>.</span></div>` : ""}
      <form id="codeform">
        <div class="field"><label for="f_code">Code reçu</label><input id="f_code" class="code-input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="000000" pattern="[0-9]{6}" required></div>
        <button class="btn brand block" id="checkcode" disabled>${signup ? "Créer mon compte" : "Se connecter"}</button>
      </form>
      <p class="switch-mode"><button type="button" class="linkbtn" id="resend" disabled>Renvoyer le code</button></p>`;
    const input = $("#f_code"), ok = $("#checkcode"), resend = $("#resend");
    input.focus();
    input.oninput = () => { input.value = input.value.replace(/\D/g, "").slice(0, 6); ok.disabled = input.value.length !== 6; };
    const tick = () => { resend.disabled = wait > 0; resend.textContent = wait > 0 ? `Renvoyer le code (${wait} s)` : "Renvoyer le code"; if (wait-- <= 0) clearInterval(timer); };
    tick(); timer = setInterval(tick, 1000);
    resend.onclick = async () => {
      try { const r2 = await api("/api/auth/code", { json: { email, role, mode, profile: prof, accept_terms: signup } }); clearInterval(timer); toast("Nouveau code envoyé"); stepCode(r2, email, prof); }
      catch (err) { toast(err.message); }
    };
    $("#backform").onclick = () => { clearInterval(timer); stepForm(); };
    $("#codeform").onsubmit = async (e) => {
      e.preventDefault(); ok.disabled = true;
      try { await api("/api/auth/verify", { json: { challenge: r.challenge, code: input.value } }); clearInterval(timer); ME = await api("/api/me"); toast(signup ? "Compte créé." : "Connexion réussie."); location.hash = home(); }
      catch (err) { toast(err.message); ok.disabled = false; input.select(); }
    };
  };
  stepForm();
}

function mountGoogle(clientId, role, mode, getProfile, getTerms) {
  const render = () => {
    const el = $("#gbtn"); if (!el || !window.google?.accounts?.id) return;
    google.accounts.id.initialize({ client_id: clientId, callback: async (res) => {
      const profile = getProfile();
      if (profile === false) return toast("Complétez le formulaire et acceptez les conditions avant de continuer avec Google.");
      try { await api("/api/auth/google", { json: { credential: res.credential, role, mode, profile, accept_terms: getTerms() } }); ME = await api("/api/me"); location.hash = home(); }
      catch (err) { toast(err.message); }
    } });
    google.accounts.id.renderButton(el, { theme: "outline", size: "large", shape: "pill", text: mode === "signup" ? "signup_with" : "continue_with", locale: "fr", width: Math.min(380, el.clientWidth || 380) });
  };
  if (window.google?.accounts?.id) return render();
  const s = document.createElement("script"); s.src = "https://accounts.google.com/gsi/client"; s.async = true; s.onload = render; document.head.appendChild(s);
}

// ------------------------------------------------------------------ conditions et confidentialité
function viewLegal(kind) {
  const cgu = kind === "cgu";
  app().innerHTML = `${publicTop()}<div class="guide-wrap"><div class="page-head"><div><h1>${cgu ? "Conditions générales d'utilisation" : "Politique de confidentialité"}</h1>
    <p class="sub">Prototype présenté au GPU Challenge 2026. Ce texte décrit le fonctionnement du prototype ; il devra être validé juridiquement avant toute mise en service.</p></div></div>
    <div class="card legal">${cgu ? `
      <h2>Objet</h2><p>CreditWise aide un commerçant à constituer un dossier financier et un établissement de crédit à l'analyser. CreditWise ne prête pas d'argent et ne prend aucune décision de crédit : la décision appartient à l'établissement.</p>
      <h2>Comptes</h2><p>La connexion se fait par un code envoyé à votre adresse e-mail ou par votre compte Google. Vous êtes responsable de l'accès à votre messagerie.</p>
      <h2>Données transmises</h2><p>Le commerçant garantit que les documents qu'il importe correspondent à son activité. Les valeurs lues automatiquement doivent être vérifiées par lui.</p>
      <h2>Partage</h2><p>Un établissement ne voit un dossier que si le commerçant l'y a autorisé. Le commerçant peut retirer cet accès à tout moment.</p>
      <h2>Limites</h2><p>Les scores et probabilités affichés sont des indicateurs d'aide à l'analyse. Ils ne constituent ni un conseil ni une décision.</p>` : `
      <h2>Données collectées</h2><p>Nom, adresse e-mail, nom du commerce ou de l'établissement, ville, documents comptables importés et journal des accès au dossier.</p>
      <h2>Utilisation</h2><p>Ces données servent uniquement à calculer l'analyse financière et à la partager avec les établissements que vous autorisez. Elles ne sont ni vendues ni utilisées pour de la publicité.</p>
      <h2>Consentement et partage</h2><p>Le partage d'un dossier exige l'accord explicite du commerçant, retirable à tout moment. Chaque consultation est enregistrée et visible par le commerçant.</p>
      <h2>Sécurité</h2><p>Connexion par code à usage unique, cookies de session protégés, données transmises au navigateur limitées au nécessaire.</p>
      <h2>Vos droits</h2><p>Vous pouvez demander l'accès, la rectification ou la suppression de vos données. Le traitement de données personnelles au Bénin relève de l'Autorité de protection des données personnelles (APDP).</p>`}
    </div></div>`;
}

// ------------------------------------------------------------------ guides
const GUIDES = {
  merchant: {
    title: "Guide du commerçant", intro: "Constituez votre dossier financier et partagez-le avec un établissement de crédit, en quatre étapes.",
    steps: [
      ["upload", "Importer vos documents", "Menu « Documents » : glissez vos fichiers dans la zone de dépôt. CreditWise reconnaît automatiquement le type de document et la période.",
        "Le plus utile : 12 mois de compte de résultat et de bilan. Un grand livre ou un journal de caisse permet en plus de contrôler les totaux.", "#/m/documents"],
      ["eye", "Vérifier les chiffres", "Menu « Données » : les montants lus dans un PDF sont marqués « extrait auto. ». Comparez-les à vos documents puis validez-les, ou corrigez-les.",
        "Une valeur vérifiée améliore la note « qualité des données » de votre dossier.", "#/m/donnees"],
      ["dashboard", "Comprendre votre tableau de bord", "Chiffre d'affaires, marge, trésorerie et évolution mois par mois. Le panneau « À vérifier avant transmission » montre ce que l'établissement de crédit verra.",
        "Une alerte n'est pas une accusation : préparez une explication (saison creuse, grosse commande).", "#/m/tableau"],
      ["shield", "Partager votre dossier", "Menu « Partage et accès » : cliquez sur « Autoriser l'accès » pour l'institution choisie. Vous pouvez retirer cet accès à tout moment.",
        "Le journal des accès vous montre qui a consulté votre dossier et quand. Vous pouvez aussi générer un PDF signé, protégé par mot de passe.", "#/m/partage"],
    ],
    docs: [["Compte de résultat", "Ventes, achats et charges, idéalement mois par mois."], ["Bilan", "Stocks, caisse, banque, dettes fournisseurs, emprunts."],
           ["Grand livre ou journal", "Le détail des opérations (ventes du jour, factures)."], ["Balance générale", "Les soldes de chaque compte, exportés du logiciel."]],
    glossary: [["Chiffre d'affaires", "Le total de vos ventes sur la période (pas forcément encaissées)."], ["Trésorerie", "L'argent disponible en caisse et en banque, moins les découverts."],
               ["Marge nette", "La part de vos ventes qui reste en bénéfice, en %."], ["Valeur « extraite auto. »", "Un montant lu automatiquement dans un PDF : à confirmer."]],
    faq: [["Mes données sont-elles visibles par tout le monde ?", "Non. Seule l'institution que vous autorisez peut consulter votre dossier, et chaque consultation est enregistrée."],
          ["Je n'ai pas de logiciel comptable, comment faire ?", "Importez un journal de caisse ou mobile money au format CSV (date, référence, tiers, libellé, compte, débit, crédit), ou les états PDF préparés par votre comptable."],
          ["CreditWise décide-t-il de mon crédit ?", "Non. CreditWise prépare l'analyse ; la décision est prise par un analyste de l'institution, qui doit la motiver."],
          ["Un fichier n'est pas reconnu, que faire ?", "Vérifiez le format (PDF texte, XLSX ou CSV). Les photos de reçus ne sont pas encore prises en charge. Les postes non reconnus sont signalés et jamais additionnés."]],
  },
  institution: {
    title: "Guide de l'établissement de crédit", intro: "Analysez un dossier partagé et enregistrez une décision motivée, en quatre étapes.",
    steps: [
      ["folder", "Ouvrir un dossier", "Menu « Dossiers de crédit » : chaque carte montre le score, la probabilité de défaut et l'évolution des ventes. Cliquez pour ouvrir l'analyse.",
        "Un dossier n'apparaît que si le commerçant vous a autorisé. Vous pouvez aussi téléverser un dossier PDF signé qu'il vous a transmis.", "#/i/dossiers"],
      ["scale", "Lire la synthèse", "En haut : score de risque (règles explicables), probabilité de défaut indicative et capacité de remboursement (DSCR). « Pourquoi ce score ? » liste les points forts et faibles.",
        "Le score est plafonné à « à examiner » si des anomalies de fiabilité ne sont pas résolues.", "#/i/dossiers"],
      ["alert", "Examiner l'évolution et les anomalies", "Onglets « Évolution », « Anomalies », « Ratios » : chaque alerte donne la raison, la méthode et une explication possible à demander au commerçant.",
        "Une anomalie est un signal à vérifier, pas la preuve d'une fraude.", "#/i/dossiers"],
      ["check", "Simuler puis décider", "Modifiez montant, durée et taux puis « Simuler » pour recalculer la capacité de remboursement. Onglet « Décision » : choisissez et motivez votre décision, puis téléchargez le rapport PDF.",
        "Le motif est obligatoire et figure dans le rapport ; la décision est tracée dans le journal du commerçant.", "#/i/dossiers"],
    ],
    docs: [["Score de risque", "25 % rentabilité, 20 % liquidité, 20 % endettement, 20 % stabilité, 15 % qualité des données."], ["PD indicative", "Modèle XGBoost entraîné sur données réelles d'entreprises (UCI)."],
           ["DSCR", "Flux disponible / échéances. Au-dessus de 1,25 : marge de sécurité."], ["Rapport PDF", "Synthèse, formules, alertes, score et décision, prêt à archiver."]],
    glossary: [["DSCR", "Capacité à couvrir les échéances de dette avec les flux de l'activité."], ["PD", "Probabilité de défaut à un an, indicative et relative au jeu d'entraînement."],
               ["BFR", "Argent immobilisé dans les stocks et les créances, moins les dettes d'exploitation."], ["EL = PD × LGD × EAD", "Perte attendue si le crédit est accordé."]],
    faq: [["La PD est-elle une probabilité réelle pour ce commerçant ?", "Non. Le modèle est entraîné sur des entreprises polonaises : la PD est un indicateur relatif, à lire avec le score et les ratios."],
          ["Puis-je modifier les données du commerçant ?", "Non. Seul le commerçant corrige ses données ; vous voyez le statut de chaque valeur (déclarée, extraite, vérifiée)."],
          ["Pourquoi certains ratios sont « non calculables » ?", "Quand une donnée manque ou est nulle, le ratio n'est pas calculé plutôt que d'afficher un chiffre faux."],
          ["Le commerçant peut-il retirer l'accès ?", "Oui, à tout moment. Le dossier disparaît alors de votre liste."]],
  },
};
function viewGuide(role) {
  const g = GUIDES[role], m = role === "merchant", logged = !!ME, mine = logged && ME.role === role;
  const other = m ? "institution" : "merchant";
  app().innerHTML = `${logged ? "" : publicTop()}
  <div class="${logged ? "" : "guide-wrap"}">
    <div class="page-head"><div><div class="eyebrow">${icon("book").replace("<svg ", '<svg width="14" height="14" ')}Guide d'utilisation</div><h1>${g.title}</h1><p class="sub">${g.intro}</p></div>
      ${logged ? "" : `<a class="btn brand" href="#/connexion/${SLUG_OF[role]}">Accéder à l'espace ${m ? "commerçant" : "établissement"}</a>`}</div>
    <div class="timeline">${g.steps.map(([i, t, d, tip, href], k) => `<div class="tl-step"><div class="tl-num">${k + 1}</div><div class="card tl-card">
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:8px"><span class="ic ${m ? "teal" : "blue"}" style="width:36px;height:36px;border-radius:10px;display:grid;place-items:center">${icon(i).replace("<svg ", '<svg width="18" height="18" ')}</span><h2 style="margin:0">${t}</h2></div>
      <p style="margin:0 0 10px;color:var(--ink-2)">${d}</p><div class="tip">${icon("info")}<span>${tip}</span></div>
      ${mine ? `<a class="btn sm" href="${href}" style="margin-top:12px">Ouvrir cette page</a>` : ""}</div></div>`).join("")}</div>
    <div class="grid g2 mt">
      <div class="card"><h2>${m ? "Documents à préparer" : "Ce que vous trouverez dans un dossier"}</h2>${g.docs.map(([t, d]) => `<div class="factor" style="display:block"><b>${t}</b><div class="small muted">${d}</div></div>`).join("")}</div>
      <div class="card"><h2>Lexique</h2>${g.glossary.map(([t, d]) => `<div class="factor" style="display:block"><b>${t}</b><div class="small muted">${d}</div></div>`).join("")}</div>
    </div>
    <div class="card mt"><h2>Questions fréquentes</h2>${g.faq.map(([q, a]) => `<details class="faq"><summary>${q}</summary><p>${a}</p></details>`).join("")}</div>
    <p class="small muted" style="text-align:center;margin-top:24px">${m ? "Vous êtes un établissement de crédit ?" : "Vous êtes commerçant ?"} <a href="#/guide/${SLUG_OF[other]}">Lire le guide ${m ? "établissement" : "commerçant"}</a></p>
  </div>`;
}

// ------------------------------------------------------------------ graphiques
if (window.Chart) {
  Chart.defaults.font.family = "Plex, Segoe UI, sans-serif";
  Chart.defaults.color = "#64748b";
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
}
function monthlyChart(canvas, a) {
  const ms = a.monthly;
  const c = new Chart(canvas, {
    data: {
      labels: ms.map((m) => m.month),
      datasets: [
        { type: "bar", label: "Chiffre d'affaires", data: ms.map((m) => m.ventes), order: 3, borderRadius: 0, maxBarThickness: 30,
          backgroundColor: ms.map((m) => (m.has_pnl ? "#1d4e89" : "#d9dee5")) },
        { type: "line", label: "Résultat net", data: ms.map((m) => m.resultat_net), borderColor: "#e06000", backgroundColor: "#e06000", pointRadius: 2.5, borderWidth: 2, order: 1 },
        { type: "line", label: "Trésorerie nette", data: ms.map((m) => m.tresorerie_nette_constatee), borderColor: "#0f7a55", backgroundColor: "#0f7a55", borderDash: [5, 4], pointRadius: 0, borderWidth: 2, order: 2 },
      ],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top", align: "end", labels: { boxWidth: 8, boxHeight: 8, font: { size: 12 }, padding: 16 } },
        tooltip: { backgroundColor: "#0b2545", padding: 10, cornerRadius: 3, titleFont: { weight: "600" }, bodySpacing: 5,
          callbacks: { label: (x) => ` ${x.dataset.label} : ${money(x.parsed.y)}`, afterBody: (items) => { const m = ms[items[0].dataIndex]; return [m.var_mom !== null ? `Vs mois précédent : ${signed(m.var_mom)}` : "", m.var_yoy !== null ? `Vs même mois N-1 : ${signed(m.var_yoy)}` : ""].filter(Boolean); } } } },
      scales: { y: { grid: { color: "#eef2f7" }, border: { display: false }, ticks: { callback: (v) => mfcfa(v), font: { size: 11 } } },
        x: { grid: { display: false }, border: { display: false }, ticks: { font: { size: 11 }, maxRotation: 0, autoSkipPadding: 14 } } },
    },
  });
  charts.push(c);
}
function sparkline(values, color) {
  const v = values.filter((x) => x !== null && x !== undefined);
  if (v.length < 2) return "";
  const w = 300, h = 46, min = Math.min(...v), max = Math.max(...v), span = max - min || 1;
  const pts = v.map((y, i) => [(i / (v.length - 1)) * w, h - 4 - ((y - min) / span) * (h - 8)]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.8" vector-effect="non-scaling-stroke"/></svg>`;
}

const scoreColor = (score, capped) => (score === null ? "#98a2b3" : capped ? "#d98e04" : score >= 80 ? "#0f7a55" : score >= 60 ? "#d98e04" : "#b42318");
const verdictShort = (s) => (s.score === null ? "Non calculable" : s.capped || (s.score >= 60 && s.score < 80) ? "À examiner" : s.score >= 80 ? "Favorable" : "Risque élevé");
const verdictClass = (score, capped) => (score === null ? "warn" : capped ? "warn" : score >= 80 ? "good" : score >= 60 ? "warn" : "bad");
function scoreRing(score, capped = false, size = 148, stroke = 12) {
  const s = score ?? 0, r = (size - stroke) / 2, C = 2 * Math.PI * r, col = scoreColor(score, capped);
  return `<div class="score-ring" style="width:${size}px;height:${size}px"><svg width="${size}" height="${size}"><circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="#eef2f7" stroke-width="${stroke}" fill="none"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="${col}" stroke-width="${stroke}" fill="none" stroke-linecap="round" stroke-dasharray="${(C * s) / 100} ${C}"/></svg>
    <div class="center"><b style="color:${col}">${score === null ? "-" : Math.round(s)}</b><span class="muted small">sur 100</span></div></div>`;
}
function miniRing(score, capped) {
  const s = score ?? 0, r = 23, C = 2 * Math.PI * r, col = scoreColor(score, capped);
  return `<div class="mini-ring"><svg width="56" height="56"><circle cx="28" cy="28" r="${r}" stroke="#eef2f7" stroke-width="6" fill="none"/><circle cx="28" cy="28" r="${r}" stroke="${col}" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="${(C * s) / 100} ${C}"/></svg><b style="color:${col}">${score === null ? "-" : Math.round(s)}</b></div>`;
}
const noteColor = (n) => (n === null ? "#98a2b3" : n >= 75 ? "#0f7a55" : n >= 50 ? "#d98e04" : "#b42318");

function alertsHtml(alerts, empty = "Aucune anomalie détectée par les contrôles programmés.") {
  if (!alerts.length) return `<div class="empty-ok">${icon("check").replace("<svg ", '<svg width="22" height="22" ')}${empty}</div>`;
  return alerts.map((x) => `<div class="alert-item ${x.severity}"><span class="aic">${icon(x.severity === "info" ? "info" : "alert")}</span><div style="min-width:0">
    <div class="title">${esc(x.title)} <span class="chip ${x.severity}">${SEV[x.severity]}</span></div><div class="reason">${esc(x.reason)}</div>
    ${x.explanation ? `<div class="expl">${esc(x.explanation)}</div>` : ""}<div class="method">Méthode : ${esc(x.method)}${x.period ? " · période " + esc(x.period) : ""}</div></div></div>`).join("");
}

function kpis(a) {
  const R = Object.fromEntries(a.ratios.map((r) => [r.key, r]));
  const tn = a.monthly.filter((m) => m.tresorerie_nette_constatee !== null).slice(-1)[0]?.tresorerie_nette_constatee ?? null;
  const evo = R.evol_ca_trimestrielle.value, mn = R.marge_nette.value;
  return `<div class="grid g4">
    <div class="card kpi"><span class="ic blue">${icon("coins")}</span><div><div class="label">CA 12 derniers mois</div><div class="value">${mfcfa(a.ttm.ventes)}</div><div class="sub">${a.coverage.annualised ? "annualisé (moins de 12 mois)" : "FCFA · " + a.coverage.ttm_months[0] + " à " + a.coverage.ttm_months.slice(-1)[0]}</div></div></div>
    <div class="card kpi"><span class="ic ${evo === null || evo >= 0 ? "teal" : "red"}">${icon(evo === null || evo >= 0 ? "trend" : "trendDown")}</span><div><div class="label">Évolution trimestrielle</div><div class="value">${evo === null ? "-" : signed(evo)}</div><div class="sub">dernier trimestre complet vs précédent</div></div></div>
    <div class="card kpi"><span class="ic ${mn === null || mn >= 0 ? "teal" : "red"}">${icon("percent")}</span><div><div class="label">Marge nette</div><div class="value">${mn === null ? "-" : pct(mn)}</div><div class="sub">résultat net / chiffre d'affaires</div></div></div>
    <div class="card kpi"><span class="ic ${tn === null || tn >= 0 ? "teal" : "red"}">${icon("wallet")}</span><div><div class="label">Trésorerie nette</div><div class="value" style="color:${tn !== null && tn < 0 ? "var(--red)" : "inherit"}">${mfcfa(tn)}</div><div class="sub">caisse + banque - découverts · ${esc(a.coverage.last_balance || "-")}</div></div></div>
  </div>`;
}

// ------------------------------------------------------------------ COMMERÇANT
function onboarding(a, shares, docsCount) {
  const steps = [
    ["Importer vos documents", docsCount > 0, "#/m/documents"],
    ["Vérifier les valeurs extraites des PDF", !a.empty && !(a.coverage.status_counts.extrait > 0), "#/m/donnees"],
    ["Relire les points à vérifier", !a.empty, "#/m/tableau"],
    ["Autoriser un établissement à consulter votre dossier", shares.some((x) => !x.revoked_at), "#/m/partage"],
  ];
  const done = steps.filter((x) => x[1]).length;
  if (done === steps.length) return "";
  return `<div class="card onboard"><div class="card-head"><div><h2 style="margin:0">Bien démarrer</h2><p class="small muted" style="margin:4px 0 0">${done} étape(s) sur ${steps.length} · <a href="#/guide/commercant">lire le guide</a></p></div>
    <div class="bar" style="width:180px"><span style="width:${(done / steps.length) * 100}%;background:var(--teal-2)"></span></div></div>
    <div class="onboard-steps">${steps.map(([t, ok, href], k) => `<a href="${href}" class="ob-step ${ok ? "done" : ""}"><span class="ob-check">${ok ? icon("check") : k + 1}</span><span>${t}</span></a>`).join("")}</div></div>`;
}

async function viewMerchantDashboard(cid) {
  const [a, shares, docs] = await Promise.all([api(`/api/companies/${cid}/analysis`), api(`/api/companies/${cid}/shares`), api(`/api/companies/${cid}/documents`)]);
  const ob = onboarding(a, shares, docs.length);
  if (a.empty) {
    app().innerHTML = `<div class="page-head"><div><div class="eyebrow">${icon("dashboard").replace("<svg ", '<svg width="14" height="14" ')}Tableau de bord</div><h1>${esc(ME.companies[0].name)}</h1><p class="sub">Votre dossier est vide.</p></div></div>
    ${ob}
    <div class="card mt" style="text-align:center;padding:48px 24px"><div class="dropzone" style="border:0;background:none;padding:0;cursor:default"><div class="dz-ic">${icon("upload")}</div></div>
    <h2 style="font-size:20px">Commencez par importer vos documents</h2>
    <p class="muted" style="max-width:560px;margin:0 auto 22px">Vous avez un logiciel comptable ? Exportez vos états financiers, votre balance ou votre grand livre. Sinon, importez votre journal de caisse / mobile money ou les états préparés par votre comptable.</p>
    <div class="row" style="justify-content:center"><a class="btn primary" href="#/m/documents">${icon("upload")}Importer des documents</a><a class="btn" href="#/guide/commercant">${icon("book")}Lire le guide</a></div></div>`;
    return;
  }
  const extr = a.coverage.status_counts.extrait || 0;
  const pending = a.alerts.filter((x) => x.severity !== "info");
  app().innerHTML = `
  <div class="page-head"><div><div class="eyebrow">${icon("dashboard").replace("<svg ", '<svg width="14" height="14" ')}Tableau de bord</div><h1>${esc(a.company.name)}</h1>
    <p class="sub">${esc(a.company.sector || "")} · ${esc(a.company.city || "")} · données de ${a.coverage.first_month} à ${a.coverage.last_month}</p></div>
  <div class="row"><a class="btn" href="#/m/documents">${icon("upload")}Importer</a><a class="btn primary" href="#/m/partage">${icon("shield")}Partager mon dossier</a></div></div>
  ${ob ? ob + '<div style="height:18px"></div>' : ""}
  ${extr ? `<div class="notice warn" style="margin-bottom:18px">${icon("eye")}<span>${extr} valeur(s) ont été <b>extraites automatiquement</b> d'un PDF et ne sont pas encore vérifiées. <a href="#/m/donnees">Les vérifier</a></span></div>` : ""}
  ${kpis(a)}
  <div class="grid g3 mt">
    <div class="card span2"><div class="card-head"><h2>Évolution mensuelle</h2><span class="muted small">FCFA</span></div><div class="chart-box"><canvas id="ch"></canvas></div></div>
    <div class="card"><div class="card-head"><h2>À vérifier avant transmission</h2><span class="chip ${pending.length ? "attention" : "good"}">${pending.length}</span></div>
      <p class="muted small" style="margin-top:-6px">Ces signaux seront visibles par l'institution financière. Expliquez-les ou corrigez vos données.</p>
      <div style="max-height:330px;overflow:auto;padding-right:2px">${alertsHtml(pending, "Aucun point bloquant détecté.")}</div></div>
  </div>
  <div class="card mt"><div class="card-head"><h2>Mes indicateurs</h2><span class="muted small">calculés sur 12 mois glissants</span></div>${ratiosTable(a.ratios.filter((r) => !r.key.startsWith("dscr")))}</div>`;
  monthlyChart($("#ch"), a);
}

function importResultCard(x) {
  return `<div class="card" style="padding:18px;margin-bottom:12px"><div class="row" style="justify-content:space-between;align-items:center">
    <div style="display:flex;gap:12px;align-items:center"><span class="ic ${x.n_values || x.n_transactions ? "teal" : "amber"}" style="width:38px;height:38px;border-radius:10px;display:grid;place-items:center">${icon(x.n_values || x.n_transactions ? "check" : "alert").replace("<svg ", '<svg width="18" height="18" ')}</span>
    <div><b>${esc(x.filename)}</b><div class="small muted">${KIND[x.kind] || esc(x.kind)} · ${x.n_values} valeur(s)${x.n_transactions ? ` · ${x.n_transactions} opération(s)` : ""}${x.periods ? ` · ${x.periods[0]} à ${x.periods[1]}` : ""}</div></div></div>
    <div>${Object.entries(x.status_summary || {}).map(([s, n]) => `<span class="chip ${s}">${n} ${STATUS[s]}</span>`).join(" ")}</div></div>
    ${x.unmatched?.length ? `<div class="notice warn" style="margin-top:12px">${icon("alert")}<span>Postes non reconnus (non additionnés) : ${x.unmatched.map(esc).join(", ")}</span></div>` : ""}
    ${(x.warnings || []).map((w) => `<div class="notice ${/authentique/.test(w) ? "ok" : "warn"}" style="margin-top:10px">${icon(/authentique/.test(w) ? "check" : "alert")}<span>${esc(w)}</span></div>`).join("")}
    ${x.status_summary?.extrait ? `<p class="small" style="margin:10px 0 0"><a href="#/m/donnees">Vérifier les valeurs extraites</a></p>` : ""}</div>`;
}

async function viewDocuments(cid, lastResults = "") {
  const [docs, demo] = await Promise.all([api(`/api/companies/${cid}/documents`), api("/api/demo-files")]);
  app().innerHTML = `
  <div class="page-head"><div><div class="eyebrow">${icon("upload").replace("<svg ", '<svg width="14" height="14" ')}Documents</div><h1>Importer mes documents</h1><p class="sub">PDF, XLSX ou CSV : états financiers, balance générale, grand livre, journal de caisse ou dossier CreditWise.</p></div></div>
  <div class="grid g3">
    <div class="span2 stack">
      <label class="dropzone" id="dz"><input type="file" id="file" multiple accept=".pdf,.xlsx,.csv" hidden>
        <div class="dz-ic">${icon("upload")}</div><b style="font-size:15px">Glissez-déposez vos fichiers ici</b><div class="muted small" style="margin-top:4px">ou <span style="color:var(--blue);font-weight:600">parcourez votre ordinateur</span>, plusieurs fichiers à la fois</div>
        <div style="margin-top:14px;display:flex;gap:6px;justify-content:center"><span class="chip plain neutral">PDF</span><span class="chip plain neutral">XLSX</span><span class="chip plain neutral">CSV</span></div></label>
      <div id="results">${lastResults}</div>
      <div class="card"><div class="card-head"><h2>Documents importés</h2><span class="chip plain neutral">${docs.length}</span></div>${docs.length ? `<div class="table-wrap"><table><thead><tr><th>Fichier</th><th>Type reconnu</th><th class="num">Valeurs</th><th class="num">Opérations</th><th>Importé le</th><th></th></tr></thead><tbody>
      ${docs.map((d) => `<tr><td><div style="display:flex;gap:10px;align-items:center"><span style="color:var(--muted)">${icon("file").replace("<svg ", '<svg width="18" height="18" ')}</span><div><b style="font-weight:600">${esc(d.filename)}</b>${d.warnings.length ? `<div class="muted small">${d.warnings.map(esc).join("<br>")}</div>` : ""}</div></div></td><td><span class="chip plain neutral">${KIND[d.kind] || esc(d.kind)}</span></td>
      <td class="num">${d.n_values}</td><td class="num">${d.n_transactions}</td><td class="small muted">${esc(d.uploaded_at.slice(0, 16))}</td>
      <td><button class="btn sm ghost danger" data-del="${d.id}">Supprimer</button></td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">Aucun document pour le moment.</p>`}</div>
    </div>
    <div class="stack">
      <div class="card"><h2>Fichiers d'exemple</h2><p class="muted small" style="margin-top:-6px">Commerçants fictifs. Téléchargez puis déposez-les à gauche.</p>
        ${["A", "B", "C"].map((k) => `<div class="small" style="font-weight:650;margin:14px 0 6px;color:var(--ink-2)">Commerçant ${k}</div>` + demo.filter((f) => f.company === k).map((f) => `<a class="factor" href="${f.url}" download style="color:var(--ink)"><span style="display:flex;gap:8px;align-items:center">${icon("file").replace("<svg ", '<svg width="16" height="16" style="color:var(--muted)" ')}${esc(f.name)}</span>${icon("download").replace("<svg ", '<svg width="15" height="15" style="color:var(--blue)" ')}</a>`).join("")).join("")}</div>
      <div class="card"><h2>Formats reconnus</h2>
        <ul class="small muted" style="padding-left:18px;margin:0;line-height:1.9">
          <li>Tableau « poste × mois » (export logiciel)</li><li>Format long : periode_debut, periode_fin, poste, montant</li>
          <li>Balance : periode, compte, intitule, debit, credit</li><li>Grand livre : date, reference, tiers, libelle, compte, debit, credit</li>
          <li>PDF texte avec tableaux (lecture automatique, à vérifier)</li><li>Photos de reçus : prévu après le prototype (OCR)</li></ul></div>
    </div>
  </div>`;
  const dz = $("#dz"), input = $("#file");
  const send = async (files) => {
    if (!files.length) return;
    const fd = new FormData(); [...files].forEach((f) => fd.append("files", f));
    $("#results").innerHTML = `<div class="card loading" style="padding:28px"><span class="spinner"></span>Lecture de ${files.length} fichier(s)</div>`;
    try {
      const r = await api(`/api/companies/${cid}/documents`, { method: "POST", body: fd });
      toast("Import terminé"); await viewDocuments(cid, r.results.map(importResultCard).join(""));
    } catch (e) { $("#results").innerHTML = `<div class="notice warn">${icon("alert")}<span>${esc(e.message)}</span></div>`; }
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
  const filter = counts.extrait ? "extrait" : "";
  app().innerHTML = `
  <div class="page-head"><div><div class="eyebrow">${icon("table").replace("<svg ", '<svg width="14" height="14" ')}Données</div><h1>Données financières normalisées</h1><p class="sub">Chaque valeur conserve sa source, sa période et son niveau de fiabilité. Une valeur extraite automatiquement doit être vérifiée.</p></div></div>
  <div class="grid g4" style="margin-bottom:18px">${["declare", "extrait", "verifie", "estime"].map((s) => `<div class="card kpi" style="padding:16px"><div><div class="label"><span class="chip ${s}">${STATUS[s]}</span></div><div class="value" style="font-size:22px;margin-top:8px">${nf0.format(counts[s] || 0)}</div></div></div>`).join("")}</div>
  <div class="card">
    <div class="row" style="margin-bottom:16px">
      <div class="field"><label>Statut</label><select id="st"><option value="">Tous (${vals.length})</option>${Object.entries(counts).map(([s, n]) => `<option value="${s}" ${s === filter ? "selected" : ""}>${STATUS[s]} (${n})</option>`).join("")}</select></div>
      <div class="field"><label>Document</label><select id="doc"><option value="">Tous</option>${docs.map(([id, n]) => `<option value="${id}">${esc(n)}</option>`).join("")}</select></div>
      <div class="field"><label>Recherche (poste ou mois)</label><input id="q" placeholder="ex. trésorerie, 2026-03"></div>
      <button class="btn teal" id="verifyDoc">${icon("check")}Valider les valeurs extraites affichées</button>
    </div>
    <div class="table-wrap"><table><thead><tr><th>Période</th><th>Poste</th><th class="num">Montant</th><th>Statut</th><th>Source</th><th>Libellé d'origine</th><th></th></tr></thead><tbody id="tb"></tbody></table></div>
    <p class="muted small" id="cnt" style="margin:10px 0 0"></p>
  </div>`;
  const draw = () => {
    const st = $("#st").value, dId = $("#doc").value, q = $("#q").value.toLowerCase();
    const rows = vals.filter((v) => (!st || v.status === st) && (!dId || String(v.document_id) === dId) && (!q || (v.item_label + v.period_end).toLowerCase().includes(q)));
    $("#tb").innerHTML = rows.slice(0, 400).map((v) => `<tr><td class="small">${v.period_start.slice(0, 7)}${v.period_start.slice(0, 7) !== v.period_end.slice(0, 7) ? " à " + v.period_end.slice(0, 7) : ""}</td>
      <td style="font-weight:500">${esc(v.item_label)}</td><td class="num">${money(v.amount)}</td><td><span class="chip ${v.status}">${STATUS[v.status]}</span>${v.confidence !== null && v.confidence < 0.9 ? `<div class="small muted">confiance ${Math.round(v.confidence * 100)} %</div>` : ""}</td>
      <td class="small">${esc(v.source_name)}</td><td class="small muted">${esc(v.source_label || "")}${v.comment ? `<div>${esc(v.comment)}</div>` : ""}</td>
      <td><button class="btn sm" data-edit="${v.id}" data-amount="${v.amount}">Corriger</button></td></tr>`).join("");
    $("#cnt").textContent = `${rows.length} valeur(s)${rows.length > 400 ? ", 400 premières affichées" : ""}`;
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
  <div class="page-head"><div><div class="eyebrow">${icon("shield").replace("<svg ", '<svg width="14" height="14" ')}Partage et accès</div><h1>Vous gardez la main sur vos données</h1><p class="sub">Vous décidez quelle institution peut consulter votre dossier. Chaque accès est tracé.</p></div></div>
  <div class="grid g2">
    <div class="stack">
      <div class="card"><h2>Institutions financières</h2>
        ${inst.map((i) => { const s = active.find((x) => x.institution_user_id === i.id);
          return `<div class="row" style="justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--line-2)"><div style="display:flex;gap:12px;align-items:center"><span class="avatar" style="background:#0b1f33">${initials(i.organisation || i.display_name)}</span><div><b>${esc(i.organisation || i.display_name)}</b><div class="small muted">${esc(i.display_name)}</div></div></div>
          ${s ? `<div style="display:flex;gap:8px;align-items:center"><span class="chip good">Autorisée · ${esc(s.granted_at.slice(0, 10))}</span><button class="btn sm ghost danger" data-revoke="${s.id}">Retirer</button></div>` : `<button class="btn sm primary" data-share="${i.id}">Autoriser l'accès</button>`}</div>`; }).join("")}</div>
      <div class="card"><div style="display:flex;gap:14px;align-items:flex-start"><span class="ic blue" style="width:44px;height:44px;border-radius:12px;display:grid;place-items:center;flex:none">${icon("lock").replace("<svg ", '<svg width="20" height="20" ')}</span>
        <div><h2 style="margin-bottom:6px">Dossier financier PDF sécurisé</h2><p class="small muted" style="margin:0">Synthèse lisible + données normalisées <b>signées (HMAC-SHA256)</b> en pièce jointe. L'institution peut le téléverser dans CreditWise : toute modification invalide la signature.</p></div></div>
        <div class="row" style="margin-top:16px"><div class="field"><label>Mot de passe d'ouverture (facultatif, AES-256)</label><input id="pw" type="password" placeholder="à communiquer séparément"></div>
        <button class="btn primary" id="exp">${icon("download")}Générer le PDF</button></div></div>
    </div>
    <div class="card"><div class="card-head"><h2>Journal des accès</h2><span class="chip plain neutral">${log.length}</span></div><div class="table-wrap" style="max-height:520px"><table><thead><tr><th>Date</th><th>Qui</th><th>Action</th></tr></thead><tbody>
      ${log.map((l) => `<tr><td class="small muted" style="white-space:nowrap">${esc(l.at.slice(0, 16))}</td><td class="small">${l.role === "institution" ? `<span class="chip plain declare">${esc(l.organisation || l.display_name)}</span>` : "Vous"}</td><td class="small">${esc(ACTIONS[l.action] || l.action)}${l.detail ? ` <span class="muted">(${esc(l.detail)})</span>` : ""}</td></tr>`).join("")}
    </tbody></table></div></div>
  </div>`;
  $$("[data-share]").forEach((b) => (b.onclick = async () => { await api(`/api/companies/${cid}/shares`, { json: { institution_id: +b.dataset.share } }); toast("Accès autorisé"); viewSharing(cid); }));
  $$("[data-revoke]").forEach((b) => (b.onclick = async () => { if (!confirm("Retirer l'accès de cette institution ?")) return; await api(`/api/shares/${b.dataset.revoke}`, { method: "DELETE" }); toast("Accès retiré"); viewSharing(cid); }));
  $("#exp").onclick = () => download(`/api/companies/${cid}/dossier.pdf`, "Dossier_CreditWise.pdf", { json: { password: $("#pw").value || null } }).then(() => setTimeout(() => viewSharing(cid), 500));
}

// ------------------------------------------------------------------ INSTITUTION
const decisionChip = (q) => `<span class="chip ${q.decision ? (q.decision.decision.startsWith("Accord") ? "good" : q.decision.decision.startsWith("Refus") ? "bad" : "warn") : "neutral"}">${esc(q.decision ? q.decision.decision : "En analyse")}</span>`;

async function viewDossiers() {
  const ds = await api("/api/dossiers");
  const nReq = ds.reduce((n, d) => n + d.requests.length, 0), nDec = ds.reduce((n, d) => n + d.requests.filter((q) => q.decision).length, 0);
  const amount = ds.reduce((n, d) => n + d.requests.reduce((m, q) => m + q.amount, 0), 0);
  app().innerHTML = `<div class="page-head"><div><div class="eyebrow">${icon("folder").replace("<svg ", '<svg width="14" height="14" ')}Portefeuille</div><h1>Dossiers de crédit</h1><p class="sub">Dossiers partagés par les commerçants ou téléversés par votre institution.</p></div>
    <a class="btn primary" href="#/i/televerser">${icon("plus")}Téléverser un dossier</a></div>
    <div class="grid g4" style="margin-bottom:20px">
      <div class="card kpi"><span class="ic blue">${icon("folder")}</span><div><div class="label">Dossiers</div><div class="value">${ds.length}</div><div class="sub">accessibles à votre institution</div></div></div>
      <div class="card kpi"><span class="ic amber">${icon("eye")}</span><div><div class="label">Demandes en analyse</div><div class="value">${nReq - nDec}</div><div class="sub">sur ${nReq} demande(s)</div></div></div>
      <div class="card kpi"><span class="ic teal">${icon("check")}</span><div><div class="label">Décisions rendues</div><div class="value">${nDec}</div><div class="sub">motivées et tracées</div></div></div>
      <div class="card kpi"><span class="ic blue">${icon("coins")}</span><div><div class="label">Montant demandé</div><div class="value">${mfcfa(amount)}</div><div class="sub">FCFA, toutes demandes</div></div></div>
    </div>
    <div class="grid g3" id="cards">${ds.map((d) => `<div class="card dossier-card" data-c="${d.id}" data-r="${d.requests[0]?.id || ""}">
      <div class="dc-top">
        <div style="display:flex;gap:12px;align-items:center"><span class="co-badge" style="background:${colorFor(d.id)}">${initials(d.name)}</span>
          <div style="min-width:0"><div style="font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(d.name)}</div><div class="muted small">${esc(d.sector || "-")} · ${esc(d.city || "-")}</div></div></div>
        <div class="score-slot"><div class="dc-score"><div class="mini-ring" style="display:grid;place-items:center"><span class="spinner"></span></div><span class="muted small">Calcul en cours</span></div><div style="height:60px"></div></div>
      </div>
      <div class="dc-bottom">${d.requests.length ? d.requests.map((q) => `<div class="row small" style="justify-content:space-between;align-items:center"><span><b>${money(q.amount)}</b> <span class="muted">· ${q.duration_months} mois</span></span>${decisionChip(q)}</div>`).join("") : `<div class="small muted">Aucune demande de crédit</div>`}
        <div class="small muted" style="margin-top:8px">${d.access === "partage" ? "Partagé par le commerçant" : "Téléversé par l'institution"}</div></div>
    </div>`).join("") || `<div class="card" style="grid-column:1/-1;text-align:center;padding:40px"><h2>Aucun dossier pour le moment</h2>
      <p class="muted">Les dossiers apparaissent ici dès qu'un commerçant vous autorise, ou quand vous téléversez un dossier PDF qu'il vous a transmis.</p>
      <div class="row" style="justify-content:center"><a class="btn primary" href="#/i/televerser">${icon("upload")}Téléverser un dossier</a><a class="btn" href="#/guide/microfinance">${icon("book")}Lire le guide</a></div></div>`}</div>`;
  $$(".dossier-card").forEach((el) => (el.onclick = () => (location.hash = `#/i/dossier/${el.dataset.c}${el.dataset.r ? "/" + el.dataset.r : ""}`)));
  for (const el of $$(".dossier-card")) {
    api(`/api/companies/${el.dataset.c}/analysis${el.dataset.r ? "?request_id=" + el.dataset.r : ""}`).then((a) => {
      if (a.empty) { $(".score-slot", el).innerHTML = `<p class="muted small" style="margin:18px 0">Aucune donnée exploitable</p>`; return; }
      const s = a.score; const nHigh = a.alerts.filter((x) => x.severity === "elevee").length;
      const col = scoreColor(s.score, s.capped);
      $(".score-slot", el).innerHTML = `<div class="dc-score">${miniRing(s.score, s.capped)}<div><span class="verdict ${verdictClass(s.score, s.capped)}" style="font-size:12px;padding:3px 10px">${verdictShort(s)}</span>
        <div class="small muted" style="margin-top:5px">PD ${a.pd.available ? pct(a.pd.pd * 100) : "n.d."} · ${nHigh ? `<span style="color:var(--red);font-weight:600">${nHigh} alerte(s) élevée(s)</span>` : "aucune alerte élevée"}</div></div></div>
        ${sparkline(a.monthly.map((m) => m.ventes), col)}`;
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
  ${groups.map(([g, ks]) => { const rows = ks.filter((k) => R[k]); return rows.length ? `<tr class="group-row"><td colspan="4">${g}</td></tr>` + rows.map((k) => { const r = R[k];
    return `<tr><td style="font-weight:500">${esc(r.label)}</td><td class="num"><b>${fmtRatio(r)}</b></td><td class="small muted">${esc(r.formula)}</td><td class="small">${r.value === null ? `<span class="nc">${esc(r.reason)}</span>` : esc(r.interpretation)}</td></tr>`; }).join("") : ""; }).join("")}
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
  const dscr = R.dscr_avec_credit.value;
  const dscrCol = dscr === null ? "var(--ink)" : dscr >= 1.25 ? "var(--teal)" : dscr >= 1 ? "var(--amber)" : "var(--red)";
  const nHigh = a.alerts.filter((x) => x.severity === "elevee").length;
  app().innerHTML = `
  <a href="#/i/dossiers" class="small" style="display:inline-flex;align-items:center;gap:4px;color:var(--muted);margin-bottom:14px">${icon("back").replace("<svg ", '<svg width="14" height="14" ')}Tous les dossiers</a>
  <div class="page-head"><div style="display:flex;gap:16px;align-items:center"><span class="co-badge" style="width:56px;height:56px;border-radius:16px;font-size:19px;background:${colorFor(cid)}">${initials(a.company.name)}</span>
    <div><h1>${esc(a.company.name)}</h1><p class="sub" style="margin-top:4px">${esc(a.company.sector || "")} · ${esc(a.company.city || "")} · ${d.access === "partage" ? "partagé par le commerçant le " + esc((d.granted_at || "").slice(0, 10)) : "dossier téléversé"}</p></div></div>
    <div class="row">${req ? `<button class="btn" id="dl">${icon("download")}Rapport PDF</button>` : ""}</div></div>

  <div class="card" style="margin-bottom:18px;padding:18px 22px"><div class="row" style="align-items:flex-end">
    <div class="field" style="min-width:250px;max-width:300px"><label>Demande de crédit</label><select id="reqsel">${d.requests.map((q) => `<option value="${q.id}" ${q.id === rid ? "selected" : ""}>#${q.id} : ${money(q.amount)} · ${q.duration_months} mois</option>`).join("")}<option value="" ${!rid ? "selected" : ""}>Sans demande</option></select></div>
    </div><div class="sim-grid" style="margin-top:16px">
    <div class="field"><label for="s_amount">Montant <b id="o_amount" aria-live="polite"></b></label><input id="s_amount" type="range" min="100000" max="10000000" step="50000" value="${cur?.amount ?? 1000000}"></div>
    <div class="field"><label for="s_dur">Durée <b id="o_dur" aria-live="polite"></b></label><input id="s_dur" type="range" min="3" max="60" step="1" value="${cur?.duration_months ?? 12}"></div>
    <div class="field"><label for="s_rate">Taux annuel <b id="o_rate" aria-live="polite"></b></label><input id="s_rate" type="range" min="0" max="30" step="0.5" value="${cur ? +(cur.annual_rate * 100).toFixed(2) : 15}"></div>
    </div><div class="row" style="margin-top:6px">
    <button class="btn" id="simbtn">${icon("bolt")}Simuler « et si »</button>
    <button class="btn ${sim ? "primary" : ""}" id="savereq">${icon("plus")}Enregistrer comme demande</button>
  </div>${sim ? `<div class="notice" style="margin-top:12px">${icon("info")}<span>Simulation : rien n'est enregistré.</span></div>` : req?.purpose ? `<div class="small muted" style="margin-top:10px">Objet : ${esc(req.purpose)}</div>` : ""}</div>

  <div class="grid g3">
    <div class="card"><div class="card-head"><h2>Score de risque</h2><span class="chip plain neutral">règles explicables</span></div>
      <div style="display:flex;gap:18px;align-items:flex-end;flex-wrap:wrap"><div class="giant" style="color:${scoreColor(s.score, s.capped)}" aria-label="Score ${s.score === null ? "non calculable" : Math.round(s.score) + " sur 100"}">${s.score === null ? "-" : Math.round(s.score)}<span style="font-size:18px;letter-spacing:0">/100</span></div><div><span class="verdict ${verdictClass(s.score, s.capped)}">${verdictShort(s)}</span><div class="small" style="margin-top:8px;color:var(--ink-2)">${esc(s.category)}</div><div class="small muted" style="margin-top:6px">${nHigh ? `<b style="color:var(--red)">${nHigh}</b> alerte(s) élevée(s) · ` : ""}${a.alerts.length} signal(aux) au total</div></div></div>
      <div class="zone" role="img" aria-label="Échelle de risque : moins de 60 risque élevé, 60 à 79 à examiner, 80 et plus favorable"><div class="z1"></div><div class="z2"></div><div class="z3"></div>${s.score === null ? "" : `<span class="rep" style="left:${s.score}%"></span>`}</div>
      <p class="small" style="margin:0 0 14px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><span style="color:var(--red)">0 à 59 : risque élevé</span><span style="color:var(--amber)">60 à 79 : à examiner</span><span style="color:var(--teal)">80 et plus : favorable</span></p>
      <div style="margin-top:18px">${s.dimensions.map((x) => `<div class="dim"><div class="top"><span>${esc(x.label)} <span class="muted">· ${x.weight * 100} %</span></span><b>${x.note === null ? "n.c." : Math.round(x.note)}</b></div><div class="bar"><span style="width:${x.note ?? 0}%;background:${noteColor(x.note)}"></span></div></div>`).join("")}</div></div>
    <div class="card"><div class="card-head"><h2>Probabilité de défaut</h2><span class="chip plain good">données réelles</span></div>${p.available ? `
      <div class="big-pd" style="color:${p.relative_to_base > 2 ? "var(--red)" : p.relative_to_base > 1 ? "var(--amber)" : "var(--teal)"}">${pct(p.pd * 100)}</div>
      <div class="small muted" style="margin-top:4px">à 1 an · <b>${p.relative_to_base.toLocaleString("fr-FR")} ×</b> le taux moyen d'entraînement (${pct(p.base_rate * 100)})</div>
      <div style="margin-top:14px">${p.factors.map((f) => `<div class="factor"><span>${esc(f.label)}${f.imputed ? ' <span class="chip plain neutral">imputé</span>' : ""}</span><span class="chip ${f.effect.startsWith("augmente") ? "bad" : "good"}">${f.effect.startsWith("augmente") ? "↑ risque" : "↓ risque"}</span></div>`).join("")}</div>
      ${p.expected_loss ? `<div class="notice" style="margin-top:14px">${icon("scale")}<span>Perte attendue <b>${money(p.expected_loss.el)}</b><br><span class="small">EL = PD × LGD (${p.expected_loss.lgd * 100} %) × EAD (${money(p.expected_loss.ead)})</span></span></div>` : ""}
      <p class="small muted" style="margin:12px 0 0">Modèle statistique appris sur des données publiques d'entreprises polonaises (UCI), pas sur des commerçants béninois. <a href="#/i/modele">Méthode et limites</a></p>`
      : `<p class="muted">${esc(p.reason)}</p>`}</div>
    <div class="card"><div class="card-head"><h2>Capacité de remboursement</h2></div>
      <div style="padding:14px 16px;border-radius:12px;background:${dscr === null ? "var(--grey-bg)" : dscr >= 1.25 ? "var(--teal-bg)" : dscr >= 1 ? "var(--amber-bg)" : "var(--red-bg)"};margin-bottom:16px">
        <div class="small" style="color:var(--ink-2);font-weight:600">DSCR avec le crédit demandé</div><div class="giant" style="color:${dscrCol};margin:6px 0">${fmtRatio(R.dscr_avec_credit)}</div>
        <div class="small muted">${dscr === null ? "" : dscr >= 1.25 ? "Échéances couvertes avec une marge" : dscr >= 1 ? "Couverture juste, sans marge de sécurité" : "Les flux ne couvrent pas les échéances"}</div></div>
      <dl class="kv">
      <dt>Flux disponible annuel (EBE - impôt)</dt><dd>${money(cr.cfads_annual)}</dd>
      <dt>Échéances actuelles (12 mois)</dt><dd>${money(cr.existing_service_annual)}</dd>
      <dt>Nouvelle mensualité</dt><dd>${money(cr.new_installment)}</dd>
      <dt>DSCR actuel</dt><dd>${fmtRatio(R.dscr_actuel)}</dd>
      <dt>Mensualité max. (DSCR 1,25)</dt><dd>${money(cr.max_installment_dscr_1_25)}</dd></dl>
      <p class="small muted" style="margin:14px 0 0">Un DSCR &gt; 1 indique une couverture théorique ; il ne suffit pas seul à approuver un crédit.</p></div>
  </div>

  <div class="card mt"><div class="card-head"><h2>Pourquoi ce score ?</h2></div><div style="display:grid;gap:8px">${s.explanations.map((e) => { const bad = /^À surveiller|plafonnée/.test(e), good = /^Atout/.test(e);
    return `<div style="display:flex;gap:10px;align-items:flex-start"><span style="color:${bad ? "var(--red)" : good ? "var(--teal)" : "var(--muted)"};margin-top:1px">${icon(bad ? "alert" : good ? "check" : "info").replace("<svg ", '<svg width="17" height="17" ')}</span><span>${esc(capitalize(e.replace(/^(À surveiller|Atout) : /, "")))}</span></div>`; }).join("")}</div></div>

  <div class="tabs" id="tabs">${[["evol", "Évolution"], ["alertes", `Anomalies · ${a.alerts.length}`], ["ratios", "Ratios"], ["score", "Détail du score"], ["couverture", "Données et documents"], ["decision", "Décision"]].map(([k, l], i) => `<button data-t="${k}" class="${i === 0 ? "active" : ""}">${l}</button>`).join("")}</div>
  <div data-p="evol"><div class="grid g3"><div class="card span2"><div class="card-head"><h2>Évolution mensuelle</h2><span class="muted small">FCFA</span></div><div class="chart-box"><canvas id="ch"></canvas></div></div>
    <div class="card"><h2>Trimestres</h2><table><thead><tr><th>Trimestre</th><th class="num">CA</th><th class="num">vs préc.</th><th class="num">vs N-1</th></tr></thead><tbody>
      ${a.quarterly.map((q) => `<tr><td>${q.quarter}${q.complete ? "" : ` <span class="chip plain neutral">${q.months}/3</span>`}</td><td class="num">${q.complete ? mfcfa(q.ventes) : "-"}</td><td class="num" style="color:${q.var_vs_prev === null ? "inherit" : q.var_vs_prev >= 0 ? "var(--teal)" : "var(--red)"}">${signed(q.var_vs_prev)}</td><td class="num">${signed(q.var_yoy)}</td></tr>`).join("")}</tbody></table>
      <p class="small muted">Les trimestres incomplets ne sont pas comparés. La comparaison avec N-1 neutralise la saisonnalité.</p></div></div>
    <div class="card mt"><h2>Détail mensuel</h2><div class="table-wrap"><table><thead><tr><th>Mois</th><th class="num">CA</th><th class="num">vs M-1</th><th class="num">vs N-1</th><th class="num">Marge commerciale</th><th class="num">Résultat net</th><th class="num">Trésorerie nette</th></tr></thead><tbody>
      ${a.monthly.slice().reverse().map((m) => `<tr><td>${m.month}${m.has_pnl ? "" : ' <span class="chip warn">sans données</span>'}</td><td class="num">${money(m.ventes)}</td><td class="num" style="color:${m.var_mom === null ? "inherit" : m.var_mom >= 0 ? "var(--teal)" : "var(--red)"}">${signed(m.var_mom)}</td><td class="num">${signed(m.var_yoy)}</td><td class="num">${money(m.marge_commerciale)}</td><td class="num" style="color:${m.resultat_net !== null && m.resultat_net < 0 ? "var(--red)" : "inherit"}">${money(m.resultat_net)}</td><td class="num" style="color:${m.tresorerie_nette_constatee !== null && m.tresorerie_nette_constatee < 0 ? "var(--red)" : "inherit"}">${money(m.tresorerie_nette_constatee)}</td></tr>`).join("")}</tbody></table></div></div></div>
  <div data-p="alertes" class="hidden"><div class="notice" style="margin-bottom:14px">${icon("info")}<span>Une anomalie est un signal qui mérite une vérification : elle ne prouve pas une fraude. Chaque alerte affiche la raison et la méthode du signalement.</span></div>${alertsHtml(a.alerts)}</div>
  <div data-p="ratios" class="hidden"><div class="card">${ratiosTable(a.ratios)}<p class="small muted" style="margin:12px 0 0">Montants annuels calculés sur 12 mois glissants (${a.coverage.ttm_months[0]} à ${a.coverage.ttm_months.slice(-1)[0]})${a.coverage.annualised ? ", <b>annualisés</b> faute de 12 mois" : ""}. Bilan au ${esc(a.coverage.last_balance || "-")}.</p></div></div>
  <div data-p="score" class="hidden"><div class="card"><div class="table-wrap" style="max-height:none"><table><thead><tr><th>Dimension</th><th>Critère</th><th class="num">Valeur</th><th class="num">Note</th><th>Règle</th></tr></thead><tbody>
    ${s.dimensions.map((dm) => dm.details.map((x, i) => `<tr>${i === 0 ? `<td rowspan="${dm.details.length}" style="background:#fbfcfe"><b>${esc(dm.label)}</b><div class="small muted">poids ${dm.weight * 100} % · note ${dm.note === null ? "n.c." : Math.round(dm.note)}</div></td>` : ""}<td>${esc(x.criterion)}</td><td class="num">${esc(x.value ?? "n.c.")}</td><td class="num" style="color:${noteColor(x.note)}"><b>${x.note === null ? "-" : Math.round(x.note)}</b></td><td class="small muted">${esc(x.rule)}</td></tr>`).join("")).join("")}
    </tbody></table></div><p class="small muted" style="margin:12px 0 0">${esc(s.weights_note)} Un critère non calculable est retiré et sa pondération redistribuée. Ce score n'est pas un modèle prédictif et ne constitue pas une décision.</p></div></div>
  <div data-p="couverture" class="hidden"><div class="grid g2">
    <div class="card"><h2>Période couverte</h2><dl class="kv"><dt>Période</dt><dd>${a.coverage.first_month} à ${a.coverage.last_month}</dd><dt>Mois de compte de résultat</dt><dd>${a.coverage.n_months_pnl}</dd>
      <dt>Mois manquants</dt><dd>${a.coverage.missing_months.join(", ") || "aucun"}</dd><dt>Dernier bilan</dt><dd>${esc(a.coverage.last_balance || "aucun")}</dd><dt>Opérations du grand livre</dt><dd>${nf0.format(a.n_transactions)}</dd>
      <dt>Fiabilité des valeurs</dt><dd>${Object.entries(a.coverage.status_counts).map(([k, v]) => `<span class="chip ${k}">${v} ${STATUS[k]}</span>`).join(" ")}</dd></dl>
      <h3 style="margin-top:22px">Documents attendus</h3>${a.checklist.map((c) => `<div class="factor"><span>${esc(c.document)}${c.note ? `<div class="small muted">${esc(c.note)}</div>` : ""}</span><span class="chip ${c.ok ? "good" : "warn"}">${c.ok ? "reçu" : "manquant"}</span></div>`).join("")}</div>
    <div class="card"><h2>Fichiers sources</h2><div class="table-wrap"><table><thead><tr><th>Fichier</th><th>Type</th><th class="num">Valeurs</th><th class="num">Opér.</th></tr></thead><tbody>${a.documents.map((x) => `<tr><td class="small" style="font-weight:500">${esc(x.filename)}</td><td class="small">${KIND[x.kind] || esc(x.kind)}</td><td class="num">${x.n_values}</td><td class="num">${x.n_transactions}</td></tr>`).join("")}</tbody></table></div>
      <h3 style="margin-top:22px">Limites de l'analyse</h3><ul class="small muted" style="padding-left:18px;line-height:1.8;margin:0">${a.limits.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div></div></div>
  <div data-p="decision" class="hidden"><div class="grid g2">
    <div class="card"><h2>Décision de l'analyste</h2>${req ? `<form id="dec"><input type="hidden" name="decision" id="decval" value="">
      <div class="dec-opts" role="group" aria-label="Choix de la décision">${[["Accordé", "Accorder"], ["Accordé sous conditions", "Accorder sous conditions"], ["Ajourné : pièces complémentaires", "Demander des pièces"], ["Refusé", "Refuser"]].map(([v, l]) => `<button type="button" class="dec-opt" data-v="${v}" aria-pressed="false">${l}<span aria-hidden="true">↗</span></button>`).join("")}</div>
      <div class="field" style="margin-top:18px">
      <label for="motif">Motif (obligatoire, conservé dans le rapport)</label><textarea id="motif" name="comment" rows="5" required minlength="5" placeholder="Ex. : DSCR de 1,41 avec le crédit, activité stable sur 24 mois ; demander les relevés bancaires des 3 derniers mois."></textarea></div>
      <button class="btn primary">${icon("check")}Enregistrer la décision</button></form><p class="small muted" style="margin:14px 0 0">La décision reste humaine : CreditWise prépare l'analyse, l'analyste habilité décide.</p>` : `<p class="muted">Sélectionnez ou créez une demande de crédit pour enregistrer une décision.</p>`}</div>
    <div class="card"><h2>Historique</h2>${req?.decision ? `<div style="display:flex;gap:12px;align-items:center;margin-bottom:12px">${decisionChip(req)}<span class="small muted">par ${esc(req.decision.analyst)} · ${esc(req.decision.decided_at.slice(0, 16))}</span></div><p style="margin:0 0 12px">${esc(req.decision.comment)}</p><p class="small muted" style="margin:0">Score au moment de la décision : ${req.decision.score === null ? "-" : Math.round(req.decision.score)} · PD : ${req.decision.pd === null ? "-" : pct(req.decision.pd * 100)}</p>` : `<p class="muted">Aucune décision enregistrée.</p>`}</div></div></div>`;

  monthlyChart($("#ch"), a);
  $$("#tabs button").forEach((b) => (b.onclick = () => { $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b)); $$("[data-p]").forEach((p) => p.classList.toggle("hidden", p.dataset.p !== b.dataset.t)); }));
  $("#reqsel").onchange = (e) => (location.hash = `#/i/dossier/${cid}${e.target.value ? "/" + e.target.value : ""}`);
  const simVals = () => ({ amount: +$("#s_amount").value, duration_months: +$("#s_dur").value, annual_rate: +$("#s_rate").value / 100 });
  $("#simbtn").onclick = () => { const v = simVals(); if (!v.amount) return toast("Indiquez un montant"); destroyCharts(); viewDossier(cid, rid, v); };
  const createReq = async () => { const v = simVals(); if (!v.amount) return toast("Indiquez un montant");
    const purpose = prompt("Objet du crédit :", "Fonds de roulement") || null;
    const r = await api("/api/requests", { json: { company_id: cid, ...v, purpose } }); toast("Demande enregistrée"); location.hash = `#/i/dossier/${cid}/${r.id}`; };
  $("#savereq").onclick = createReq;
  if ($("#dl")) $("#dl").onclick = () => download(`/api/requests/${rid}/report.pdf`, "Rapport_CreditWise.pdf");
  $$(".dec-opt").forEach((b) => (b.onclick = () => {
    $$(".dec-opt").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); $("#decval").value = b.dataset.v;
  }));
  const showSim = () => {
    $("#o_amount").textContent = money(+$("#s_amount").value); $("#o_dur").textContent = $("#s_dur").value + " mois";
    $("#o_rate").textContent = pct(+$("#s_rate").value);
  };
  ["s_amount", "s_dur", "s_rate"].forEach((id) => $("#" + id).addEventListener("input", showSim)); showSim();
  if ($("#dec")) $("#dec").onsubmit = async (e) => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    if (!f.decision) { toast("Choisissez une décision"); $(".dec-opt")?.focus(); return; }
    try { await api(`/api/requests/${rid}/decision`, { json: f }); toast("Décision enregistrée et tracée"); viewDossier(cid, rid); } catch (err) { toast(err.message); } };
}

async function viewInstitutionUpload(cid) {
  app().innerHTML = `<div class="page-head"><div><div class="eyebrow">${icon("upload").replace("<svg ", '<svg width="14" height="14" ')}Téléversement</div><h1>Téléverser un dossier reçu</h1><p class="sub">Le commerçant vous a transmis un dossier CreditWise (PDF signé) ou ses fichiers comptables : créez un dossier puis déposez-les.</p></div></div>
  <div class="grid g2"><div class="card">${cid ? `<div class="notice ok">${icon("check")}<span>Dossier #${cid} créé. Déposez les fichiers ci-dessous.</span></div>` : `<h2>1. Créer le dossier</h2><form id="nc"><div class="row"><div class="field"><label>Nom du commerce</label><input name="name" required></div><div class="field"><label>Ville</label><input name="city"></div></div>
    <div class="field" style="margin-top:14px"><label>Secteur</label><input name="sector"></div><button class="btn primary">Créer le dossier</button></form>`}
    ${cid ? `<label class="dropzone" id="dz" style="margin-top:16px"><input type="file" id="file" multiple accept=".pdf,.xlsx,.csv" hidden><div class="dz-ic">${icon("upload")}</div><b>Déposez le dossier PDF ou les fichiers</b><div class="muted small">PDF, XLSX, CSV</div></label><div id="res" style="margin-top:16px"></div>` : ""}</div>
    <div class="card"><h2>Comment ça marche ?</h2>
      ${[["download", "Le commerçant exporte son dossier depuis « Partage et accès » (mot de passe en option)."], ["lock", "Le PDF contient une synthèse lisible et les données normalisées signées (HMAC-SHA256)."], ["shield", "À l'import, CreditWise vérifie la signature : un fichier modifié est refusé."], ["check", "Les statuts d'origine (déclaré, extrait, vérifié) sont conservés."]]
        .map(([i, t], k) => `<div style="display:flex;gap:12px;align-items:flex-start;margin-bottom:14px"><span class="ic blue" style="width:34px;height:34px;border-radius:10px;display:grid;place-items:center;flex:none">${icon(i).replace("<svg ", '<svg width="16" height="16" ')}</span><div><b>Étape ${k + 1}</b><div class="small muted">${t}</div></div></div>`).join("")}
      <p class="small muted" style="margin:0">Un PDF chiffré doit être déchiffré avant import (prototype).</p></div></div>`;
  if ($("#nc")) $("#nc").onsubmit = async (e) => { e.preventDefault(); const r = await api("/api/companies", { json: Object.fromEntries(new FormData(e.target)) }); location.hash = `#/i/televerser/${r.id}`; };
  if ($("#dz")) {
    const send = async (files) => { const fd = new FormData(); [...files].forEach((f) => fd.append("files", f));
      $("#res").innerHTML = `<div class="loading" style="padding:20px"><span class="spinner"></span>Lecture des fichiers</div>`;
      const r = await api(`/api/companies/${cid}/documents`, { method: "POST", body: fd });
      $("#res").innerHTML = r.results.map(importResultCard).join("") + `<a class="btn primary" href="#/i/dossier/${cid}">Voir l'analyse</a>`; };
    $("#file").onchange = () => send($("#file").files);
    $("#dz").ondragover = (e) => { e.preventDefault(); $("#dz").classList.add("over"); };
    $("#dz").ondragleave = () => $("#dz").classList.remove("over");
    $("#dz").ondrop = (e) => { e.preventDefault(); $("#dz").classList.remove("over"); send(e.dataTransfer.files); };
  }
}

async function viewModel() {
  const c = await api("/api/model-card");
  const v = c.metrics_test;
  const best = v.complet.xgboost, base = v.complet.logistic_regression;
  app().innerHTML = `<div class="page-head"><div><div class="eyebrow">${icon("model").replace("<svg ", '<svg width="14" height="14" ')}Transparence</div><h1>Modèle et méthode</h1><p class="sub">Ce qui est calculé, comment, et ce que cela ne permet pas de conclure.</p></div></div>
  <div class="grid g4" style="margin-bottom:18px">
    <div class="card kpi"><span class="ic teal">${icon("check")}</span><div><div class="label">ROC-AUC (test)</div><div class="value">${best.roc_auc.toFixed(3).replace(".", ",")}</div><div class="sub">référence logistique : ${base.roc_auc.toFixed(3).replace(".", ",")}</div></div></div>
    <div class="card kpi"><span class="ic teal">${icon("trend")}</span><div><div class="label">PR-AUC (test)</div><div class="value">${best.pr_auc.toFixed(3).replace(".", ",")}</div><div class="sub">référence : ${base.pr_auc.toFixed(3).replace(".", ",")} · base ${pct(c.dataset.base_rate * 100)}</div></div></div>
    <div class="card kpi"><span class="ic blue">${icon("folder")}</span><div><div class="label">Entreprises réelles</div><div class="value">${nf0.format(c.dataset.rows)}</div><div class="sub">${nf0.format(c.dataset.positives)} faillites à 1 an</div></div></div>
    <div class="card kpi"><span class="ic amber">${icon("bolt")}</span><div><div class="label">Entraînement</div><div class="value">GPU</div><div class="sub"><code>--device cuda</code> · inférence sur CPU</div></div></div>
  </div>
  <div class="grid g2">
    <div class="card"><h2>Probabilité de défaut indicative (données réelles)</h2>
      <p style="margin-top:0"><b>${esc(c.dataset.name)}</b>, licence ${esc(c.dataset.license)}.<br><span class="small muted">${esc(c.dataset.citation)} · <a href="${esc(c.dataset.url)}" target="_blank" rel="noopener">source UCI</a></span></p>
      <p class="small">Cible : ${esc(c.dataset.target)}. ${esc(c.split)}. ${esc(c.missing_values)}.</p>
      <div class="table-wrap" style="max-height:none"><table><thead><tr><th>Variante</th><th>Modèle</th><th class="num">ROC-AUC</th><th class="num">PR-AUC</th><th class="num">Brier</th></tr></thead><tbody>
      ${Object.entries(v).map(([k, m]) => Object.entries(m).map(([name, x]) => `<tr><td class="small">${esc(c.variants[k])}</td><td>${name === "xgboost" ? '<span class="chip good">XGBoost · retenu</span>' : '<span class="chip plain neutral">Logistique · référence</span>'}</td><td class="num">${x.roc_auc.toFixed(3)}</td><td class="num">${x.pr_auc.toFixed(3)}</td><td class="num">${x.brier.toFixed(3)}</td></tr>`).join("")).join("")}
      </tbody></table></div>
      <h3 style="margin-top:20px">Limites</h3><ul class="small muted" style="padding-left:18px;line-height:1.8;margin:0">${c.limits.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div>
    <div class="stack">
      <div class="card"><h2>Ratios utilisés et importance</h2>
        ${Object.entries(c.feature_importance.complet).map(([k, imp]) => `<div class="dim"><div class="top"><span>${esc(c.features[k])}</span><b>${pct(imp * 100)}</b></div><div class="bar"><span style="width:${Math.min(100, imp * 450)}%;background:var(--navy)"></span></div></div>`).join("")}</div>
      <div class="card"><h2>Score à base de règles</h2><p class="small" style="margin-top:0">Score = 25 % rentabilité + 20 % liquidité + 20 % endettement + 20 % stabilité + 15 % qualité des données. Seuils explicites, chaque note est expliquée ; catégorie plafonnée à « à examiner » en cas d'alerte de fiabilité non résolue. Pondérations illustratives à valider par l'équipe Finance.</p>
        <h2 style="margin-top:18px">Détection d'anomalies</h2><p class="small" style="margin:0">Règles d'abord (doublons, dates impossibles, montants négatifs, bilan non équilibré, totaux grand livre ≠ états, postes absents, baisse prolongée, trésorerie négative), puis Z-score désaisonnalisé (|Z| ≥ 3, au moins 30 opérations). Isolation Forest testé puis écarté : sans signal sur ce volume de données.</p></div>
    </div>
  </div>`;
}
