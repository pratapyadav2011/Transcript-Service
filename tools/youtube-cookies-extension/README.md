# YouTube & Vimeo cookies → Transcript Service (Chrome/Edge extension)

One click sends your logged-in YouTube and Vimeo cookies to the transcript
service, so yt-dlp stops hitting YouTube's "Sign in to confirm you're not a bot"
and Vimeo's "401 Unauthorized" from datacenter IPs. Both go into the one
cookies file yt-dlp uses; you can be signed in to either site or both.

A page served by the transcript service cannot do this itself: browsers forbid
any site from reading another site's cookies, and Google's session cookies are
`HttpOnly`. An extension has the `chrome.cookies` permission, so it can.

## Install (once, ~30 seconds)

0. Download the zip from the service's *Generate Transcript* page (it arrives
   pre-configured), or use this folder directly from the repo.
1. Open `chrome://extensions` (or `edge://extensions`).
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and pick this folder (`tools/youtube-cookies-extension`).
4. Pin the extension so its icon stays visible.

## Use

1. Click the extension icon. It checks your YouTube and Vimeo sessions first:
   - **Signed in to neither** → it shows **Log in to YouTube** / **Log in to Vimeo**.
   - **Signed in to one or both** → it shows **Send cookies**, which sites are
     covered, and a log-in button for any site still missing.
2. If prompted, log in, then click the icon again.
3. Click **Send cookies**. It reports how many cookies were stored and when they
   expire.

The service URL is pre-filled when you download the zip from the service itself,
along with a signed access token if that service has auth enabled — so the popup
never asks you for credentials. Rotating `API_SERVICE_TOKEN` on the server
invalidates tokens handed out this way; re-download the zip to get a fresh one.

Repeat step 3 whenever downloads start failing again — Google rotates these
cookies every few weeks.

## Notes

- These cookies are a full login session for that YouTube account. Prefer a
  throwaway account, and only point this at a service you control over HTTPS.
- Firefox needs a separate build (`browser.cookies`, MV2-style packaging); the
  manual file upload in the service UI works there in the meantime.
