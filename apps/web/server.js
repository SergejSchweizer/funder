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

const statisticsSteps = [
  { id: "load-data", label: "Load Data", actionLabel: "Load selected ISINs", endpoint: "load-data" },
  { id: "univariate", label: "Univariate Statistics" },
  { id: "bivariate", label: "Bivariate Statistics" },
  { id: "multivariate", label: "Multivariate Statistics" },
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

function statisticsStepButton(step, index) {
  const current = index === 0 ? ' aria-current="step"' : "";
  const disabled = index === 0 ? "" : " disabled";
  return `<button class="statistics-path__step" type="button" data-statistics-step="${step.id}"${current}${disabled}>
    <span class="statistics-path__index" aria-hidden="true">${index + 1}</span>
    <span class="funnel-copy">
      <span class="funnel-label">${escapeHtml(step.label)}</span>
      <span class="funnel-status">ready</span>
    </span>
  </button>`;
}

function statisticsPanel(step, index) {
  return `<section class="statistics-page" data-statistics-page="${step.id}"${index === 0 ? "" : " hidden"}>
    <div class="progress-banner" data-statistics-progress-banner="${step.id}">
      <div>
        <p class="eyebrow">${step.id === "load-data" ? "data load" : "statistics compute"}</p>
        <h2>${escapeHtml(step.label)}</h2>
        <p class="subtle" data-statistics-status="${step.id}">Idle. Select ${escapeHtml(step.actionLabel || "Compute")} to run this step for the current project.</p>
      </div>
      <button class="primary" type="button" data-compute-statistics="${step.id}">${escapeHtml(step.actionLabel || "Compute")}</button>
      <progress value="0" max="100" data-statistics-progress="${step.id}"></progress>
    </div>
    ${step.id === "univariate" ? univariateStatisticsTableMarkup() : ""}
  </section>`;
}

function univariateStatisticsTableMarkup() {
  return `<div class="statistics-table-panel">
    <div>
      <h3>Univariate Statistics Filters</h3>
      <p class="subtle" data-univariate-summary-status>Compute univariate statistics to populate this table.</p>
    </div>
    <div class="statistics-table-wrap">
      <table class="statistics-table">
        <thead>
          <tr>
            <th>Statistic</th>
            <th>Mean</th>
            <th>Median</th>
            <th>+- 3 std</th>
            <th>Filter</th>
          </tr>
        </thead>
        <tbody data-univariate-summary-body>
          <tr><td colspan="5">Compute univariate statistics to populate this table.</td></tr>
        </tbody>
      </table>
    </div>
  </div>`;
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
  --sidebar-width: 280px;
  min-height: 100vh;
  display: grid;
  grid-template-columns: var(--sidebar-width) 8px minmax(0, 1fr);
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
  display: flex;
  flex-direction: column;
}
.sidebar-resizer {
  position: sticky;
  top: 0;
  height: 100vh;
  cursor: col-resize;
  background: transparent;
  border: 0;
  border-left: 1px solid transparent;
  border-right: 1px solid transparent;
  padding: 0;
}
.sidebar-resizer:hover, .sidebar-resizer:focus-visible, .app-shell--resizing .sidebar-resizer {
  background: #e8f0fe;
  border-color: var(--accent);
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
.snapshot-indicator[aria-disabled="true"], .project-definition[aria-disabled="true"] {
  opacity: .46;
}
.snapshot-indicator span {
  display: block;
  color: var(--muted);
  font-size: var(--meta);
}
.sidebar-auth {
  margin-top: auto;
  padding-top: 18px;
}
.sidebar-auth button {
  width: 100%;
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
  margin-bottom: 32px;
}
.eodhd-fetch {
  width: min(620px, 100%);
  display: grid;
  grid-template-columns: minmax(240px, 1fr) auto;
  gap: 8px;
  align-items: end;
}
.eodhd-fetch label {
  color: var(--muted);
}
.eodhd-fetch button {
  min-width: 150px;
}
.eodhd-fetch__status {
  grid-column: 1 / -1;
  min-height: 18px;
  color: var(--muted);
  font-size: var(--meta);
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
.statistics-path {
  display: flex;
  flex-wrap: nowrap;
  gap: 8px;
  margin: 18px 0;
  overflow-x: auto;
  padding-bottom: 2px;
}
.statistics-path__step {
  flex: 1 0 178px;
  min-height: 66px;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--surface);
  padding: 10px;
  color: var(--ink);
  text-align: left;
}
.statistics-path__step:hover, .statistics-path__step[aria-current="step"] {
  border-color: var(--accent);
  background: #e8f0fe;
}
.statistics-path__step:disabled {
  cursor: not-allowed;
  color: var(--muted);
  background: #f1f3f4;
  opacity: .52;
}
.statistics-path__step:disabled:hover {
  border-color: var(--line);
  background: #f1f3f4;
}
.statistics-path__index {
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
.statistics-pages {
  display: grid;
  gap: 12px;
  margin-bottom: 16px;
}
.progress-banner {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--surface);
  padding: var(--space-panel);
  box-shadow: 0 1px 2px rgba(60, 64, 67, .16);
}
.progress-banner progress {
  grid-column: 1 / -1;
  width: 100%;
  height: 12px;
  accent-color: var(--accent);
}
.statistics-table-panel {
  display: grid;
  gap: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--surface);
  padding: var(--space-panel);
}
.statistics-table-wrap {
  overflow-x: auto;
}
.statistics-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 760px;
}
.statistics-table th, .statistics-table td {
  border-bottom: 1px solid var(--line);
  padding: 8px 10px;
  text-align: left;
  vertical-align: middle;
}
.statistics-table th {
  color: var(--muted);
  font-size: var(--meta);
  font-weight: 700;
}
.statistics-table select {
  min-width: 180px;
}
.project-empty-state {
  min-height: 360px;
  display: grid;
  align-content: start;
  justify-items: center;
  gap: 14px;
  color: var(--muted);
  text-align: center;
  padding: 28px 0;
}
.project-definition {
  width: min(760px, 100%);
  display: grid;
  gap: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--surface);
  padding: 18px;
  text-align: left;
  box-shadow: 0 1px 2px rgba(60, 64, 67, .16);
}
.project-definition__header {
  display: grid;
  gap: 4px;
}
.project-definition__actions {
  display: flex;
  justify-content: flex-end;
}
.project-definition__actions button {
  min-width: 220px;
  min-height: 46px;
  font-weight: 700;
}
.project-workspace[hidden] {
  display: none !important;
}
.eyebrow {
  color: var(--muted);
  font-size: var(--meta);
  text-transform: uppercase;
  letter-spacing: .08em;
}
form {
  display: grid;
  gap: 12px;
}
fieldset {
  margin: 0;
  padding: 0;
  border: 0;
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
@media (max-width: 1040px) {
  .app-shell { grid-template-columns: 1fr; }
  .sidebar-resizer { display: none; }
  .sidebar {
    position: static;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
}
@media (max-width: 620px) {
  .workspace { padding: 16px; }
  .topbar { align-items: flex-start; flex-direction: column; }
  .eodhd-fetch { grid-template-columns: 1fr; }
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
    <div class="snapshot-indicator" data-snapshot-indicator aria-disabled="true">
      <label>
        <strong>Projects</strong>
        <select name="project_snapshot" data-project-selector disabled>
          <option value="">No project selected</option>
        </select>
      </label>
      <span data-project-summary>Not selected</span>
    </div>
    <div class="sidebar-auth">
      <a href="/auth/logout"><button type="button" data-action="google-auth">Google Auth</button></a>
    </div>
  </aside>
  <button class="sidebar-resizer" type="button" data-sidebar-resizer aria-label="Resize sidebar" aria-orientation="vertical" aria-valuemin="220" aria-valuemax="520" aria-valuenow="280"></button>
  <main class="workspace">
    <header class="topbar">
      <div>
        <h1 data-workspace-title>Projects</h1>
        <p class="subtle" data-api-base="${escapedApiUrl}" data-current-selection-summary>Consisting currently of 0 ISINs</p>
      </div>
      <form class="eodhd-fetch" data-form="eodhd-fetch">
        <label>EODHD Key<input name="provider_key" type="password" autocomplete="new-password" placeholder="Paste EODHD API key"></label>
        <button class="primary" type="submit" data-action="fetch-all-isins" disabled>Fetch all ISINs</button>
        <span class="eodhd-fetch__status" data-eodhd-fetch-status>Enter an EODHD key to enable project setup.</span>
      </form>
    </header>

    <section class="project-empty-state" data-project-empty-state>
      <h2>No project selected</h2>
      <p>Select a project from Projects or define a new ISIN search project.</p>
      <form class="project-definition" data-form="project-definition" aria-disabled="true">
        <div class="project-definition__header">
          <h2>Project Definition</h2>
          <p class="subtle">Filter the all-ISIN metadata universe and create a project from the resulting list.</p>
        </div>
        <fieldset class="field-grid" data-project-definition-fields disabled>
          <label>Exchange<select name="exchange" data-metadata-option="exchange"><option value="">Any</option></select></label>
          <label>Name<input name="name" placeholder="UCITS ETF"></label>
          <label>Instrument Type<select name="instrument_type" data-metadata-option="instrument_type"><option value="">Any</option></select></label>
          <label>Country<select name="country" data-metadata-option="country"><option value="">Any</option></select></label>
          <label>Currency<select name="currency" data-metadata-option="currency"><option value="">Any</option></select></label>
        </fieldset>
        <div class="project-definition__actions">
          <button class="primary" type="submit" data-action="create-metadata-project" disabled>Create New Project</button>
        </div>
        <p class="subtle" data-project-definition-status></p>
      </form>
    </section>

    <section class="project-workspace" data-project-workspace hidden>
      <nav class="statistics-path" aria-label="Statistics path map">
        ${statisticsSteps.map(statisticsStepButton).join("")}
      </nav>
      <div class="statistics-pages">
        ${statisticsSteps.map(statisticsPanel).join("")}
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
  projects: "/projects",
  metadataFilterFetchAllIsins: "/metadata-filter/fetch-all-isins",
  metadataFilterOptions: "/metadata-filter/options",
  metadataFilterProjects: "/metadata-filter/projects",
  loadSelectedIsins: "/data/load-selected-isins",
  univariateStatisticsSummary: "/statistics/univariate/summary",
  statisticsCompute: (kind) => "/statistics/" + encodeURIComponent(kind) + "/compute"
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
function setAuthStatus(message) {
  const status = document.querySelector("[data-auth-status]");
  if (status) status.textContent = message;
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
let projectState = {
  projects: [],
  selectedProjectId: "",
  metadataReady: false,
  eodhdCredentialSaved: false,
  univariateSummaryLoaded: false,
  statisticsComplete: { "load-data": false, univariate: false, bivariate: false, multivariate: false }
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
function selectedIsinCount(project) {
  if (!project) return 0;
  if (Number.isFinite(project.selected_count)) return Number(project.selected_count);
  if (project.selection && Array.isArray(project.selection.member_ids)) return project.selection.member_ids.length;
  return 0;
}
function currentSelectionSummary(project) {
  const count = selectedIsinCount(project);
  return "Consisting currently of " + count + " ISIN" + (count === 1 ? "" : "s");
}
function updateCurrentSelectionSummary(project = selectedProject()) {
  const selectionSummary = document.querySelector("[data-current-selection-summary]");
  if (selectionSummary) selectionSummary.textContent = currentSelectionSummary(project);
}
function setEodhdFetchStatus(message) {
  const target = document.querySelector("[data-eodhd-fetch-status]");
  if (target) target.textContent = message;
}
function eodhdKeyInput() {
  return document.querySelector('[data-form="eodhd-fetch"] [name="provider_key"]');
}
function setEodhdCredentialSaved(saved, maskedLabel = "") {
  projectState.eodhdCredentialSaved = saved;
  const input = eodhdKeyInput();
  if (input) {
    input.placeholder = saved ? "Saved EODHD key available" : "Paste EODHD API key";
    if (saved && maskedLabel && (!input.value || input.dataset.credentialDisplay === "masked")) {
      input.value = maskedLabel;
      input.dataset.credentialDisplay = "masked";
    }
    if (!saved) {
      delete input.dataset.credentialDisplay;
    }
  }
  updateFetchButtonState();
}
function setProjectGateEnabled(enabled) {
  projectState.metadataReady = enabled;
  const selector = document.querySelector("[data-project-selector]");
  const snapshot = document.querySelector("[data-snapshot-indicator]");
  const definition = document.querySelector('[data-form="project-definition"]');
  const definitionFields = document.querySelector("[data-project-definition-fields]");
  const createButton = document.querySelector('[data-action="create-metadata-project"]');
  if (selector) selector.disabled = !enabled;
  if (snapshot) snapshot.setAttribute("aria-disabled", enabled ? "false" : "true");
  if (definition) definition.setAttribute("aria-disabled", enabled ? "false" : "true");
  if (definitionFields) definitionFields.disabled = !enabled;
  if (createButton) createButton.disabled = !enabled;
  if (!enabled) {
    projectState.projects = [];
    projectState.selectedProjectId = "";
    renderProjectOptions();
    selectProject("");
  }
}
function eodhdKeyValue() {
  const input = eodhdKeyInput();
  if (input && input.dataset.credentialDisplay === "masked") return "";
  return input ? String(input.value || "").trim() : "";
}
function updateFetchButtonState() {
  const button = document.querySelector('[data-action="fetch-all-isins"]');
  const hasKey = Boolean(eodhdKeyValue());
  const hasUsableCredential = hasKey || projectState.eodhdCredentialSaved;
  if (button) button.disabled = !hasUsableCredential;
  setProjectGateEnabled(false);
  setEodhdFetchStatus(
    hasKey
      ? "Fetch all ISINs to enable project setup."
      : projectState.eodhdCredentialSaved
        ? "Saved EODHD key available. Fetch all ISINs to enable project setup."
        : "Enter an EODHD key to enable project setup."
  );
}
async function refreshEodhdCredentialStatus() {
  try {
    const status = await apiRequest(apiRoutes.credential);
    const saved = status && status.status === "active";
    setEodhdCredentialSaved(saved, saved ? String(status.masked_label || "") : "");
    if (saved) {
      setProjectGateEnabled(true);
      await refreshMetadataFilterOptions();
      await refreshProjects();
      setEodhdFetchStatus("Saved EODHD key available. Projects restored for this user.");
    }
  } catch (_error) {
    setEodhdCredentialSaved(false);
  }
}
async function fetchAllIsinsForProjects(form) {
  const providerKey = eodhdKeyValue();
  if (!providerKey && !projectState.eodhdCredentialSaved) {
    updateFetchButtonState();
    return;
  }
  setProjectGateEnabled(false);
  setEodhdFetchStatus("Fetching all ISINs...");
  if (providerKey) {
    await apiRequest(apiRoutes.credential, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("credential") },
      body: { provider_key: providerKey }
    });
    setEodhdCredentialSaved(true);
  }
  const result = await apiRequest(apiRoutes.metadataFilterFetchAllIsins, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey("fetch-all-isins") }
  });
  setProjectGateEnabled(true);
  await refreshMetadataFilterOptions();
  await refreshProjects();
  setEodhdFetchStatus("Fetched " + result.row_count + " ISIN listings.");
}
function optionMarkup(value) {
  return '<option value="' + clientEscapeHtml(value) + '">' + clientEscapeHtml(value) + "</option>";
}
function formatSummaryValue(value) {
  if (value === null || value === undefined || value === "") return "n/a";
  if (typeof value === "number") return Number.isFinite(value) ? value.toPrecision(6) : "n/a";
  return String(value);
}
function filterOptionMarkup(option) {
  if (!option || option.value === undefined) return "";
  const label = option.label === undefined ? option.value : option.label;
  return '<option value="' + clientEscapeHtml(option.value) + '">' + clientEscapeHtml(label) + "</option>";
}
function renderUnivariateStatisticsSummary(items) {
  const body = document.querySelector("[data-univariate-summary-body]");
  const status = document.querySelector("[data-univariate-summary-status]");
  if (!body) return;
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="5">No univariate statistics are available yet.</td></tr>';
    if (status) status.textContent = "No univariate statistics are available yet.";
    return;
  }
  body.innerHTML = rows.map((row) => {
    const filterOptions = Array.isArray(row.filter_options) ? row.filter_options : [];
    const options = '<option value="">Choose filter</option>' + filterOptions.map(filterOptionMarkup).join("");
    return '<tr>'
      + '<td><strong>' + clientEscapeHtml(row.name || "") + '</strong><br><span class="subtle">'
      + clientEscapeHtml(row.category || "") + "</span></td>"
      + "<td>" + clientEscapeHtml(formatSummaryValue(row.mean)) + "</td>"
      + "<td>" + clientEscapeHtml(formatSummaryValue(row.median)) + "</td>"
      + "<td>" + clientEscapeHtml(formatSummaryValue(row.three_std_range)) + "</td>"
      + '<td><select name="filter_' + clientEscapeHtml(row.name || "statistic") + '">' + options + "</select></td>"
      + "</tr>";
  }).join("");
  if (status) status.textContent = "Statistics summary loaded.";
}
async function loadUnivariateStatisticsSummary() {
  if (projectState.univariateSummaryLoaded) return;
  const status = document.querySelector("[data-univariate-summary-status]");
  if (status) status.textContent = "Loading statistics summary...";
  try {
    const payload = await apiRequest(apiRoutes.univariateStatisticsSummary);
    renderUnivariateStatisticsSummary(payload.items);
    projectState.univariateSummaryLoaded = true;
  } catch (_error) {
    renderUnivariateStatisticsSummary([]);
    if (status) status.textContent = "Statistics summary is not available.";
  }
}
function resetUnivariateStatisticsSummary() {
  projectState.univariateSummaryLoaded = false;
  const body = document.querySelector("[data-univariate-summary-body]");
  const status = document.querySelector("[data-univariate-summary-status]");
  if (body) {
    body.innerHTML = '<tr><td colspan="5">Compute univariate statistics to populate this table.</td></tr>';
  }
  if (status) status.textContent = "Compute univariate statistics to populate this table.";
}
function setProjectDefinitionStatus(message) {
  const target = document.querySelector("[data-project-definition-status]");
  if (target) target.textContent = message;
}
function projectDefinitionPayload(form) {
  const data = new FormData(form);
  return {
    exchange: String(data.get("exchange") || ""),
    name: String(data.get("name") || ""),
    instrument_type: String(data.get("instrument_type") || ""),
    country: String(data.get("country") || ""),
    currency: String(data.get("currency") || "")
  };
}
async function refreshMetadataFilterOptions() {
  let payload = {};
  try {
    payload = await apiRequest(apiRoutes.metadataFilterOptions);
  } catch (_error) {
    setProjectDefinitionStatus("Metadata options are not available.");
  }
  for (const field of ["exchange", "instrument_type", "country", "currency"]) {
    const select = document.querySelector('[data-metadata-option="' + field + '"]');
    if (!select) continue;
    const values = Array.isArray(payload[field]) ? payload[field] : [];
    select.innerHTML = '<option value="">Any</option>' + values.map(optionMarkup).join("");
  }
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
function statisticsStepIndex(kind) {
  return statisticsSteps.findIndex((step) => step.id === kind);
}
function statisticsStepEnabled(kind) {
  const index = statisticsStepIndex(kind);
  if (index <= 0) return true;
  const previous = statisticsSteps[index - 1];
  return Boolean(previous && projectState.statisticsComplete[previous.id]);
}
function nextStatisticsStep(kind) {
  const index = statisticsStepIndex(kind);
  if (index < 0) return null;
  return statisticsSteps[index + 1] || null;
}
function updateStatisticsPathAccess() {
  for (const button of document.querySelectorAll("[data-statistics-step]")) {
    const kind = button.dataset.statisticsStep || "";
    const enabled = statisticsStepEnabled(kind);
    const status = button.querySelector(".funnel-status");
    button.disabled = !enabled;
    if (status) {
      status.textContent = projectState.statisticsComplete[kind] ? "complete" : enabled ? "ready" : "locked";
    }
  }
}
function resetStatisticsWorkflow() {
  const project = selectedProject();
  projectState.statisticsComplete = {
    "load-data": Boolean(project && project.data_loaded === true),
    univariate: false,
    bivariate: false,
    multivariate: false
  };
  resetUnivariateStatisticsSummary();
  for (const step of statisticsSteps) {
    setStatisticsProgress(step.id, 0, "Idle. Select " + (step.actionLabel || "Compute") + " to run this step for the current project.");
  }
  updateStatisticsPathAccess();
  showStatisticsPage(projectState.statisticsComplete["load-data"] ? "univariate" : "load-data");
}
function showStatisticsPage(kind) {
  if (!statisticsStepEnabled(kind)) return;
  for (const page of document.querySelectorAll("[data-statistics-page]")) {
    page.hidden = page.dataset.statisticsPage !== kind;
  }
  for (const button of document.querySelectorAll("[data-statistics-step]")) {
    if (button.dataset.statisticsStep === kind) {
      button.setAttribute("aria-current", "step");
    } else {
      button.removeAttribute("aria-current");
    }
  }
}
function setStatisticsProgress(kind, progress, message) {
  const progressBar = document.querySelector('[data-statistics-progress="' + kind + '"]');
  const status = document.querySelector('[data-statistics-status="' + kind + '"]');
  if (progressBar) progressBar.value = progress;
  if (status) status.textContent = message;
}
function completeStatisticsStep(kind, result = {}) {
  const project = selectedProject();
  if (project && Number.isFinite(result.selected_count)) {
    project.selected_count = Number(result.selected_count);
  }
  if (project && kind === "load-data") project.data_loaded = true;
  projectState.statisticsComplete[kind] = true;
  updateCurrentSelectionSummary(project);
  updateStatisticsPathAccess();
  if (kind === "univariate") {
    projectState.univariateSummaryLoaded = false;
    void loadUnivariateStatisticsSummary();
  }
  const nextStep = nextStatisticsStep(kind);
  if (nextStep && statisticsStepEnabled(nextStep.id)) showStatisticsPage(nextStep.id);
}
async function computeStatistics(kind) {
  const project = selectedProject();
  if (!project) {
    setStatisticsProgress(kind, 0, "Select a project before computing statistics.");
    return;
  }
  const isLoadData = kind === "load-data";
  setStatisticsProgress(kind, 12, isLoadData ? "Loading selected ISINs..." : "Starting " + kind + " statistics...");
  const result = await apiRequest(isLoadData ? apiRoutes.loadSelectedIsins : apiRoutes.statisticsCompute(kind), {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey(isLoadData ? "load-data" : kind + "-statistics") },
    body: { project_id: project.project_id }
  });
  setStatisticsProgress(kind, Number(result.progress || 100), isLoadData ? "Loaded selected ISINs." : "Completed " + kind + " statistics.");
  if (!result.status || result.status === "succeeded") completeStatisticsStep(kind, result);
}
function selectProject(projectId) {
  const previousProjectId = projectState.selectedProjectId;
  projectState.selectedProjectId = projectId;
  const project = selectedProject();
  const workspace = document.querySelector("[data-project-workspace]");
  const emptyState = document.querySelector("[data-project-empty-state]");
  const title = document.querySelector("[data-workspace-title]");
  const summary = document.querySelector("[data-project-summary]");
  if (workspace) workspace.hidden = !project;
  if (emptyState) emptyState.hidden = Boolean(project);
  if (title) title.textContent = project ? projectLabel(project) : "Projects";
  if (summary) summary.textContent = project ? projectLabel(project) : "Not selected";
  updateCurrentSelectionSummary(project);
  renderProjectOptions();
  if (previousProjectId !== projectId) resetStatisticsWorkflow();
}
async function refreshProjects() {
  if (!projectState.metadataReady) {
    renderProjectOptions();
    selectProject("");
    return;
  }
  try {
    const payload = await apiRequest(apiRoutes.projects);
    projectState.projects = normalizeProjectItems(payload);
  } catch (_error) {
    projectState.projects = [];
  }
  if (!selectedProject()) projectState.selectedProjectId = "";
  renderProjectOptions();
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
  setProjectGateEnabled(false);
  void refreshEodhdCredentialStatus();
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
const sidebarWidthBounds = { min: 220, max: 520, step: 16 };
function clampSidebarWidth(width) {
  return Math.max(sidebarWidthBounds.min, Math.min(sidebarWidthBounds.max, width));
}
function setSidebarWidth(width) {
  const shell = document.querySelector(".app-shell");
  const resizer = document.querySelector("[data-sidebar-resizer]");
  const nextWidth = clampSidebarWidth(width);
  if (shell) shell.style.setProperty("--sidebar-width", nextWidth + "px");
  if (resizer) resizer.setAttribute("aria-valuenow", String(nextWidth));
}
function currentSidebarWidth() {
  const sidebar = document.querySelector(".sidebar");
  return sidebar ? sidebar.getBoundingClientRect().width : 280;
}
function bindSidebarResizer() {
  const resizer = document.querySelector("[data-sidebar-resizer]");
  const shell = document.querySelector(".app-shell");
  if (!resizer || !shell) return;
  resizer.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    resizer.setPointerCapture(event.pointerId);
    shell.classList.add("app-shell--resizing");
  });
  resizer.addEventListener("pointermove", (event) => {
    if (!resizer.hasPointerCapture(event.pointerId)) return;
    setSidebarWidth(event.clientX);
  });
  function endResize(event) {
    if (resizer.hasPointerCapture(event.pointerId)) resizer.releasePointerCapture(event.pointerId);
    shell.classList.remove("app-shell--resizing");
  }
  resizer.addEventListener("pointerup", endResize);
  resizer.addEventListener("pointercancel", endResize);
  resizer.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setSidebarWidth(currentSidebarWidth() - sidebarWidthBounds.step);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setSidebarWidth(currentSidebarWidth() + sidebarWidthBounds.step);
    } else if (event.key === "Home") {
      event.preventDefault();
      setSidebarWidth(sidebarWidthBounds.min);
    } else if (event.key === "End") {
      event.preventDefault();
      setSidebarWidth(sidebarWidthBounds.max);
    }
  });
}
function bindAuthenticatedHandlers() {
if (authenticatedHandlersBound) return;
authenticatedHandlersBound = true;
bindSidebarResizer();
document.querySelector('[data-form="eodhd-fetch"]').addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await fetchAllIsinsForProjects(event.currentTarget);
  } catch (_error) {
    setProjectGateEnabled(false);
    setEodhdFetchStatus("Fetch failed. Check the EODHD key and all-ISIN reference data.");
  }
});
document.querySelector('[data-form="eodhd-fetch"] [name="provider_key"]').addEventListener("input", () => {
  delete eodhdKeyInput().dataset.credentialDisplay;
  updateFetchButtonState();
});
document.querySelector("[data-project-selector]").addEventListener("change", (event) => {
  if (!projectState.metadataReady) return;
  selectProject(event.currentTarget.value);
});
for (const button of document.querySelectorAll("[data-statistics-step]")) {
  button.addEventListener("click", () => showStatisticsPage(button.dataset.statisticsStep || "univariate"));
}
for (const button of document.querySelectorAll("[data-compute-statistics]")) {
  button.addEventListener("click", () => {
    void computeStatistics(button.dataset.computeStatistics || "univariate");
  });
}
document.querySelector('[data-form="project-definition"]').addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!projectState.metadataReady) return;
  const form = event.currentTarget;
  setProjectDefinitionStatus("Creating project...");
  try {
    const created = await apiRequest(apiRoutes.metadataFilterProjects, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("metadata-project") },
      body: projectDefinitionPayload(form)
    });
    await refreshProjects();
    if (created && created.project && created.project.project_id) {
      selectProject(created.project.project_id);
      setProjectDefinitionStatus("Created " + created.project.name + " with " + created.selected_count + " listings.");
    }
  } catch (_error) {
    setProjectDefinitionStatus("Choose at least one filter with matching ISINs.");
  }
});
}
window.founderApi = { apiRequest, apiRoutes, idempotencyKey, refreshSession };
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
  logoutLocalGoogleSession,
  parseCookies,
  proxyApiRequest,
  proxyAuthRequest,
  renderAppShell,
  renderAuthenticatedShell,
  sessionFromRequest,
  startLocalGoogleLogin,
  statisticsSteps,
};
