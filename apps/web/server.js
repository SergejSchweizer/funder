const http = require("node:http");
const crypto = require("node:crypto");
const fs = require("node:fs");
const { URL } = require("node:url");

if (process.argv.includes("--health")) {
  process.exit(0);
}

const port = Number.parseInt(process.env.PORT || "3000", 10);
const apiBaseUrl = process.env.FOUNDER_API_BASE_URL || "http://api:8000";
const authMode = process.env.FOUNDER_AUTH_MODE || "google";
const googleClientId = process.env.FOUNDER_GOOGLE_CLIENT_ID || "";
const googleRedirectUri =
  process.env.FOUNDER_GOOGLE_REDIRECT_URI || `http://localhost:${port}/auth/google/callback`;
const googleAllowedDomain = process.env.FOUNDER_GOOGLE_ALLOWED_DOMAIN || "";
const googleAuthEndpoint =
  process.env.FOUNDER_GOOGLE_AUTH_ENDPOINT || "https://accounts.google.com/o/oauth2/v2/auth";
const googleTokenEndpoint =
  process.env.FOUNDER_GOOGLE_TOKEN_ENDPOINT || "https://oauth2.googleapis.com/token";
const googleJwksUri = process.env.FOUNDER_GOOGLE_JWKS_URI || "https://www.googleapis.com/oauth2/v3/certs";
const googleStateTtlMs = Number.parseInt(process.env.FOUNDER_GOOGLE_STATE_TTL_SECONDS || "600", 10) * 1000;
const localDevUserId = "local-google-dev-user";
const localDevCsrfToken = "valid-csrf";
const localDevGoogleEmail = (
  process.env.FOUNDER_LOCAL_DEV_GOOGLE_EMAIL || "local-google-dev-user@example.test"
).toLowerCase();
const sessionCookieName = "founder_session_user";
const csrfCookieName = "founder_csrf";
const emailCookieName = "founder_auth_email";
const providerCookieName = "founder_auth_provider";
const pendingGoogleStates = new Map();
let googleJwksCache = { expiresAt: 0, keys: [] };

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
  { id: "projects", title: "Projects", tone: "complete" },
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

function base64Url(buffer) {
  return Buffer.from(buffer).toString("base64url");
}

function randomToken(bytes = 32) {
  return base64Url(crypto.randomBytes(bytes));
}

function sha256Hex(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function stableGoogleUserId(subject) {
  return "google-" + sha256Hex(subject).slice(0, 32);
}

function localDevAuthEnabled() {
  if (authMode === "local-dev") return true;
  return false;
}

function googleAuthConfigured() {
  return Boolean(googleClientId && googleRedirectUri);
}

function privateIpv4Address(hostname) {
  const parts = hostname.split(".");
  if (parts.length !== 4) return false;
  const octets = parts.map((part) => Number.parseInt(part, 10));
  if (
    octets.some(
      (octet, index) => !Number.isInteger(octet) || String(octet) !== parts[index] || octet < 0 || octet > 255
    )
  ) {
    return false;
  }
  const [first, second] = octets;
  return (
    first === 10 ||
    first === 127 ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168)
  );
}

function googleRedirectUsesPrivateIp() {
  try {
    return privateIpv4Address(new URL(googleRedirectUri).hostname);
  } catch {
    return false;
  }
}

function applyGooglePrivateIpDeviceParams(url) {
  if (!googleRedirectUsesPrivateIp()) return;
  url.searchParams.set("device_id", "founder-" + sha256Hex(googleRedirectUri).slice(0, 32));
  url.searchParams.set("device_name", "Founder Research Local");
}

function readGoogleClientSecret() {
  if (process.env.FOUNDER_GOOGLE_CLIENT_SECRET) return process.env.FOUNDER_GOOGLE_CLIENT_SECRET;
  const secretPath = process.env.FOUNDER_GOOGLE_CLIENT_SECRET_FILE;
  if (!secretPath) return "";
  return fs.readFileSync(secretPath, "utf8").trim();
}

function pruneExpiredGoogleStates(now = Date.now()) {
  for (const [stateHash, pending] of pendingGoogleStates.entries()) {
    if (pending.expiresAt <= now || pending.consumed) pendingGoogleStates.delete(stateHash);
  }
}

function createGoogleAuthRequest() {
  pruneExpiredGoogleStates();
  const state = randomToken();
  const nonce = randomToken();
  const codeVerifier = randomToken(48);
  const codeChallenge = base64Url(crypto.createHash("sha256").update(codeVerifier).digest());
  pendingGoogleStates.set(sha256Hex(state), {
    codeVerifier,
    nonce,
    expiresAt: Date.now() + googleStateTtlMs,
    consumed: false,
  });
  const url = new URL(googleAuthEndpoint);
  url.searchParams.set("client_id", googleClientId);
  url.searchParams.set("redirect_uri", googleRedirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid email profile");
  url.searchParams.set("state", state);
  url.searchParams.set("nonce", nonce);
  url.searchParams.set("code_challenge", codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("prompt", "select_account");
  applyGooglePrivateIpDeviceParams(url);
  return url.toString();
}

async function exchangeGoogleCode(code, codeVerifier) {
  const clientSecret = readGoogleClientSecret();
  if (!clientSecret) throw new Error("google_client_secret_missing");
  const body = new URLSearchParams({
    client_id: googleClientId,
    client_secret: clientSecret,
    code,
    code_verifier: codeVerifier,
    grant_type: "authorization_code",
    redirect_uri: googleRedirectUri,
  });
  const response = await fetch(googleTokenEndpoint, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
    body,
  });
  const payload = await response.json();
  if (!response.ok || !payload.id_token) throw new Error("google_token_exchange_failed");
  return payload.id_token;
}

async function googleJwks() {
  if (googleJwksCache.expiresAt > Date.now() && googleJwksCache.keys.length > 0) {
    return googleJwksCache.keys;
  }
  const response = await fetch(googleJwksUri, { headers: { accept: "application/json" } });
  const payload = await response.json();
  if (!response.ok || !Array.isArray(payload.keys)) throw new Error("google_jwks_unavailable");
  googleJwksCache = { expiresAt: Date.now() + 3600 * 1000, keys: payload.keys };
  return googleJwksCache.keys;
}

function jsonPart(value) {
  return JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
}

async function verifyGoogleIdToken(idToken, expectedNonce) {
  const parts = idToken.split(".");
  if (parts.length !== 3) throw new Error("invalid_google_id_token");
  const [encodedHeader, encodedPayload, encodedSignature] = parts;
  const header = jsonPart(encodedHeader);
  const claims = jsonPart(encodedPayload);
  if (header.alg !== "RS256" || !header.kid) throw new Error("invalid_google_id_token_algorithm");
  const keys = await googleJwks();
  const jwk = keys.find((key) => key.kid === header.kid && key.kty === "RSA");
  if (!jwk) throw new Error("google_jwk_not_found");
  const verifier = crypto.createVerify("RSA-SHA256");
  verifier.update(`${encodedHeader}.${encodedPayload}`);
  verifier.end();
  const valid = verifier.verify(crypto.createPublicKey({ key: jwk, format: "jwk" }), Buffer.from(encodedSignature, "base64url"));
  if (!valid) throw new Error("invalid_google_id_token_signature");
  const now = Math.floor(Date.now() / 1000);
  if (!["https://accounts.google.com", "accounts.google.com"].includes(claims.iss)) {
    throw new Error("invalid_google_issuer");
  }
  if (claims.aud !== googleClientId) throw new Error("invalid_google_audience");
  if (!claims.sub) throw new Error("missing_google_subject");
  if (claims.nonce !== expectedNonce) throw new Error("invalid_google_nonce");
  if (Number(claims.exp || 0) <= now) throw new Error("expired_google_id_token");
  if (claims.email_verified !== true && claims.email_verified !== "true") {
    throw new Error("google_email_unverified");
  }
  if (googleAllowedDomain && claims.hd !== googleAllowedDomain) {
    throw new Error("google_hosted_domain_not_allowed");
  }
  return claims;
}

function navItem(route) {
  return `<a class="nav-link nav-link--${route.tone}" href="/${route.id}" data-route="${route.id}">
    <span>${escapeHtml(route.title)}</span>
  </a>`;
}

function projectNavigationMarkup() {
  return `<nav class="nav-group" aria-label="Project routes" data-project-navigation>
    ${navItem(routeSkeletons[0])}
    <div class="project-tree" data-project-tree>
      <div class="project-tree__empty" data-project-tree-empty>No projects</div>
      <div class="project-tree__items" data-project-tree-items></div>
    </div>
  </nav>`;
}

function userLabel(session) {
  if (!session) return "";
  return String(session.email || session.display_name || session.user_id || "").toLowerCase();
}

function authProviderLabel(session) {
  if (!session || !session.auth_provider) return "";
  return String(session.auth_provider).toLowerCase();
}

function brandMarkup(session = null) {
  const label = userLabel(session);
  const provider = authProviderLabel(session);
  const userLine = label
    ? `<span class="brand-user" data-auth-user>${escapeHtml(label)}${provider ? ` · ${escapeHtml(provider)}` : ""}</span>`
    : "";
  return `<div class="brand"><span class="brand-mark" aria-hidden="true">F</span><span class="brand-copy"><span>Founder Research</span>${userLine}</span></div>`;
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
[hidden] { display: none !important; }
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
  align-items: flex-start;
  gap: 10px;
  min-height: 42px;
  margin-bottom: 18px;
  font-weight: 700;
}
.brand-copy {
  display: grid;
  gap: 1px;
}
.brand-user {
  color: var(--muted);
  font-size: var(--meta);
  font-weight: 500;
  line-height: 1.25;
  text-transform: lowercase;
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
  display: grid;
  gap: 8px;
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
  display: flex;
  align-items: center;
  padding: 0 10px;
  border-radius: var(--radius-control);
  text-decoration: none;
  font-weight: 700;
}
.nav-link:hover { background: #e8f0fe; }
.project-tree {
  display: grid;
  gap: 4px;
  padding-left: 14px;
  border-left: 1px solid var(--line);
  margin-left: 10px;
}
.project-tree__empty, .project-tree__item {
  min-height: 32px;
  display: flex;
  align-items: center;
  border-radius: var(--radius-control);
  color: var(--muted);
  font-size: var(--meta);
}
.project-tree__item {
  border: 0;
  justify-content: flex-start;
  padding: 0 8px;
  background: transparent;
  color: var(--ink);
  text-align: left;
}
.project-tree__item:hover, .project-tree__item[aria-current="page"] {
  background: #e8f0fe;
  color: var(--accent);
}
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
.project-empty-state {
  min-height: 360px;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 8px;
  color: var(--muted);
  text-align: center;
}
.project-workspace[hidden] {
  display: none !important;
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

function renderAuthenticatedShell(escapedApiUrl, session = null) {
  return `<div class="app-shell" data-design-system-version="founder-web-shell-v1">
  <aside class="sidebar" aria-label="Founder navigation">
    ${brandMarkup(session)}
    <div class="snapshot-indicator" data-snapshot-indicator>
      <label>
        <strong>Project Snapshot</strong>
        <select name="project_snapshot" data-project-selector>
          <option value="">No project selected</option>
        </select>
      </label>
      <span data-project-summary>Not selected</span>
    </div>
    ${projectNavigationMarkup()}
  </aside>
  <main class="workspace">
    <header class="topbar">
      <div>
        <h1 data-workspace-title>Project Snapshot</h1>
        <p class="subtle" data-api-base="${escapedApiUrl}">API ${escapedApiUrl}</p>
      </div>
      <div class="actions">
        <a href="/auth/logout"><button type="button" data-action="logout">Logout</button></a>
      </div>
    </header>

    <section class="project-empty-state" data-project-empty-state>
      <h2>No project selected</h2>
      <p>Select a project from Project Snapshot to load its workspace.</p>
    </section>

    <section class="project-workspace" data-project-workspace hidden>
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
    </section>
  </main>
</div>`;
}

function renderAppShell(apiUrl, initialSession = null) {
  const escapedApiUrl = escapeHtml(apiUrl);
  const escapedCsrfToken = initialSession && initialSession.csrf_token ? escapeHtml(initialSession.csrf_token) : "";
  const initialShell =
    initialSession && initialSession.authenticated === true
      ? renderAuthenticatedShell(escapedApiUrl, initialSession)
      : "";
  const gateHidden = initialSession && initialSession.authenticated === true ? " hidden" : "";
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="founder-csrf-token" content="${escapedCsrfToken}">
<title>Founder Research</title>
${renderStyles()}
</head>
<body>
<div class="login-gate" data-auth-gate${gateHidden}>
  <section class="login-panel" aria-label="Founder login">
    ${brandMarkup()}
    <h1>Sign in to continue</h1>
    <p class="login-panel__copy">The research dashboard is only available after Google authentication.</p>
    <div class="actions">
      <form action="/auth/google/start" method="get" data-form="google-login">
        <button class="primary" type="submit" aria-label="Start Google login">Google Login</button>
      </form>
    </div>
    <p class="login-panel__status" data-auth-status>Checking session...</p>
  </section>
</div>
<div id="authenticated-root" data-authenticated-root>${initialShell}</div>
<template id="authenticated-shell-template" data-authenticated-template>
${renderAuthenticatedShell(escapedApiUrl)}
</template>
<script>
const initialSession = ${JSON.stringify(initialSession)};
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
function setAuthStatus(message) {
  const status = document.querySelector("[data-auth-status]");
  if (status) status.textContent = message;
}
function parseSymbols(value) {
  return value.split(",").map((symbol) => symbol.trim()).filter(Boolean);
}
function clientEscapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
async function refreshSession() {
  return apiRequest(apiRoutes.session);
}
async function refreshDatasets() {
  const datasets = await apiRequest(apiRoutes.datasets);
  writeJson("[data-analysis-output]", { datasets });
}
let projectState = {
  projects: [],
  selectedProjectId: ""
};
function normalizeProjectItems(payload) {
  if (!payload || !Array.isArray(payload.items)) return [];
  return payload.items.filter((project) => project && project.project_id && project.name);
}
function projectLabel(project) {
  return String(project.name || project.project_id || "Untitled project");
}
function selectedProject() {
  return projectState.projects.find((project) => project.project_id === projectState.selectedProjectId) || null;
}
function renderProjectOptions() {
  const selector = document.querySelector("[data-project-selector]");
  if (!selector) return;
  const current = projectState.selectedProjectId;
  selector.innerHTML = '<option value="">No project selected</option>' + projectState.projects.map((project) => {
    const selected = project.project_id === current ? " selected" : "";
    return '<option value="' + clientEscapeHtml(project.project_id) + '"' + selected + ">"
      + clientEscapeHtml(projectLabel(project)) + "</option>";
  }).join("");
}
function renderProjectNavigation() {
  const items = document.querySelector("[data-project-tree-items]");
  const empty = document.querySelector("[data-project-tree-empty]");
  if (!items || !empty) return;
  empty.hidden = projectState.projects.length > 0;
  items.innerHTML = projectState.projects.map((project) => {
    const current = project.project_id === projectState.selectedProjectId ? ' aria-current="page"' : "";
    return '<button class="project-tree__item" type="button" data-project-id="'
      + clientEscapeHtml(project.project_id) + '"' + current + ">"
      + clientEscapeHtml(projectLabel(project)) + "</button>";
  }).join("");
  for (const button of items.querySelectorAll("[data-project-id]")) {
    button.addEventListener("click", () => selectProject(button.dataset.projectId || ""));
  }
}
function selectProject(projectId) {
  projectState.selectedProjectId = projectId;
  const project = selectedProject();
  const workspace = document.querySelector("[data-project-workspace]");
  const emptyState = document.querySelector("[data-project-empty-state]");
  const title = document.querySelector("[data-workspace-title]");
  const summary = document.querySelector("[data-project-summary]");
  if (workspace) workspace.hidden = !project;
  if (emptyState) emptyState.hidden = Boolean(project);
  if (title) title.textContent = project ? projectLabel(project) : "Project Snapshot";
  if (summary) summary.textContent = project ? projectLabel(project) : "Not selected";
  renderProjectOptions();
  renderProjectNavigation();
}
async function refreshProjects() {
  try {
    const payload = await apiRequest(apiRoutes.projects);
    projectState.projects = normalizeProjectItems(payload);
  } catch (_error) {
    projectState.projects = [];
  }
  if (!selectedProject()) projectState.selectedProjectId = "";
  renderProjectOptions();
  renderProjectNavigation();
  selectProject(projectState.selectedProjectId);
}
function clientUserLabel(session) {
  if (!session) return "";
  return String(session.email || session.display_name || session.user_id || "").toLowerCase();
}
function clientAuthProviderLabel(session) {
  if (!session || !session.auth_provider) return "";
  return String(session.auth_provider).toLowerCase();
}
function mountAuthenticatedShell(session) {
  const gate = document.querySelector("[data-auth-gate]");
  const root = document.querySelector("[data-authenticated-root]");
  const template = document.querySelector("[data-authenticated-template]");
  if (!root || !template) return;
  if (root.childElementCount === 0) root.appendChild(template.content.cloneNode(true));
  const csrfMeta = document.querySelector('meta[name="founder-csrf-token"]');
  if (csrfMeta && session && session.csrf_token) csrfMeta.content = session.csrf_token;
  const authUser = document.querySelector("[data-auth-user]");
  if (authUser && session) {
    const label = clientUserLabel(session);
    const provider = clientAuthProviderLabel(session);
    authUser.textContent = label + (provider ? " · " + provider : "");
  }
  if (gate) gate.hidden = true;
  bindAuthenticatedHandlers();
  void refreshProjects();
}
function showLoginGate() {
  const gate = document.querySelector("[data-auth-gate]");
  if (gate) gate.hidden = false;
  setAuthStatus("Google login is required before the dashboard is shown.");
}
async function initializeAuthGate() {
  if (initialSession && initialSession.authenticated === true) {
    mountAuthenticatedShell(initialSession);
    return;
  }
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
let authenticatedHandlersBound = false;
function bindAuthenticatedHandlers() {
if (authenticatedHandlersBound) return;
authenticatedHandlersBound = true;
document.querySelector("[data-project-selector]").addEventListener("change", (event) => {
  selectProject(event.currentTarget.value);
});
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
  const requestUrl = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
  if (requestUrl.pathname === "/auth/google/start") {
    void startGoogleLogin(response);
    return;
  }
  if (requestUrl.pathname === "/auth/google/callback") {
    void completeGoogleLogin(requestUrl, response);
    return;
  }
  if (requestUrl.pathname === "/auth/logout") {
    logoutLocalGoogleSession(response);
    return;
  }
  if (request.url && request.url.startsWith("/auth/")) {
    proxyAuthRequest(request, response);
    return;
  }
  const session = sessionFromRequest(request);
  if (requestUrl.pathname === "/" && session === null) {
    void startGoogleLogin(response);
    return;
  }
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(renderAppShell(apiBaseUrl, session));
});

server.listen(port, "0.0.0.0");

function cookieHeader(name, value, options = {}) {
  const parts = [`${name}=${encodeURIComponent(value)}`, "Path=/", "SameSite=Lax"];
  if (options.httpOnly) parts.push("HttpOnly");
  if (options.secure) parts.push("Secure");
  if (options.maxAge !== undefined) parts.push(`Max-Age=${options.maxAge}`);
  return parts.join("; ");
}

async function startGoogleLogin(response) {
  try {
    if (localDevAuthEnabled()) {
      startLocalGoogleLogin(response);
      return;
    }
    if (!googleAuthConfigured()) throw new Error("google_auth_not_configured");
    response.writeHead(303, { location: createGoogleAuthRequest() });
    response.end();
  } catch (_error) {
    writeAuthError(response, "google_auth_start_failed");
  }
}

async function completeGoogleLogin(callbackUrl, response) {
  try {
    const code = callbackUrl.searchParams.get("code");
    const state = callbackUrl.searchParams.get("state");
    if (!code || !state) throw new Error("google_callback_missing_code_or_state");
    const pending = pendingGoogleStates.get(sha256Hex(state));
    if (!pending || pending.consumed || pending.expiresAt <= Date.now()) {
      throw new Error("google_callback_invalid_state");
    }
    pending.consumed = true;
    pendingGoogleStates.delete(sha256Hex(state));
    const idToken = await exchangeGoogleCode(code, pending.codeVerifier);
    const claims = await verifyGoogleIdToken(idToken, pending.nonce);
    startGoogleSession(response, claims);
  } catch (_error) {
    writeAuthError(response, "google_auth_callback_failed");
  }
}

function startLocalGoogleLogin(response) {
  response.writeHead(303, {
    location: "/",
    "set-cookie": [
      cookieHeader(sessionCookieName, localDevUserId, { httpOnly: true, maxAge: 3600 }),
      cookieHeader(csrfCookieName, localDevCsrfToken, { maxAge: 3600 }),
      cookieHeader(emailCookieName, localDevGoogleEmail, { httpOnly: true, maxAge: 3600 }),
      cookieHeader(providerCookieName, "local-dev-google", { httpOnly: true, maxAge: 3600 }),
    ],
  });
  response.end();
}

function startGoogleSession(response, claims) {
  const csrfToken = randomToken();
  const email = String(claims.email || "").toLowerCase();
  response.writeHead(303, {
    location: "/",
    "set-cookie": [
      cookieHeader(sessionCookieName, stableGoogleUserId(claims.sub), { httpOnly: true, maxAge: 3600 }),
      cookieHeader(csrfCookieName, csrfToken, { maxAge: 3600 }),
      cookieHeader(emailCookieName, email, { httpOnly: true, maxAge: 3600 }),
      cookieHeader(providerCookieName, "google-oidc", { httpOnly: true, maxAge: 3600 }),
    ],
  });
  response.end();
}

function logoutLocalGoogleSession(response) {
  response.writeHead(303, {
    location: "/",
    "set-cookie": [
      cookieHeader(sessionCookieName, "", { httpOnly: true, maxAge: 0 }),
      cookieHeader(csrfCookieName, "", { maxAge: 0 }),
      cookieHeader(emailCookieName, "", { httpOnly: true, maxAge: 0 }),
      cookieHeader(providerCookieName, "", { httpOnly: true, maxAge: 0 }),
    ],
  });
  response.end();
}

function writeAuthError(response, errorCode) {
  response.writeHead(503, { "content-type": "application/json" });
  response.end(JSON.stringify({ error: errorCode }));
}

function parseCookies(cookieHeaderValue) {
  const cookies = {};
  for (const part of String(cookieHeaderValue || "").split(";")) {
    const [rawName, ...rawValueParts] = part.trim().split("=");
    if (!rawName) continue;
    cookies[rawName] = decodeURIComponent(rawValueParts.join("="));
  }
  return cookies;
}

function sessionFromRequest(request) {
  const cookies = parseCookies(request.headers.cookie);
  if (!cookies[sessionCookieName]) return null;
  return {
    authenticated: true,
    user_id: cookies[sessionCookieName],
    email: cookies[emailCookieName] || cookies[sessionCookieName],
    display_name: cookies[emailCookieName] || cookies[sessionCookieName],
    auth_provider: cookies[providerCookieName] || "unknown",
    csrf_token: cookies[csrfCookieName] || localDevCsrfToken,
  };
}

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
  logoutLocalGoogleSession,
  parseCookies,
  proxyApiRequest,
  proxyAuthRequest,
  renderAppShell,
  renderAuthenticatedShell,
  routeSkeletons,
  sessionFromRequest,
  startLocalGoogleLogin,
};
