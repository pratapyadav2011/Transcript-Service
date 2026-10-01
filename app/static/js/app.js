// Front-end glue: submit the New Job forms via fetch, then redirect to the
// job-detail page so the user immediately sees the live step log.

function showResult(targetId, html, ok) {
  const el = document.getElementById(targetId);
  if (el) el.innerHTML = `<div class="${ok ? 'success-banner' : 'error-box'}">${html}</div>`;
}

function goToJob(jobId) {
  window.location.href = `/jobs/${jobId}`;
}

async function writeClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('Browser denied clipboard access');
}

async function copyTranscript() {
  const jobIdEl = document.querySelector('.job-id');
  if (!jobIdEl) return;
  try {
    const res = await fetch(`/api/jobs/${jobIdEl.textContent.trim()}/transcript`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Transcript could not be loaded');
    await writeClipboard(data.transcript);
    alert(`Copied full transcript (${data.transcript.length} characters).`);
  } catch (err) {
    alert('Copy failed: ' + err.message);
  }
}

async function downloadTranscript() {
  const jobIdEl = document.querySelector('.job-id');
  if (!jobIdEl) return;
  const jobId = jobIdEl.textContent.trim();
  try {
    const res = await fetch(`/api/jobs/${jobId}/transcript`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Transcript could not be loaded');
    const blob = new Blob([data.transcript], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `transcript-${jobId.slice(0, 8)}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('Download failed: ' + err.message);
  }
}

async function submitUrlForm(event) {
  event.preventDefault();
  const form = event.target;
  const body = { url: form.url.value.trim() };
  try {
    const res = await fetch('/api/transcript/url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    showResult('url-result', `✓ Job queued — redirecting…`, true);
    setTimeout(() => goToJob(data.job_id), 600);
  } catch (err) {
    showResult('url-result', `✗ ${err.message}`, false);
  }
}

async function findMediaLinks() {
  const input = document.getElementById('url-input');
  const target = document.getElementById('media-links-result');
  const sourceUrl = input && input.value.trim();
  if (!sourceUrl || !target) {
    showResult('url-result', 'Enter a video or meeting URL first.', false);
    return;
  }

  target.replaceChildren();
  const loading = document.createElement('div');
  loading.className = 'media-links-panel';
  loading.textContent = 'Searching for downloadable media…';
  target.appendChild(loading);

  try {
    const res = await fetch('/api/transcript/media-links', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: sourceUrl }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'No media links found');

    const panel = document.createElement('div');
    panel.className = 'media-links-panel';
    const heading = document.createElement('strong');
    heading.textContent = 'Download in your browser, then upload the file';
    panel.appendChild(heading);

    const note = document.createElement('p');
    note.className = 'hint';
    note.textContent = 'Choose MP3 when available—it is smaller and already audio-only. If a link opens a player, use the browser’s download/save option.';
    panel.appendChild(note);

    const list = document.createElement('div');
    list.className = 'media-link-list';
    data.links.forEach((item) => {
      const link = document.createElement('a');
      link.className = `btn ${item.downloadable ? 'btn-success' : 'btn-secondary'}`;
      link.href = item.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = item.downloadable ? `Download ${item.format}` : `Open ${item.format} stream`;
      list.appendChild(link);
    });
    panel.appendChild(list);
    target.replaceChildren(panel);
  } catch (err) {
    target.replaceChildren();
    showResult('media-links-result', `✗ ${err.message}`, false);
  }
}

async function submitUploadForm(event) {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  try {
    const res = await fetch('/api/transcript/upload', { method: 'POST', body: data });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || 'Upload failed');
    showResult('upload-result', `✓ Uploaded — redirecting…`, true);
    setTimeout(() => goToJob(json.job_id), 600);
  } catch (err) {
    showResult('upload-result', `✗ ${err.message}`, false);
  }
}

async function rerunJob(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}/rerun`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Rerun failed');
    goToJob(data.job_id);
  } catch (err) {
    alert('Rerun failed: ' + err.message);
  }
}

async function retryTranscription(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}/retry-transcription`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Transcription retry failed');
    goToJob(data.job_id);
  } catch (err) {
    alert('Transcription retry failed: ' + err.message);
  }
}

async function retryWithGemini(jobId) {
  if (!confirm('Send the cached audio to Gemini for transcription?')) return;
  try {
    const res = await fetch(`/api/jobs/${jobId}/retry-gemini`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gemini transcription failed to start');
    goToJob(data.job_id);
  } catch (err) {
    alert('Gemini transcription failed to start: ' + err.message);
  }
}

// ── YouTube cookie jar ──────────────────────────────────────────────────────
// A page cannot read youtube.com cookies itself (cross-origin + HttpOnly), so
// the user exports cookies.txt from their browser and hands us the file.

function renderCookieStatus(data) {
  const el = document.getElementById('cookie-status');
  if (!el) return;
  if (!data.present) {
    el.className = 'cookie-status';
    el.textContent = 'No cookies stored — YouTube downloads may hit the bot check.';
    return;
  }
  const when = new Date(data.updated_at * 1000).toLocaleString();
  const expires = data.expires_at
    ? new Date(data.expires_at * 1000).toLocaleDateString()
    : 'unknown';
  if (data.expired || data.warning) {
    el.className = 'cookie-status cookie-status-stale';
    el.textContent = data.warning
      ? `Stored cookies look unusable: ${data.warning}`
      : `Stored cookies expired on ${expires} — upload a fresh export.`;
    return;
  }
  el.className = 'cookie-status cookie-status-ok';
  el.textContent = `${data.count} cookies stored ${data.managed ? '' : '(set by env config) '}` +
    `· updated ${when} · expires ${expires}`;
}

async function loadCookieStatus() {
  if (!document.getElementById('cookie-status')) return;
  try {
    const res = await fetch('/api/cookies');
    renderCookieStatus(await res.json());
  } catch (err) {
    renderCookieStatus({ present: false });
  }
}

async function submitCookiesForm(event, rerunJobId) {
  event.preventDefault();
  const form = event.target;
  const body = new FormData();
  if (form.file.files.length) body.append('file', form.file.files[0]);
  else body.append('text', form.text.value);

  try {
    const res = await fetch('/api/cookies', { method: 'POST', body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Cookies rejected');
    renderCookieStatus(data);
    form.reset();
    showResult('cookie-result', '✓ Cookies saved.', true);
    if (rerunJobId) {
      showResult('cookie-result', '✓ Cookies saved — rerunning job…', true);
      setTimeout(() => rerunJob(rerunJobId), 600);
    }
  } catch (err) {
    showResult('cookie-result', `✗ ${err.message}`, false);
  }
}

async function deleteCookies() {
  if (!confirm('Remove the stored YouTube cookies?')) return;
  try {
    const res = await fetch('/api/cookies', { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Delete failed');
    renderCookieStatus(data);
    showResult('cookie-result', '✓ Cookies removed.', true);
  } catch (err) {
    showResult('cookie-result', `✗ ${err.message}`, false);
  }
}

document.addEventListener('DOMContentLoaded', loadCookieStatus);

// On the job-detail page, reload after a pause/resume/stop so the header
// buttons reflect the new state (the status badge already polls live).
document.body.addEventListener('htmx:afterRequest', (e) => {
  const path = e.detail.requestConfig && e.detail.requestConfig.path;
  if (path && /\/api\/jobs\/.+\/(pause|resume|stop)$/.test(path) &&
      document.querySelector('.header-actions')) {
    setTimeout(() => window.location.reload(), 700);
  }
});

// Auto-scroll the live log box when new lines arrive (HTMX swaps the container).
document.body.addEventListener('htmx:afterSwap', (e) => {
  if (e.target.id !== 'logs-container') return;
  const toggle = document.getElementById('auto-scroll');
  if (toggle && !toggle.checked) return;
  const box = document.getElementById('log-box');
  if (box) box.scrollTop = box.scrollHeight;
});
