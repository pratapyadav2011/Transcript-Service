// Reads the YouTube session cookies and posts them to the transcript service as
// a Netscape cookies.txt — the format yt-dlp's --cookies flag expects.
// An extension can do this because chrome.cookies sees HttpOnly cookies; a normal
// web page never can, which is why the service also accepts a manual file upload.

// Chrome/Edge expose `chrome`, Firefox `browser`; both return promises here.
const api = globalThis.browser ?? globalThis.chrome;
const COOKIE_DOMAINS = ["youtube.com", "google.com"];
// Any of these means a signed-in session; Google rotates which ones it sets.
const LOGIN_COOKIES = new Set([
  "SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "__Secure-3PAPISID",
  "SSID", "HSID", "LOGIN_INFO", "APISID",
]);
const LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube";
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

function isLiveLoginCookie(c) {
  // expirationDate is absent for session cookies, which are still valid now.
  const alive = !c.expirationDate || c.expirationDate * 1000 > Date.now();
  return alive && LOGIN_COOKIES.has(c.name);
}

/** Show either the "log in" prompt or the send button, based on real cookies. */
async function refreshSignInState() {
  const cookies = await collectCookies();
  const signedIn = cookies.some(isLiveLoginCookie);
  $("checking").hidden = true;
  $("signin").hidden = signedIn;
  $("send").hidden = !signedIn;
  if (signedIn) {
    const plural = cookies.length === 1 ? "cookie" : "cookies";
    setStatus(`Signed in to YouTube — ${cookies.length} ${plural} ready to send.`, true);
  }
  return signedIn;
}

function openLogin() {
  if (api.tabs && api.tabs.create) api.tabs.create({ url: LOGIN_URL });
  else window.open(LOGIN_URL, "_blank");
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
    if (!cookies.some(isLiveLoginCookie)) {
      await refreshSignInState();
      throw new Error("That YouTube session ended — log in again.");
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
    setStatus(`✓ Sent ${data.count} ${data.count === 1 ? "cookie" : "cookies"}.${expires}`, true);
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
$("login").addEventListener("click", openLogin);
refreshSignInState();
