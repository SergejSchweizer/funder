const http = require("node:http");
const { URL } = require("node:url");

if (process.argv.includes("--health")) {
  process.exit(0);
}

const port = Number.parseInt(process.env.PORT || "3000", 10);
const apiBaseUrl = process.env.FOUNDER_API_BASE_URL || "http://api:8000";

const funnelSteps = [
  { id: "data", label: "Data", status: "ready", href: "/data" },
  { id: "metadata", label: "Metadata", status: "not-started", href: "/metadata" },
  { id: "univariate", label: "Univariate", status: "running", href: "/univariate" },
  { id: "filter", label: "Filter", status: "warning", href: "/filter" },
  { id: "diversification", label: "Diversification", status: "stale", href: "/diversification" },
  { id: "portfolio", label: "Portfolio", status: "complete", href: "/portfolio" },
  { id: "validation", label: "Validation", status: "failed", href: "/validation" },
  { id: "report", label: "Report", status: "not-started", href: "/report" },
];

const routeSkeletons = [
  { id: "dashboard", title: "Dashboard", tone: "ready" },
  { id: "projects", title: "Projects", tone: "complete" },
  { id: "data", title: "Data", tone: "ready" },
  { id: "metadata", title: "Metadata", tone: "not-started" },
  { id: "univariate", title: "Univariate", tone: "running" },
  { id: "filter", title: "Filter", tone: "warning" },
  { id: "diversification", title: "Diversification", tone: "stale" },
  { id: "portfolio", title: "Portfolio", tone: "complete" },
  { id: "validation", title: "Validation", tone: "failed" },
  { id: "report", title: "Report", tone: "not-started" },
  { id: "settings", title: "Settings", tone: "ready" },
];

const designTokens = {
  typography: {
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
    pageTitle: "28px",
    sectionTitle: "18px",
    body: "14px",
    meta: "12px",
  },
  spacing: {
    page: "24px",
    panel: "16px",
    control: "10px",
    gap: "12px",
  },
  color: {
    canvas: "#f8fafd",
    surface: "#ffffff",
    ink: "#202124",
    muted: "#5f6368",
    line: "#dadce0",
    accent: "#1a73e8",
    accentHover: "#1765cc",
    focus: "#1a73e8",
    warning: "#f9ab00",
    danger: "#d93025",
    stale: "#b06000",
    running: "#1a73e8",
    complete: "#188038",
  },
  radius: {
    panel: "8px",
    control: "6px",
  },
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function navItem(route) {
  return `<a class="nav-link nav-link--${route.tone}" href="/${route.id}" data-route="${route.id}">
    <span class="nav-dot" aria-hidden="true"></span>
    <span>${escapeHtml(route.title)}</span>
  </a>`;
}

function funnelItem(step, index) {
  return `<a class="funnel-step funnel-step--${step.status}" href="${step.href}" data-funnel-step="${step.id}" data-state="${step.status}">
    <span class="funnel-index" aria-hidden="true">${index + 1}</span>
    <span class="funnel-copy">
      <span class="funnel-label">${escapeHtml(step.label)}</span>
      <span class="funnel-status">${escapeHtml(step.status)}</span>
    </span>
  </a>`;
}

function routePanel(route) {
  return `<section class="route-panel route-panel--${route.tone}" id="${route.id}" data-route-skeleton="${route.id}">
    <div class="route-panel__header">
      <p class="eyebrow">${escapeHtml(route.tone)}</p>
      <h2>${escapeHtml(route.title)}</h2>
    </div>
    <div class="route-panel__body">
      <div class="metric-strip" aria-label="${escapeHtml(route.title)} summary">
        <span><strong data-synthetic-count="${route.id}">0</strong><small>items</small></span>
        <span><strong>ready</strong><small>state</small></span>
        <span><strong>snapshot</strong><small>source</small></span>
      </div>
      <div class="empty-state" data-empty-state="${route.id}">No user-owned run is loaded for this route.</div>
    </div>
  </section>`;
}

function renderStyles() {
  return `<style>
:root {
  color-scheme: light;
  --font-family: ${designTokens.typography.fontFamily};
  --page-title: ${designTokens.typography.pageTitle};
  --section-title: ${designTokens.typography.sectionTitle};
  --body: ${designTokens.typography.body};
  --meta: ${designTokens.typography.meta};
  --space-page: ${designTokens.spacing.page};
  --space-panel: ${designTokens.spacing.panel};
  --space-control: ${designTokens.spacing.control};
  --gap: ${designTokens.spacing.gap};
  --canvas: ${designTokens.color.canvas};
  --surface: ${designTokens.color.surface};
  --ink: ${designTokens.color.ink};
  --muted: ${designTokens.color.muted};
  --line: ${designTokens.color.line};
  --accent: ${designTokens.color.accent};
  --accent-hover: ${designTokens.color.accentHover};
  --focus: ${designTokens.color.focus};
  --warning: ${designTokens.color.warning};
  --danger: ${designTokens.color.danger};
  --stale: ${designTokens.color.stale};
  --running: ${designTokens.color.running};
  --complete: ${designTokens.color.complete};
  --radius-panel: ${designTokens.radius.panel};
  --radius-control: ${designTokens.radius.control};
}
* { box-sizing: border-box; }
html { background: var(--canvas); }
body {
  margin: 0;
  color: var(--ink);
  background: var(--canvas);
  font-family: var(--font-family);
  font-size: var(--body);
  line-height: 1.45;
}
a { color: inherit; }
button, input, select {
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--surface);
  color: var(--ink);
  font: inherit;
}
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 12px;
  cursor: pointer;
}
button.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
button.primary:hover {
  background: var(--accent-hover);
}
button.danger {
  border-color: var(--danger);
  color: var(--danger);
}
button:focus-visible, input:focus-visible, select:focus-visible, a:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--focus) 35%, transparent);
  outline-offset: 2px;
}
.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
}
.login-gate {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-page);
}
.login-panel {
  width: min(440px, 100%);
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--surface);
  box-shadow: 0 1px 2px rgba(60, 64, 67, .3), 0 1px 3px rgba(60, 64, 67, .15);
  padding: 22px;
  display: grid;
  gap: 14px;
}
.login-panel__copy {
  color: var(--muted);
}
.login-panel__status {
  min-height: 20px;
  color: var(--muted);
  font-size: var(--meta);
}
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: auto;
  border-right: 1px solid var(--line);
  background: #f1f3f4;
  padding: 18px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  margin-bottom: 18px;
  font-weight: 700;
}
.brand-mark {
  width: 34px;
  height: 34px;
  border: 2px solid var(--accent);
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: var(--accent);
}
.snapshot-indicator {
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--surface);
  padding: 12px;
  margin-bottom: 18px;
}
.snapshot-indicator span {
  display: block;
  color: var(--muted);
  font-size: var(--meta);
}
.nav-group {
  display: grid;
  gap: 6px;
  margin-bottom: 18px;
}
.nav-link {
  min-height: 38px;
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 0 10px;
  border-radius: var(--radius-control);
  text-decoration: none;
}
.nav-link:hover { background: #e8f0fe; }
.nav-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted);
}
.nav-link--complete .nav-dot { background: var(--complete); }
.nav-link--running .nav-dot { background: var(--running); }
.nav-link--warning .nav-dot { background: var(--warning); }
.nav-link--failed .nav-dot { background: var(--danger); }
.workspace {
  min-width: 0;
  padding: var(--space-page);
}
.topbar {
  min-height: 72px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding-bottom: 16px;
}
h1, h2, p { margin: 0; }
h1 { font-size: var(--page-title); font-weight: 720; letter-spacing: 0; }
h2 { font-size: var(--section-title); font-weight: 700; letter-spacing: 0; }
.subtle { color: var(--muted); }
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.funnel {
  display: grid;
  grid-template-columns: repeat(8, minmax(120px, 1fr));
  gap: 8px;
  margin: 18px 0;
}
.funnel-step {
  min-height: 66px;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--surface);
  padding: 10px;
  text-decoration: none;
}
.funnel-index {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #edf4f1;
  color: var(--accent);
  font-size: var(--meta);
  font-weight: 700;
}
.funnel-copy { min-width: 0; }
.funnel-label, .funnel-status {
  display: block;
  overflow-wrap: anywhere;
}
.funnel-label { font-weight: 700; }
.funnel-status { color: var(--muted); font-size: var(--meta); }
.funnel-step--complete { border-color: color-mix(in srgb, var(--complete) 40%, var(--line)); }
.funnel-step--running { border-color: color-mix(in srgb, var(--running) 50%, var(--line)); }
.funnel-step--warning { border-color: color-mix(in srgb, var(--warning) 50%, var(--line)); }
.funnel-step--failed { border-color: color-mix(in srgb, var(--danger) 50%, var(--line)); }
.funnel-step--stale { border-color: color-mix(in srgb, var(--stale) 50%, var(--line)); }
.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(300px, 0.6fr);
  gap: 16px;
  align-items: start;
}
.route-stack, .side-stack {
  display: grid;
  gap: 12px;
}
.route-panel, .control-panel {
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--surface);
  padding: var(--space-panel);
  box-shadow: 0 1px 2px rgba(60, 64, 67, .16);
}
.route-panel__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 10px;
  margin-bottom: 12px;
}
.eyebrow {
  color: var(--muted);
  font-size: var(--meta);
  text-transform: uppercase;
  letter-spacing: .08em;
}
.metric-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.metric-strip span {
  min-height: 58px;
  display: grid;
  align-content: center;
  gap: 2px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  padding: 8px;
}
.metric-strip strong { font-size: 16px; }
.metric-strip small { color: var(--muted); }
.empty-state {
  margin-top: 10px;
  color: var(--muted);
}
form {
  display: grid;
  gap: 12px;
}
label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: var(--meta);
}
input, select {
  width: 100%;
  padding: 0 var(--space-control);
}
.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 10px;
}
pre {
  max-height: 220px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: #fbfdfc;
  padding: 10px;
  color: var(--muted);
}
@media (max-width: 1040px) {
  .app-shell { grid-template-columns: 1fr; }
  .sidebar {
    position: static;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .nav-group { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
  .funnel { grid-template-columns: repeat(4, minmax(120px, 1fr)); }
  .content-grid { grid-template-columns: 1fr; }
}
@media (max-width: 620px) {
  .workspace { padding: 16px; }
  .topbar { align-items: flex-start; flex-direction: column; }
  .funnel { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-strip { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
</style>`;
}

function renderAppShell(apiUrl) {
  const escapedApiUrl = escapeHtml(apiUrl);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="founder-csrf-token" content="">
<title>Founder Research</title>
${renderStyles()}
</head>
<body>
<div class="login-gate" data-auth-gate>
  <section class="login-panel" aria-label="Founder login">
    <div class="brand"><span class="brand-mark" aria-hidden="true">F</span><span>Founder Research</span></div>
    <h1>Sign in to continue</h1>
    <p class="login-panel__copy">The research dashboard is only available after Google authentication.</p>
    <div class="actions">
      <a href="/auth/google/start"><button class="primary" type="button" aria-label="Start Google login">Google Login</button></a>
    </div>
    <p class="login-panel__status" data-auth-status>Checking session...</p>
  </section>
</div>
<div id="authenticated-root" data-authenticated-root></div>
<template id="authenticated-shell-template" data-authenticated-template>
<div class="app-shell" data-design-system-version="founder-web-shell-v1">
  <aside class="sidebar" aria-label="Founder navigation">
    <div class="brand"><span class="brand-mark" aria-hidden="true">F</span><span>Founder Research</span></div>
    <div class="snapshot-indicator" data-snapshot-indicator>
      <strong>Project snapshot</strong>
      <span>Not selected</span>
    </div>
    <nav class="nav-group" aria-label="Primary routes">
      ${routeSkeletons.map(navItem).join("")}
    </nav>
  </aside>
  <main class="workspace">
    <header class="topbar">
      <div>
        <h1>Research Workspace</h1>
        <p class="subtle" data-api-base="${escapedApiUrl}">API ${escapedApiUrl}</p>
      </div>
      <div class="actions">
        <a href="/auth/logout"><button type="button" data-action="logout">Logout</button></a>
      </div>
    </header>

    <nav class="funnel" aria-label="Persisted research funnel">
      ${funnelSteps.map(funnelItem).join("")}
    </nav>

    <div class="content-grid">
      <div class="route-stack">
        ${routeSkeletons.map(routePanel).join("")}
      </div>
      <div class="side-stack">
        <section class="control-panel" id="credentials" data-route-skeleton="credentials">
          <div class="route-panel__header"><h2>Credentials</h2><p class="eyebrow">write-only</p></div>
          <form data-form="credential">
            <div class="field-grid">
              <label>EODHD provider key<input name="provider_key" type="password" autocomplete="new-password" required></label>
              <label>Status<input name="credential_status" value="not loaded" readonly></label>
            </div>
            <div class="actions">
              <button class="primary" type="submit">Save Key</button>
              <button class="danger" type="button" data-action="delete-credential">Delete Key</button>
            </div>
          </form>
        </section>

        <section class="control-panel" id="downloads" data-route-skeleton="downloads">
          <div class="route-panel__header"><h2>Downloads</h2><p class="eyebrow">user scoped</p></div>
          <form data-form="download">
            <div class="field-grid">
              <label>Symbols<input name="symbols" placeholder="AAA.XETRA, BBB.XETRA"></label>
              <label>Run status<input name="download_status" value="idle" readonly></label>
            </div>
            <div class="actions">
              <button type="button" data-action="plan-download">Plan</button>
              <button class="primary" type="submit">Run</button>
            </div>
          </form>
        </section>

        <section class="control-panel" id="metadata-filter" data-route-skeleton="metadata-filter">
          <div class="route-panel__header"><h2>Metadata Filter</h2><p class="eyebrow">server backed</p></div>
          <form data-form="metadata-filter">
            <div class="field-grid">
              <label>Name contains<input name="name_contains" placeholder="UCITS ETF"></label>
              <label>Exchange<select name="exchange"><option value="">Any</option><option>XETRA</option><option>LSE</option></select></label>
              <label>Distribution<select name="distribution_frequency"><option value="">Any</option><option>monthly</option><option>quarterly</option><option>annual</option></select></label>
            </div>
            <div class="actions"><button class="primary" type="submit">Create Selection</button></div>
          </form>
        </section>

        <section class="control-panel" id="statistics-controls" data-route-skeleton="statistics-controls">
          <div class="route-panel__header"><h2>Statistics</h2><p class="eyebrow">API produced</p></div>
          <div class="actions">
            <button data-action="run-univariate-statistics">Univariate Statistics</button>
            <button data-action="run-univariate-filter">Univariate Filter</button>
            <button data-action="run-bivariate-statistics">Bivariate Statistics</button>
            <button data-action="run-multivariate-statistics">Multivariate Statistics</button>
          </div>
        </section>

        <section class="control-panel" id="analysis-controls" data-route-skeleton="analysis-controls">
          <div class="route-panel__header"><h2>Portfolio Analysis</h2><p class="eyebrow">no browser math</p></div>
          <form data-form="analysis">
            <div class="field-grid">
              <label>Project<input name="project_name" value="ETF Research"></label>
              <label>Objective<select name="objective"><option>minimum_variance</option><option>risk_parity</option><option>maximum_diversification</option></select></label>
            </div>
            <div class="actions">
              <button class="primary" type="submit">Analyze</button>
              <button type="button" data-action="load-report">Report</button>
            </div>
          </form>
          <pre data-analysis-output>{}</pre>
        </section>

        <section class="control-panel" id="account" data-route-skeleton="account">
          <div class="route-panel__header"><h2>Account</h2><p class="eyebrow">owned data</p></div>
          <div class="actions">
            <button class="danger" type="button" data-action="delete-account">Delete Account Data</button>
          </div>
        </section>
      </div>
    </div>
  </main>
</div>
</template>
<script>
const apiBaseUrl = "/api";
const apiRoutes = {
  session: "/session",
  credential: "/credentials/eodhd",
  datasets: "/datasets",
  downloadPlan: "/downloads/plan",
  downloadRun: "/downloads/run",
  projects: "/projects",
  selections: "/selections",
  analyses: "/analyses",
  account: "/account"
};
function csrfToken() {
  return document.querySelector('meta[name="founder-csrf-token"]').content;
}
function idempotencyKey(prefix) {
  if (globalThis.crypto && globalThis.crypto.randomUUID) {
    return prefix + "-" + globalThis.crypto.randomUUID();
  }
  return prefix + "-" + Date.now().toString(36);
}
async function apiRequest(path, options = {}) {
  const headers = Object.assign({ "accept": "application/json" }, options.headers || {});
  if (options.body) headers["content-type"] = "application/json";
  if (options.method && options.method !== "GET") headers["X-Founder-CSRF"] = csrfToken();
  const response = await fetch(apiBaseUrl + path, {
    method: options.method || "GET",
    credentials: "include",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  if (!response.ok) throw new Error("api_error_" + response.status);
  return response.json();
}
function writeJson(selector, value) {
  const target = document.querySelector(selector);
  if (target) target.textContent = JSON.stringify(value, null, 2);
}
function parseSymbols(value) {
  return value.split(",").map((symbol) => symbol.trim()).filter(Boolean);
}
async function refreshSession() {
  const session = await apiRequest(apiRoutes.session);
  writeJson("[data-analysis-output]", { session });
}
async function refreshDatasets() {
  const datasets = await apiRequest(apiRoutes.datasets);
  writeJson("[data-analysis-output]", { datasets });
}
function mountAuthenticatedShell(session) {
  const gate = document.querySelector("[data-auth-gate]");
  const root = document.querySelector("[data-authenticated-root]");
  const template = document.querySelector("[data-authenticated-template]");
  if (!root || !template || root.childElementCount > 0) return;
  root.appendChild(template.content.cloneNode(true));
  const csrfMeta = document.querySelector('meta[name="founder-csrf-token"]');
  if (csrfMeta && session && session.csrf_token) csrfMeta.content = session.csrf_token;
  if (gate) gate.hidden = true;
  writeJson("[data-analysis-output]", { session });
  bindAuthenticatedHandlers();
}
function showLoginGate() {
  const gate = document.querySelector("[data-auth-gate]");
  const status = document.querySelector("[data-auth-status]");
  if (gate) gate.hidden = false;
  if (status) status.textContent = "Google login is required before the dashboard is shown.";
}
async function initializeAuthGate() {
  try {
    const session = await apiRequest(apiRoutes.session);
    if (session && session.authenticated === true) {
      mountAuthenticatedShell(session);
      return;
    }
  } catch (_error) {
    showLoginGate();
    return;
  }
  showLoginGate();
}
function bindAuthenticatedHandlers() {
document.querySelector('[data-form="credential"]').addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const providerKey = new FormData(form).get("provider_key");
  const status = await apiRequest(apiRoutes.credential, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey("credential") },
    body: { provider_key: providerKey }
  });
  form.elements.credential_status.value = status.status;
  form.elements.provider_key.value = "";
});
document.querySelector('[data-action="delete-credential"]').addEventListener("click", async () => {
  await apiRequest(apiRoutes.credential, { method: "DELETE" });
  document.querySelector('[name="credential_status"]').value = "deleted";
});
document.querySelector('[data-action="plan-download"]').addEventListener("click", async () => {
  const symbols = parseSymbols(document.querySelector('[name="symbols"]').value);
  const plan = await apiRequest(apiRoutes.downloadPlan, { method: "POST", body: { symbols } });
  document.querySelector('[name="download_status"]').value = plan.status;
});
document.querySelector('[data-form="download"]').addEventListener("submit", async (event) => {
  event.preventDefault();
  const symbols = parseSymbols(new FormData(event.currentTarget).get("symbols"));
  const run = await apiRequest(apiRoutes.downloadRun, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey("download") },
    body: { symbols }
  });
  document.querySelector('[name="download_status"]').value = run.status;
  await refreshDatasets();
});
document.querySelector('[data-form="analysis"]').addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const project = await apiRequest(apiRoutes.projects, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey("project") },
    body: { name: new FormData(form).get("project_name") }
  });
  const selection = await apiRequest(apiRoutes.selections, {
    method: "POST",
    body: { project_id: project.project_id, name: "Current Selection", member_ids: ["example-member"] }
  });
  const analysis = await apiRequest(apiRoutes.analyses, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey("analysis") },
    body: {
      project_id: project.project_id,
      selection_id: selection.selection_id,
      settings: { objective: new FormData(form).get("objective") }
    }
  });
  writeJson("[data-analysis-output]", analysis);
});
document.querySelector('[data-action="delete-account"]').addEventListener("click", async () => {
  await apiRequest(apiRoutes.account, { method: "DELETE" });
  writeJson("[data-analysis-output]", { status: "deleted" });
});
}
window.founderApi = { apiRequest, apiRoutes, idempotencyKey, refreshDatasets, refreshSession };
initializeAuthGate();
</script>
</body>
</html>`;
}

const server = http.createServer((request, response) => {
  if (request.url === "/health") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ status: "ok" }));
    return;
  }
  if (request.url && request.url.startsWith("/api/")) {
    proxyApiRequest(request, response);
    return;
  }
  if (request.url && request.url.startsWith("/auth/")) {
    proxyAuthRequest(request, response);
    return;
  }
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(renderAppShell(apiBaseUrl));
});

server.listen(port, "0.0.0.0");

function proxyApiRequest(clientRequest, clientResponse) {
  const target = new URL(clientRequest.url.replace(/^\/api/, ""), apiBaseUrl);
  proxyRequestToTarget(clientRequest, clientResponse, target);
}

function proxyAuthRequest(clientRequest, clientResponse) {
  const target = new URL(clientRequest.url, apiBaseUrl);
  proxyRequestToTarget(clientRequest, clientResponse, target);
}

function proxyRequestToTarget(clientRequest, clientResponse, target) {
  const proxyRequest = http.request(
    target,
    {
      method: clientRequest.method,
      headers: Object.assign({}, clientRequest.headers, { host: target.host }),
    },
    (proxyResponse) => {
      clientResponse.writeHead(proxyResponse.statusCode || 502, proxyResponse.headers);
      proxyResponse.pipe(clientResponse);
    }
  );
  proxyRequest.on("error", () => {
    clientResponse.writeHead(502, { "content-type": "application/json" });
    clientResponse.end(JSON.stringify({ error: "api_unavailable" }));
  });
  clientRequest.pipe(proxyRequest);
}

module.exports = {
  designTokens,
  funnelSteps,
  proxyApiRequest,
  proxyAuthRequest,
  renderAppShell,
  routeSkeletons,
};
