const http = require("node:http");

if (process.argv.includes("--health")) {
  process.exit(0);
}

const port = Number.parseInt(process.env.PORT || "3000", 10);
const apiBaseUrl = process.env.FOUNDER_API_BASE_URL || "http://api:8000";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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
<style>
:root {
  color-scheme: light;
  --ink: #17201b;
  --muted: #536259;
  --line: #cbd6cf;
  --panel: #f7faf8;
  --canvas: #ffffff;
  --accent: #0f766e;
  --accent-ink: #ffffff;
  --warn: #9a3412;
  --ok: #166534;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--ink);
  background: var(--canvas);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
button, input, select {
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--ink);
  font: inherit;
}
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 12px;
  cursor: pointer;
}
button.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
button.danger { border-color: var(--warn); color: var(--warn); }
.shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(212px, 260px) 1fr;
}
aside {
  border-right: 1px solid var(--line);
  background: var(--panel);
  padding: 18px;
}
main { padding: 22px; }
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 24px;
  font-weight: 700;
}
.mark {
  width: 28px;
  height: 28px;
  border: 2px solid var(--accent);
  border-radius: 50%;
  display: inline-grid;
  place-items: center;
  color: var(--accent);
}
nav { display: grid; gap: 6px; }
nav a {
  padding: 9px 10px;
  color: var(--ink);
  border-radius: 6px;
  text-decoration: none;
}
nav a:hover, nav a:focus { background: #e7f2ef; outline: none; }
.topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding-bottom: 14px;
  margin-bottom: 18px;
}
.status {
  display: flex;
  gap: 10px;
  align-items: center;
  color: var(--muted);
  font-size: 14px;
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--ok);
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
section {
  border-top: 1px solid var(--line);
  padding-top: 16px;
  margin-top: 18px;
}
.panel {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: #fff;
}
.row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
  align-items: end;
}
label { display: grid; gap: 5px; color: var(--muted); font-size: 13px; }
input, select { width: 100%; padding: 0 10px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { border-bottom: 1px solid var(--line); padding: 8px; text-align: left; }
th { color: var(--muted); font-weight: 600; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.stage {
  display: grid;
  grid-template-columns: 34px 1fr;
  gap: 10px;
  align-items: center;
}
.stage-icon {
  width: 34px;
  height: 34px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  background: #e7f2ef;
  color: var(--accent);
  font-weight: 700;
}
pre {
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  background: #f9fbfa;
}
@media (max-width: 760px) {
  .shell { grid-template-columns: 1fr; }
  aside { border-right: 0; border-bottom: 1px solid var(--line); }
  .topbar { align-items: flex-start; flex-direction: column; }
}
</style>
</head>
<body>
<div class="shell">
<aside>
  <div class="brand"><span class="mark" aria-hidden="true">F</span><span>Founder Research</span></div>
  <nav aria-label="Research workflow">
    <a href="#dashboard">Dashboard</a>
    <a href="#credentials">Credentials</a>
    <a href="#downloads">Downloads</a>
    <a href="#metadata">Metadata Filter</a>
    <a href="#statistics">Statistics</a>
    <a href="#analysis">Portfolio Analysis</a>
    <a href="#account">Account</a>
  </nav>
</aside>
<main>
  <div class="topbar">
    <div>
      <h1>Research Workspace</h1>
      <div class="status"><span class="dot" aria-hidden="true"></span><span data-api-base="${escapedApiUrl}">API ${escapedApiUrl}</span></div>
    </div>
    <div class="actions">
      <a href="/auth/google/start"><button class="primary" type="button">Google Login</button></a>
      <button type="button" data-action="logout">Logout</button>
    </div>
  </div>

  <section id="dashboard">
    <h2>Dashboard</h2>
    <div class="grid">
      <div class="panel"><div class="stage"><span class="stage-icon">1</span><strong data-session-state>Session</strong></div><pre data-session-output>{}</pre></div>
      <div class="panel"><div class="stage"><span class="stage-icon">2</span><strong>Visible Coverage</strong></div><pre data-coverage-output>{ "items": [] }</pre></div>
      <div class="panel"><div class="stage"><span class="stage-icon">3</span><strong>Latest Analysis</strong></div><pre data-analysis-output>{}</pre></div>
    </div>
  </section>

  <section id="credentials">
    <h2>Credentials</h2>
    <form data-form="credential">
      <div class="row">
        <label>EODHD provider key<input name="provider_key" type="password" autocomplete="new-password" required></label>
        <label>Status<input name="credential_status" value="not loaded" readonly></label>
      </div>
      <div class="actions">
        <button class="primary" type="submit">Save Key</button>
        <button class="danger" type="button" data-action="delete-credential">Delete Key</button>
      </div>
    </form>
  </section>

  <section id="downloads">
    <h2>Downloads</h2>
    <form data-form="download">
      <div class="row">
        <label>Symbols<input name="symbols" placeholder="AAA.XETRA, BBB.XETRA"></label>
        <label>Run status<input name="download_status" value="idle" readonly></label>
      </div>
      <div class="actions">
        <button type="button" data-action="plan-download">Plan</button>
        <button class="primary" type="submit">Run</button>
      </div>
    </form>
  </section>

  <section id="metadata">
    <h2>Metadata Filter</h2>
    <form data-form="metadata-filter">
      <div class="row">
        <label>Name contains<input name="name_contains" placeholder="UCITS ETF"></label>
        <label>Exchange<select name="exchange"><option value="">Any</option><option>XETRA</option><option>LSE</option></select></label>
        <label>Distribution<select name="distribution_frequency"><option value="">Any</option><option>monthly</option><option>quarterly</option><option>annual</option></select></label>
      </div>
      <div class="actions"><button class="primary" type="submit">Create Selection</button></div>
    </form>
  </section>

  <section id="statistics">
    <h2>Statistics</h2>
    <div class="grid">
      <div class="panel"><strong>Univariate Statistics</strong><div class="actions"><button data-action="run-univariate-statistics">Run</button></div></div>
      <div class="panel"><strong>Univariate Filter</strong><div class="actions"><button data-action="run-univariate-filter">Apply</button></div></div>
      <div class="panel"><strong>Bivariate Statistics</strong><div class="actions"><button data-action="run-bivariate-statistics">Run</button></div></div>
      <div class="panel"><strong>Multivariate Statistics</strong><div class="actions"><button data-action="run-multivariate-statistics">Run</button></div></div>
    </div>
  </section>

  <section id="analysis">
    <h2>Portfolio Analysis</h2>
    <form data-form="analysis">
      <div class="row">
        <label>Project<input name="project_name" value="ETF Research"></label>
        <label>Objective<select name="objective"><option>minimum_variance</option><option>risk_parity</option><option>maximum_diversification</option></select></label>
      </div>
      <div class="actions">
        <button class="primary" type="submit">Analyze</button>
        <button type="button" data-action="load-report">Report</button>
      </div>
    </form>
    <table aria-label="Portfolio weights">
      <thead><tr><th>Instrument</th><th>Weight</th><th>Risk</th></tr></thead>
      <tbody data-weights-body><tr><td colspan="3">No analysis loaded</td></tr></tbody>
    </table>
  </section>

  <section id="account">
    <h2>Account</h2>
    <div class="actions">
      <button class="danger" type="button" data-action="delete-account">Delete Account Data</button>
    </div>
  </section>
</main>
</div>
<script>
const apiBaseUrl = ${JSON.stringify(apiUrl)};
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
  writeJson("[data-session-output]", session);
}
async function refreshDatasets() {
  const datasets = await apiRequest(apiRoutes.datasets);
  writeJson("[data-coverage-output]", datasets);
}
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
  writeJson("[data-session-output]", { status: "deleted" });
});
window.founderApi = { apiRequest, apiRoutes, idempotencyKey, refreshDatasets, refreshSession };
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
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(renderAppShell(apiBaseUrl));
});

server.listen(port, "0.0.0.0");

module.exports = { renderAppShell };
