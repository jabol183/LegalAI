/* ── LegalAI Frontend ─────────────────────────────────────────────────────── */

const API = '';  // same-origin

let selectedFile = null;
let currentSessionId = null;
let currentRedlines = [];

// ── DOM refs ───────────────────────────────────────────────────────────────────
const dropZone       = document.getElementById('drop-zone');
const fileInput      = document.getElementById('file-input');
const fileNameDisplay= document.getElementById('file-name-display');
const reviewBtn      = document.getElementById('review-btn');
const uploadSection  = document.getElementById('upload-section');
const progressSection= document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const pendingBadge   = document.getElementById('pending-badge');

// ── File selection ─────────────────────────────────────────────────────────────
dropZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => selectFile(fileInput.files[0]));

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) selectFile(e.dataTransfer.files[0]);
});

function selectFile(file) {
  if (!file) return;
  selectedFile = file;
  fileNameDisplay.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  reviewBtn.disabled = false;
}

// ── Pipeline progress steps ────────────────────────────────────────────────────
const pipelineSteps = ['step-parse','step-anon','step-classify','step-risk','step-redline'];

function animatePipeline() {
  let i = 0;
  pipelineSteps.forEach(id => {
    const el = document.getElementById(id);
    el.className = 'step';
  });
  const interval = setInterval(() => {
    if (i > 0) document.getElementById(pipelineSteps[i - 1]).classList.add('done');
    if (i < pipelineSteps.length) {
      document.getElementById(pipelineSteps[i]).classList.add('active');
      i++;
    } else {
      clearInterval(interval);
    }
  }, 1800);
  return interval;
}

// ── Run review ─────────────────────────────────────────────────────────────────
reviewBtn.addEventListener('click', async () => {
  if (!selectedFile) return;

  uploadSection.classList.add('hidden');
  progressSection.classList.remove('hidden');
  resultsSection.classList.add('hidden');

  const pipelineTimer = animatePipeline();

  try {
    const formData = new FormData();
    formData.append('file', selectedFile);

    const res = await fetch(`${API}/api/review`, { method: 'POST', body: formData });
    const data = await res.json();

    clearInterval(pipelineTimer);
    pipelineSteps.forEach(id => {
      document.getElementById(id).classList.remove('active');
      document.getElementById(id).classList.add('done');
    });

    if (!res.ok) {
      alert(`Error: ${data.detail || 'Review failed'}`);
      resetUI();
      return;
    }

    currentSessionId = data.session_id;
    currentRedlines = data.redlines || [];

    renderResults(data);

    progressSection.classList.add('hidden');
    resultsSection.classList.remove('hidden');
  } catch (err) {
    clearInterval(pipelineTimer);
    alert(`Network error: ${err.message}`);
    resetUI();
  }
});

// ── Render results ─────────────────────────────────────────────────────────────
function renderResults(data) {
  renderClassification(data.classification || {});
  renderRiskSummary(data.risk_summary || {});
  renderRedlines(data.redlines || []);
  updateExportStatus(data);
}

function renderClassification(clf) {
  const grid = document.getElementById('classification-grid');
  grid.innerHTML = [
    ['Contract Type',  clf.contract_type],
    ['Jurisdiction',   clf.jurisdiction],
    ['Effective Date', clf.effective_date || '—'],
    ['Term',           clf.term || '—'],
    ['Initial Risk',   clf.initial_risk_level],
    ['Key Topics',     (clf.key_topics || []).join(', ') || '—'],
  ].map(([label, value]) => `
    <div class="meta-item">
      <div class="meta-label">${label}</div>
      <div class="meta-value">${escHtml(String(value || '—'))}</div>
    </div>`).join('');

  if (clf.initial_risk_reason) {
    const note = document.createElement('p');
    note.style.cssText = 'color:var(--muted);font-size:0.83rem;margin-top:0.75rem;';
    note.textContent = clf.initial_risk_reason;
    document.getElementById('classification-card').appendChild(note);
  }
}

function renderRiskSummary(summary) {
  const barsEl = document.getElementById('risk-bars');
  const counts = summary.risk_counts || {};
  const total  = summary.total_clauses_reviewed || 1;
  const levels = [
    ['Critical', 'critical'],
    ['High',     'high'],
    ['Medium',   'medium'],
    ['Low',      'low'],
    ['None',     'none'],
  ];

  barsEl.innerHTML = levels.map(([label, cls]) => {
    const count = counts[label] || 0;
    const pct   = Math.round((count / total) * 100);
    return `
      <div class="risk-row">
        <span class="risk-label">${label}</span>
        <div class="risk-bar-track">
          <div class="risk-bar-fill ${cls}" style="width:${pct}%"></div>
        </div>
        <span class="risk-count">${count}</span>
      </div>`;
  }).join('');

  const flags = summary.high_priority_flags || [];
  const flagsEl = document.getElementById('high-priority-flags');
  if (flags.length === 0) {
    flagsEl.innerHTML = '<p class="hint" style="margin-top:1rem">No high-priority flags found.</p>';
    return;
  }
  flagsEl.innerHTML = `<div class="flag-list" style="margin-top:1rem">${
    flags.map(f => `
      <div class="flag-item">
        <span class="flag-badge badge-${f.risk_level.toLowerCase()}">${f.risk_level}</span>
        <div>
          <strong>${escHtml(f.clause_type)}</strong><br>
          <span style="color:var(--muted);font-size:0.82rem">${escHtml(f.deviation_summary)}</span>
        </div>
      </div>`).join('')
  }</div>`;
}

function renderRedlines(redlines) {
  const listEl = document.getElementById('redlines-list');
  currentRedlines = redlines;

  if (redlines.length === 0) {
    listEl.innerHTML = '<div class="empty-state">✅ No clauses required redlining — contract appears to match playbook standards.</div>';
    updatePendingBadge();
    return;
  }

  listEl.innerHTML = redlines.map((r, i) => buildRedlineHTML(r, i)).join('');

  // Attach button listeners
  redlines.forEach((_, i) => {
    document.getElementById(`accept-${i}`)?.addEventListener('click', () => decideRedline(i, 'accepted'));
    document.getElementById(`reject-${i}`)?.addEventListener('click', () => decideRedline(i, 'rejected'));
  });

  updatePendingBadge();
}

function buildRedlineHTML(r, i) {
  const statusClass = r.status || 'pending';
  const riskBadge   = r.risk_level ? `<span class="flag-badge badge-${r.risk_level.toLowerCase()}">${r.risk_level}</span>` : '';
  const statusChip  = `<span class="status-chip status-${statusClass}">${statusClass}</span>`;

  const actionBtns = r.status === 'pending' ? `
    <button class="btn accept" id="accept-${i}">✓ Accept</button>
    <button class="btn reject" id="reject-${i}">✗ Reject</button>` : '';

  return `
    <div class="redline-item ${statusClass}" id="redline-item-${i}">
      <div class="redline-header">
        <span class="redline-title">${escHtml(r.clause_type || `Clause ${i + 1}`)}</span>
        <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap">
          ${riskBadge}
          ${statusChip}
          <div class="redline-actions">${actionBtns}</div>
        </div>
      </div>
      <div class="redline-body">
        <div class="diff-block">
          <div class="diff-col original">
            <div class="diff-col-label">Original</div>
            <div class="diff-col-text">${escHtml(r.original_clause || '')}</div>
          </div>
          <div class="diff-col proposed">
            <div class="diff-col-label">Proposed Redline</div>
            <div class="diff-col-text">${escHtml(r.rewritten_clause || 'No rewrite generated.')}</div>
          </div>
        </div>
        ${r.changes_summary ? `
        <div class="redline-notes">
          <strong>Changes:</strong> ${escHtml(r.changes_summary)}
        </div>` : ''}
        ${r.negotiation_notes ? `
        <div class="redline-notes" style="border-left-color:var(--warning)">
          <strong>Negotiation Notes:</strong> ${escHtml(r.negotiation_notes)}
        </div>` : ''}
        ${r.fallback_position ? `
        <div class="redline-notes" style="border-left-color:var(--muted)">
          <strong>Fallback Position:</strong> ${escHtml(r.fallback_position)}
        </div>` : ''}
      </div>
    </div>`;
}

// ── HITL Decisions ──────────────────────────────────────────────────────────────
async function decideRedline(index, decision) {
  if (!currentSessionId) return;

  const res = await fetch(`${API}/api/decide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: currentSessionId, redline_index: index, decision }),
  });

  if (!res.ok) { alert('Failed to record decision.'); return; }

  currentRedlines[index].status = decision;

  // Re-render this specific item
  const itemEl = document.getElementById(`redline-item-${index}`);
  if (itemEl) itemEl.outerHTML = buildRedlineHTML(currentRedlines[index], index);

  // Re-attach listeners for any still-pending items
  currentRedlines.forEach((r, i) => {
    if (r.status === 'pending') {
      document.getElementById(`accept-${i}`)?.addEventListener('click', () => decideRedline(i, 'accepted'));
      document.getElementById(`reject-${i}`)?.addEventListener('click', () => decideRedline(i, 'rejected'));
    }
  });

  updatePendingBadge();
}

function updatePendingBadge() {
  const pending = currentRedlines.filter(r => r.status === 'pending').length;
  pendingBadge.textContent = `${pending} pending`;
}

function updateExportStatus(data) {
  const el = document.getElementById('export-status');
  el.textContent = `${data.pii_detected} PII items were anonymized before AI processing. ` +
    `Review completed in ${data.elapsed_seconds}s.`;
}

// ── Export ─────────────────────────────────────────────────────────────────────
document.getElementById('export-btn').addEventListener('click', async () => {
  if (!currentSessionId) return;
  const res = await fetch(`${API}/api/report/${currentSessionId}`);
  const data = await res.json();
  data.redlines = currentRedlines;

  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url;
  a.download = `legalai-report-${currentSessionId.slice(0, 8)}.json`;
  a.click();
  URL.revokeObjectURL(url);
});

document.getElementById('new-review-btn').addEventListener('click', resetUI);

function resetUI() {
  uploadSection.classList.remove('hidden');
  progressSection.classList.add('hidden');
  resultsSection.classList.add('hidden');
  selectedFile = null;
  currentSessionId = null;
  currentRedlines = [];
  fileInput.value = '';
  fileNameDisplay.textContent = '';
  reviewBtn.disabled = true;
  document.getElementById('classification-grid').innerHTML = '';
  document.getElementById('risk-bars').innerHTML = '';
  document.getElementById('high-priority-flags').innerHTML = '';
  document.getElementById('redlines-list').innerHTML = '';
}

// ── Playbook Manager ───────────────────────────────────────────────────────────
async function loadPlaybookStatus() {
  try {
    const res  = await fetch(`${API}/api/playbook/status`);
    const data = await res.json();
    const el   = document.getElementById('playbook-status');
    el.innerHTML = `<strong>${data.total_clauses}</strong> standard clauses loaded` +
      (data.clause_types.length ? ` · Types: <em>${data.clause_types.join(', ')}</em>` : ' · No clauses yet');
  } catch {
    document.getElementById('playbook-status').textContent = 'Could not reach API';
  }
}

document.getElementById('add-clause-btn').addEventListener('click', async () => {
  const type = document.getElementById('clause-type').value.trim();
  const text = document.getElementById('clause-text').value.trim();
  if (!type || !text) { alert('Please fill in both Clause Type and Text.'); return; }

  const res  = await fetch(`${API}/api/playbook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clause_type: type, text }),
  });
  const data = await res.json();
  if (data.ok) {
    alert(`Added! Playbook now has ${data.total_clauses} clauses.`);
    document.getElementById('clause-type').value = '';
    document.getElementById('clause-text').value = '';
    loadPlaybookStatus();
  }
});

document.getElementById('upload-playbook-btn').addEventListener('click', async () => {
  const fileEl = document.getElementById('playbook-file');
  if (!fileEl.files[0]) { alert('Select a JSON file first.'); return; }

  const formData = new FormData();
  formData.append('file', fileEl.files[0]);

  const res  = await fetch(`${API}/api/playbook/bulk`, { method: 'POST', body: formData });
  const data = await res.json();
  if (data.ok) {
    alert(`Loaded ${data.clauses_added} clauses. Total: ${data.total_clauses}`);
    loadPlaybookStatus();
  } else {
    alert(`Error: ${JSON.stringify(data)}`);
  }
});

// ── Helpers ────────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Init ───────────────────────────────────────────────────────────────────────
loadPlaybookStatus();
