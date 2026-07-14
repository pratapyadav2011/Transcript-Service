// Front-end glue: submit the New Job forms via fetch, then redirect to the
// job-detail page so the user immediately sees the live step log.

function showResult(targetId, html, ok) {
  const el = document.getElementById(targetId);
  if (el) el.innerHTML = `<div class="${ok ? 'success-banner' : 'error-box'}">${html}</div>`;
}

function goToJob(jobId) {
  window.location.href = `/jobs/${jobId}`;
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
