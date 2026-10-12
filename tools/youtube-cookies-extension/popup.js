// Reads the YouTube and Vimeo session cookies and posts them to the transcript service as
// a Netscape cookies.txt — the format yt-dlp's --cookies flag expects.
// An extension can do this because chrome.cookies sees HttpOnly cookies; a normal
// web page never can, which is why the service also accepts a manual file upload.

// Chrome/Edge expose `chrome`, Firefox `browser`; both return promises here.
const api = globalThis.browser ?? globalThis.chrome;
// One jar for both sites: yt-dlp takes a single --cookies file. `login` holds
// the cookie names that mean a signed-in session (must match cookie_store.py).
const SITES = [
  {
    name: "YouTube",
    domains: ["youtube.com", "google.com"],
    // Google rotates which of these it sets; any one means signed in.
    login: new Set([
      "SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "__Secure-3PAPISID",
      "SSID", "HSID", "LOGIN_INFO", "APISID",
    ]),
    loginUrl: "https://accounts.google.com/ServiceLogin?service=youtube",
  },
  {
    name: "Vimeo",
    domains: ["vimeo.com"],
    login: new Set(["vimeo"]),
    loginUrl: "https://vimeo.com/log_in",
  },
];
const COOKIE_DOMAINS = SITES.flatMap((s) => s.domains);
const $ = (id) => document.getElementById(id);

function setStatus(message, ok) {
  const el = $("status");
  el.textContent = message;
  el.className = ok ? "ok" : "err";
}

function toNetscape(cookies) {
  const lines = ["# Netscape HTTP Cookie File"];
  for (const c of cookies) {
    const includeSubdomains = c.domain.startsWith(".") ? "TRUE" : "FALSE";
    const expires = Math.floor(c.expirationDate || 0);
    const row = [
      c.domain, includeSubdomains, c.path, c.secure ? "TRUE" : "FALSE",
      expires, c.name, c.value,
    ].join("\t");
    // yt-dlp reads this prefix back as an HttpOnly cookie.
    lines.push(c.httpOnly ? `#HttpOnly_${row}` : row);
  }
  return lines.join("\n") + "\n";
}

async function collectCookies() {
  const byKey = new Map();
  for (const domain of COOKIE_DOMAINS) {
    for (const c of await api.cookies.getAll({ domain })) {
      byKey.set(`${c.domain}|${c.path}|${c.name}`, c);
    }
  }
  return [...byKey.values()];
}

function isLiveLoginCookie(site, c) {
  // expirationDate is absent for session cookies, which are still valid now.
  const alive = !c.expirationDate || c.expirationDate * 1000 > Date.now();
  const domain = c.domain.replace(/^\./, "");
  return alive && site.login.has(c.name) && site.domains.some((d) => domain.endsWith(d));
}

/** Names of the sites this browser has a live login session for. */
function signedInSites(cookies) {
  return SITES.filter((site) => cookies.some((c) => isLiveLoginCookie(site, c)))
    .map((site) => site.name);
}

/** Show the send button if any site is signed in, plus log-in buttons for the rest. */
async function refreshSignInState() {
  const cookies = await collectCookies();
  const sites = signedInSites(cookies);
  $("checking").hidden = true;
  $("send").hidden = sites.length === 0;
  $("signin").hidden = sites.length === SITES.length;
  for (const site of SITES) {
    $(`login-${site.name.toLowerCase()}`).hidden = sites.includes(site.name);
  }
  if (sites.length) {
    const plural = cookies.length === 1 ? "cookie" : "cookies";
    setStatus(`Signed in to ${sites.join(" + ")} — ${cookies.length} ${plural} ready to send.`, true);
  }
  return sites.length > 0;
}

function openLogin(url) {
  if (api.tabs && api.tabs.create) api.tabs.create({ url });
  else window.open(url, "_blank");
  // The popup closes when focus moves to the new tab; reopening re-checks.
  window.close();
}

async function send() {
  const button = $("send");
  const base = $("url").value.trim().replace(/\/+$/, "");
  // Minted by the service when this zip was downloaded; empty when auth is off.
  const token = (globalThis.TS_CONFIG || {}).authToken || "";
  if (!base) return setStatus("Enter your transcript service URL.", false);

  button.disabled = true;
  setStatus("Collecting cookies…", true);
  try {
    const cookies = await collectCookies();
    if (!signedInSites(cookies).length) {
      await refreshSignInState();
      throw new Error("No signed-in YouTube or Vimeo session — log in again.");
    }

    await api.storage.local.set({ base });
    const body = new FormData();
    body.append("text", toNetscape(cookies));

    const res = await fetch(`${base}/api/cookies`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body,
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      throw new Error(
        "Not authorised — re-download the extension from the service's " +
        "Generate Transcript page to get a fresh access token."
      );
    }
    if (!res.ok) throw new Error(data.detail || `Service returned ${res.status}`);

    const expires = data.expires_at
      ? ` Valid until ${new Date(data.expires_at * 1000).toLocaleDateString()}.`
      : "";
    const sites = data.sites && data.sites.length ? ` for ${data.sites.join(" + ")}` : "";
    setStatus(`✓ Sent ${data.count} ${data.count === 1 ? "cookie" : "cookies"}${sites}.${expires}`, true);
  } catch (err) {
    setStatus(`✗ ${err.message}`, false);
  } finally {
    button.disabled = false;
  }
}

// Saved setting wins; otherwise use the URL baked in at download time.
api.storage.local.get(["base"]).then(({ base }) => {
  $("url").value = base || (globalThis.TS_CONFIG || {}).serviceUrl || "";
});
$("send").addEventListener("click", send);
for (const site of SITES) {
  $(`login-${site.name.toLowerCase()}`).addEventListener("click", () => openLogin(site.loginUrl));
}
refreshSignInState();
