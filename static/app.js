const defaultWeights = {
  technical_compliance: 0.3,
  price_competitiveness: 0.25,
  relevant_experience: 0.2,
  delivery_timeline: 0.15,
  eligibility_and_documentation: 0.1,
};

const WEIGHT_LABELS = {
  technical_compliance: 'Technical compliance',
  price_competitiveness: 'Price competitiveness',
  relevant_experience: 'Relevant experience',
  delivery_timeline: 'Delivery timeline',
  eligibility_and_documentation: 'Eligibility & documentation',
};

const CRITERIA_KEYS = [
  ['technicalComplianceScore', 'Technical'],
  ['priceCompetitivenessScore', 'Price'],
  ['relevantExperienceScore', 'Experience'],
  ['deliveryTimelineScore', 'Delivery'],
  ['eligibilityDocumentationScore', 'Eligibility'],
];

const LIMITS = {
  maxFileBytes: 10 * 1024 * 1024,
  maxFilesPerVendor: 10,
  maxVendors: 20,
  maxRequestBytes: 50 * 1024 * 1024,
  allowedExtensions: ['.pdf', '.txt'],
};

const PROGRESS_STEPS = [
  { key: 'extracting', label: 'Extract documents' },
  { key: 'preparing', label: 'Prepare analysis' },
  { key: 'verifying', label: 'Verify inference' },
  { key: 'evaluation_completed', label: 'Score & rank' },
  { key: 'cleanup_completed', label: 'Cleanup' },
];

const VIEW_META = {
  overview: ['Overview', 'Command centre for confidential tender evaluation'],
  evaluate: ['Evaluate', 'Configure a tender and submit bids for verified AI evaluation'],
  'manual-scoring': ['Manual Scoring', 'Enter bidder scores for manual evaluation'],
  results: ['Results', 'Winning bidder, score breakdown and evidence'],
  verification: ['Evaluation Integrity', 'Application integrity and evaluation status'],
  history: ['History', 'Session-only evaluation records'],
  privacy: ['Privacy', 'How BIDVEIL handles your documents'],
  about: ['About', 'Architecture and technology'],
};

const sessionEvaluations = [];
let lastPayload = null;
let lastResult = null;
let currentView = 'overview';
let evaluating = false;

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}[character]));

const el = (id) => document.getElementById(id);
const fmtBytes = (bytes) => {
  if (!bytes) return '0 MB';
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
};

/* ================= Toasts & modal ================= */

const toast = (message, type = 'info') => {
  const root = el('toastRoot');
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.textContent = message;
  root.appendChild(node);
  setTimeout(() => {
    node.classList.add('out');
    setTimeout(() => node.remove(), 350);
  }, 4200);
};

const openModal = (title, bodyHtml) => {
  const root = el('modalRoot');
  root.innerHTML = `
    <div class="modal-scrim" id="modalScrim">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-head"><h3>${escapeHtml(title)}</h3>
          <button class="icon-btn" id="modalClose" aria-label="Close">✕</button>
        </div>
        <div class="modal-body">${bodyHtml}</div>
      </div>
    </div>`;
  const close = () => { root.innerHTML = ''; };
  el('modalClose').addEventListener('click', close);
  el('modalScrim').addEventListener('click', (event) => { if (event.target.id === 'modalScrim') close(); });
  document.addEventListener('keydown', function onKey(event) {
    if (event.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); }
  });
};

/* ================= Navigation ================= */

const switchView = (name) => {
  if (!VIEW_META[name]) return;
  currentView = name;
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.view === name);
  });
  document.querySelectorAll('.view').forEach((view) => {
    view.classList.toggle('active', view.id === `view-${name}`);
  });
  el('pageTitle').textContent = VIEW_META[name][0];
  el('pageSubtitle').textContent = VIEW_META[name][1];
  closeSidebar();
  window.scrollTo({ top: 0 });
};

const openSidebar = () => {
  el('sidebar').classList.add('open');
  el('sidebarScrim').classList.add('show');
};
const closeSidebar = () => {
  el('sidebar').classList.remove('open');
  el('sidebarScrim').classList.remove('show');
};

/* ================= Vendor cards & file queues ================= */

const fileIcon = (name) => (name.toLowerCase().endsWith('.pdf') ? '📄' : '📃');

const validateFile = (file) => {
  const ext = `.${(file.name.split('.').pop() || '').toLowerCase()}`;
  if (!LIMITS.allowedExtensions.includes(ext)) return `${file.name}: unsupported type (PDF or TXT only)`;
  if (file.size === 0) return `${file.name}: file is empty`;
  if (file.size > LIMITS.maxFileBytes) return `${file.name}: exceeds 10 MB limit`;
  return null;
};

const renderFileQueue = (card) => {
  const queue = card._fileQueue || [];
  const container = card.querySelector('.file-queue');
  if (!container) return;
  if (!queue.length) {
    container.innerHTML = '';
    updateReadiness();
    return;
  }
  container.innerHTML = queue.map((entry, index) => `
    <div class="file-item ${entry.error ? 'invalid' : ''}">
      <span class="file-icon">${fileIcon(entry.file.name)}</span>
      <span class="file-name" title="${escapeHtml(entry.file.name)}">${escapeHtml(entry.file.name)}</span>
      <span class="file-meta">${fmtBytes(entry.file.size)}</span>
      <span class="file-actions">
        ${entry.file.name.toLowerCase().endsWith('.txt') ? `<button type="button" data-preview="${index}" title="Preview text">👁</button>` : ''}
        <button type="button" class="remove" data-remove="${index}" title="Remove file">✕</button>
      </span>
      ${entry.error ? `<span class="file-error">${escapeHtml(entry.error)}</span>` : ''}
    </div>`).join('');

  container.querySelectorAll('[data-remove]').forEach((button) => {
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      queue.splice(Number(button.dataset.remove), 1);
      renderFileQueue(card);
    });
  });
  container.querySelectorAll('[data-preview]').forEach((button) => {
    button.addEventListener('click', async (event) => {
      event.stopPropagation();
      const entry = queue[Number(button.dataset.preview)];
      if (!entry) return;
      try {
        const text = await entry.file.text();
        openModal(`Preview — ${entry.file.name}`, `<pre>${escapeHtml(text.slice(0, 20000))}${text.length > 20000 ? '\n… (truncated)' : ''}</pre>`);
      } catch {
        toast('Could not read file for preview.', 'error');
      }
    });
  });
  updateReadiness();
};

const addFilesToCard = (card, fileList) => {
  const queue = card._fileQueue || (card._fileQueue = []);
  Array.from(fileList || []).forEach((file) => {
    if (queue.length >= LIMITS.maxFilesPerVendor) {
      toast(`Maximum ${LIMITS.maxFilesPerVendor} documents per bidder.`, 'error');
      return;
    }
    const error = validateFile(file);
    queue.push({ file, error });
    if (error) toast(error, 'error');
  });
  renderFileQueue(card);
};

const createVendorCard = (name = '', price = '', proposal = '') => `
  <div class="vendor-card">
    <div class="vendor-card-header">
      <input class="vendor-name" value="${escapeHtml(name)}" placeholder="Bidder / vendor name" aria-label="Vendor name" />
      <button class="remove-vendor" type="button">Remove</button>
    </div>
    <div class="vendor-grid">
      <div class="field-group">
        <label>Quoted price</label>
        <input class="vendor-price" type="number" min="0" value="${escapeHtml(price)}" placeholder="250000" />
      </div>
      <div class="field-group">
        <label>Proposal summary</label>
        <textarea class="vendor-proposal" rows="2" placeholder="Describe the bid…">${escapeHtml(proposal)}</textarea>
      </div>
    </div>
    <div class="field-group" style="margin-bottom:0">
      <label>Bid documents</label>
      <div class="dropzone" tabindex="0" role="button" aria-label="Upload bid documents">
        <strong>Drop files here</strong> or click to browse — PDF / TXT, 10 MB max
        <input class="vendor-files" type="file" multiple accept=".pdf,.txt" hidden />
      </div>
      <div class="file-queue"></div>
    </div>
  </div>
`;

const bindVendorCard = (card) => {
  card._fileQueue = card._fileQueue || [];

  const remove = card.querySelector('.remove-vendor');
  remove.addEventListener('click', () => {
    const container = el('vendorList');
    if (container.children.length > 1) {
      card.remove();
      updateReadiness();
    } else {
      toast('At least one bidder is required.', 'error');
    }
  });

  const dropzone = card.querySelector('.dropzone');
  const fileInput = card.querySelector('.vendor-files');

  dropzone.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener('change', () => {
    addFilesToCard(card, fileInput.files);
    fileInput.value = '';
  });

  ['dragenter', 'dragover'].forEach((type) => {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.add('drag-active');
    });
  });
  ['dragleave', 'drop'].forEach((type) => {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.remove('drag-active');
    });
  });
  dropzone.addEventListener('drop', (event) => {
    addFilesToCard(card, event.dataTransfer?.files);
  });

  card.querySelector('.vendor-name').addEventListener('input', updateReadiness);
};

const renderVendorCards = (vendors) => {
  const container = el('vendorList');
  container.innerHTML = vendors.map((vendor) => createVendorCard(vendor.name, vendor.price, vendor.proposal)).join('');
  container.querySelectorAll('.vendor-card').forEach(bindVendorCard);
  updateReadiness();
};

const getFormState = () => {
  const cards = Array.from(document.querySelectorAll('.vendor-card'));
  return {
    tender: {
      title: el('tenderTitle').value,
      description: el('tenderDescription').value,
      maximumBudget: Number(el('maximumBudget').value || 0),
      deadline: el('submissionDeadline').value,
      eligibilityRequirements: el('eligibilityRequirements').value,
      technicalRequirements: el('technicalRequirements').value,
      evaluationCriteria: el('evaluationCriteria').value,
      weights: defaultWeights,
    },
    bids: cards.map((card) => ({
      vendorName: card.querySelector('.vendor-name').value || 'Unnamed vendor',
      quotedPrice: Number(card.querySelector('.vendor-price').value || 0),
      proposalText: card.querySelector('.vendor-proposal').value || '',
    })),
    evaluationMode: el('evaluationMode').value || 'auto',
  };
};

const updateReadiness = () => {
  const cards = Array.from(document.querySelectorAll('.vendor-card'));
  let docs = 0;
  let bytes = 0;
  cards.forEach((card) => {
    (card._fileQueue || []).forEach((entry) => {
      docs += 1;
      bytes += entry.file.size;
    });
  });
  el('rdVendors').textContent = String(cards.length);
  el('rdDocs').textContent = String(docs);
  el('rdSize').textContent = fmtBytes(bytes);
};

const loadDemo = () => {
  el('tenderTitle').value = 'Modern Secure Government Data Platform';
  el('tenderDescription').value = 'Procurement for a secure government data platform with migration, governance, and modernization requirements.';
  el('maximumBudget').value = '1000000';
  el('submissionDeadline').value = '2026-12-31';
  el('eligibilityRequirements').value = 'Vendor must have three comparable public sector modernizations and valid security certifications.';
  el('technicalRequirements').value = 'Need secure integration, RBAC, encrypted data transport, monitoring, and phased rollout.';
  el('evaluationCriteria').value = 'Technical compliance, price competitiveness, relevant experience, delivery timeline, eligibility and documentation.';

  renderVendorCards([
    { name: 'Northstar Systems', price: '740000', proposal: 'Fictional Vendor A: lower quotation with moderate technical compliance, phased migration, and a 10-month delivery window.' },
    { name: 'Meridian Consulting', price: '910000', proposal: 'Fictional Vendor B: higher quotation with excellent technical compliance, SOC 2 controls, comparable deployments, and a 7-month delivery window.' },
    { name: 'Helio DataWorks', price: '820000', proposal: 'Fictional Vendor C: competitive quotation with incomplete documentation and missing security certification evidence.' },
  ]);
  toast('Demo tender loaded — sample bidders are fictional.', 'info');
};

/* ================= Validation ================= */

const validateForm = () => {
  const errors = [];
  const cards = Array.from(document.querySelectorAll('.vendor-card'));

  if (!cards.length) errors.push('At least one bidder is required.');
  if (cards.length > LIMITS.maxVendors) {
    errors.push(`At most ${LIMITS.maxVendors} bidders are allowed (found ${cards.length}).`);
  }

  let totalBytes = 0;
  cards.forEach((card, index) => {
    const label = card.querySelector('.vendor-name').value || `Bidder ${index + 1}`;
    const queue = card._fileQueue || [];
    if (queue.length > LIMITS.maxFilesPerVendor) {
      errors.push(`${label}: at most ${LIMITS.maxFilesPerVendor} documents (found ${queue.length}).`);
    }
    queue.forEach((entry) => {
      totalBytes += entry.file.size;
      if (entry.error) errors.push(`${label}: ${entry.error}`);
    });
  });

  if (totalBytes > LIMITS.maxRequestBytes) {
    errors.push(`Total upload size exceeds the 50 MB request limit (${fmtBytes(totalBytes)}).`);
  }

  const budget = Number(el('maximumBudget').value || 0);
  if (budget < 0) errors.push('Maximum budget cannot be negative.');

  return errors;
};

const showFormErrors = (errors) => {
  const box = el('formErrors');
  if (!errors.length) {
    box.hidden = true;
    box.innerHTML = '';
    return;
  }
  box.hidden = false;
  box.innerHTML = `<strong>Fix the following before evaluating:</strong><ul>${errors.map((e) => `<li>${escapeHtml(e)}</li>`).join('')}</ul>`;
};

/* ================= Progress stepper ================= */

const resetProgress = () => {
  el('progressPanel').hidden = false;
  el('progressSteps').innerHTML = PROGRESS_STEPS.map((step) => `
    <div class="pstep" data-step="${step.key}">
      <span class="pstep-dot"></span><span>${step.label}</span>
    </div>`).join('');
  el('processingDetails').innerHTML = '';
};

const markStep = (key, status) => {
  const step = el('progressSteps').querySelector(`[data-step="${key}"]`);
  if (!step) return;
  step.classList.remove('active', 'done', 'failed');
  step.classList.add(status);
};

const STATE_TO_STEP = {
  extracting: 'extracting',
  preparing: 'preparing',
  verifying: 'verifying',
  scoring: 'verifying',
  evaluation_completed: 'evaluation_completed',
  cleanup_completed: 'cleanup_completed',
  cleanup_failed: 'cleanup_completed',
  failed: 'evaluation_completed',
  verification_unavailable: 'verifying',
};

const handleProgressState = (state, status) => {
  const key = STATE_TO_STEP[state];
  if (!key) return;
  const index = PROGRESS_STEPS.findIndex((step) => step.key === key);
  PROGRESS_STEPS.forEach((step, i) => {
    if (i < index) markStep(step.key, 'done');
    else if (i === index) markStep(step.key, state === 'failed' || state === 'verification_unavailable' || state === 'cleanup_failed' ? 'failed' : 'active');
  });
  if (state === 'cleanup_completed') markStep('cleanup_completed', 'done');
};

const appendLog = (text) => {
  const list = el('processingDetails');
  const item = document.createElement('li');
  item.textContent = text;
  list.appendChild(item);
  list.scrollTop = list.scrollHeight;
};

/* ================= SSE ================= */

const readEvaluationStream = async (response) => {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalEvent = null;

  const handleMessage = (message) => {
    const dataLine = message.split(/\r?\n/).find((line) => line.startsWith('data:'));
    if (!dataLine) return;
    const event = JSON.parse(dataLine.slice(5).trim());
    if (event.type === 'state') {
      handleProgressState(event.state || '', event.status || '');
      appendLog(event.status || event.state || 'Processing…');
    } else if (event.type === 'result') {
      finalEvent = event;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const messages = buffer.split(/\r?\n\r?\n/);
    buffer = messages.pop() || '';
    messages.forEach(handleMessage);
    if (done) break;
  }
  if (buffer.trim()) handleMessage(buffer);
  if (!finalEvent) throw new Error('Evaluation stream ended without a result.');
  return finalEvent;
};

/* ================= Verification centre ================= */

const verificationExplanationFor = (state, verification = {}) => {
  switch (state) {
    case 'INFERENCE_COMPLETED':
      return 'Inference completed successfully. Evaluation results are available.';
    case 'INFERENCE_FAILED':
      return 'Inference failed. The evaluation result is not trustworthy and should not be used.';
    case 'INFERENCE_UNAVAILABLE':
      return 'No inference provider is configured. Configure a provider to enable evaluation.';
    case 'INFERENCE_PENDING':
      return 'Inference is in progress.';
    default:
      return verification.status || 'Waiting for evaluation.';
  }
};

const badgeClassFor = (state) => {
  const map = {
    INFERENCE_COMPLETED: 'success',
    INFERENCE_PENDING: 'warning',
    INFERENCE_FAILED: 'danger',
    INFERENCE_UNAVAILABLE: 'danger',
    WAITING: 'neutral',
  };
  return map[state] || 'neutral';
};

const triState = (value) => {
  if (value === true) return { text: 'Verified', cls: 'ok' };
  if (value === false) return { text: 'Failed', cls: 'bad' };
  return { text: 'Not performed', cls: 'muted' };
};

const updateVerificationCard = (verification = {}) => {
  const state = verification.state || 'WAITING';

  const badge = el('verificationBadge');
  badge.textContent = state;
  badge.className = `badge badge-lg ${badgeClassFor(state)}`;
  el('verificationMode').textContent = `mode: ${verification.mode || '—'}`;
  el('verificationExplanation').textContent = verificationExplanationFor(state, verification);

  // Application integrity stats
  const validation = triState(verification.validationVerified !== false);
  const extraction = triState(verification.extractionVerified !== false);
  const cleanup = triState(verification.cleanupVerified !== false);

  const setStat = (id, st) => {
    el(id).querySelector('strong').textContent = st.text;
    el(id).className = `stat-card verify-stat ${st.cls}`;
  };
  setStat('vsValidationState', validation);
  setStat('vsExtractionState', extraction);
  setStat('vsCleanupState', cleanup);

  // Lifecycle timeline — application integrity steps
  const reached = {
    WAITING: [],
    INFERENCE_PENDING: ['validation', 'extraction'],
    INFERENCE_COMPLETED: ['validation', 'extraction', 'inference', 'scoring', 'cleanup'],
    INFERENCE_FAILED: ['validation', 'extraction'],
    INFERENCE_UNAVAILABLE: [],
  }[state] || [];
  const failedAt = state === 'INFERENCE_FAILED' ? 'inference' : null;
  const unavailable = state === 'INFERENCE_UNAVAILABLE';

  document.querySelectorAll('#verifyTimeline li').forEach((li) => {
    const step = li.dataset.step;
    li.classList.remove('done', 'active', 'failed', 'todo');
    if (unavailable) { li.classList.add('todo'); return; }
    const idx = reached.indexOf(step);
    if (failedAt === step) li.classList.add('failed');
    else if (idx === reached.length - 1 && state !== 'INFERENCE_FAILED') li.classList.add('done');
    else if (idx >= 0) li.classList.add('done');
    else li.classList.add('todo');
  });

  // Evidence detail grid
  const rows = [
    ['Evaluation status', state, true],
    ['Mode', verification.mode || '—', true],
    ['Model', verification.model || 'not configured', true],
    ['Failure explanation', verification.failureReason || verification.status || 'none', false],
  ];
  el('verificationDetails').innerHTML = rows.map(([k, v, mono]) => `
    <div class="dk">${escapeHtml(k)}</div><div class="dv ${mono ? '' : 'wrap'}">${escapeHtml(v)}</div>`).join('');

  const notice = el('verificationUnavailable');
  if (state === 'INFERENCE_UNAVAILABLE' || state === 'INFERENCE_FAILED') {
    notice.hidden = false;
    el('verificationUnavailableText').textContent = verification.failureReason || verification.status || '';
  } else {
    notice.hidden = true;
  }

  // Nav badge reflects latest state
  const navBadge = el('verifyNavBadge');
  if (state === 'INFERENCE_COMPLETED') { navBadge.hidden = false; navBadge.textContent = 'OK'; }
  else if (state === 'INFERENCE_FAILED' || state === 'INFERENCE_UNAVAILABLE') { navBadge.hidden = false; navBadge.textContent = '!'; }
  else navBadge.hidden = true;
};

const renderProcessingFinal = (processing = [], documents = []) => {
  const list = el('processingDetails');
  list.innerHTML = '';
  const entries = [
    ...processing.map((item) => item.status),
    ...documents.map((doc) => `${doc.fileName}: ${doc.status}${doc.message ? ` — ${doc.message}` : ''}`),
  ];
  entries.forEach(appendLog);
  if (!entries.length) appendLog('No processing events recorded.');
};

/* ================= Results ================= */

const barChart = (items, { winnerName = null, valueSuffix = '' } = {}) => items.map((item) => {
  const pct = Math.max(2, Math.min(100, Number(item.value) || 0));
  const isWinner = winnerName && item.label === winnerName;
  return `
    <div class="chart-row ${isWinner ? 'winner' : ''}">
      <span class="chart-label" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>
      <div class="chart-bar-track"><div class="chart-bar ${item.alt ? 'alt' : ''}" style="width:${pct}%"></div></div>
      <span class="chart-value">${escapeHtml(item.display ?? item.value)}${valueSuffix}</span>
    </div>`;
}).join('');

const renderResults = (data) => {
  lastResult = data;
  const vendors = Array.isArray(data.vendors) ? data.vendors : [];
  const summary = data.summary || {};
  const verification = data.verification || {};

  el('resultsEmpty').hidden = true;
  el('resultsContent').hidden = false;

  const winner = vendors.find((v) => v.rank === 1) || vendors[0];
  el('winnerName').textContent = summary.winner || winner?.vendorName || '—';
  el('winnerSub').textContent = winner?.evidenceSummary
    ? String(winner.evidenceSummary).slice(0, 220)
    : 'Evidence summary not provided by the evaluation.';
  el('winnerScoreChip').textContent = winner ? `Score ${winner.weightedScore ?? '—'}` : '—';
  el('winnerPriceChip').textContent = winner ? `Quote $${Number(winner.quotedPrice || 0).toLocaleString()}` : '—';
  el('winnerVerifyChip').textContent = `Verification: ${verification.state || '—'}`;

  el('averageScore').textContent = typeof summary.averageScore === 'number' ? `${summary.averageScore} / 100` : '—';
  el('vendorCount').textContent = String(vendors.length);
  el('modelName').textContent = data.evaluationMode === 'manual' ? 'Manual' : (verification.model || '—');
  el('resultVerifyState').textContent = data.evaluationMode === 'manual' ? 'Manual evaluation' : (verification.state || '—');

  // Weighted score chart
  el('scoreChart').innerHTML = vendors.length
    ? barChart(vendors.map((v) => ({
        label: v.vendorName,
        value: v.weightedScore ?? 0,
        display: v.weightedScore ?? '—',
      })), { winnerName: summary.winner || winner?.vendorName })
    : '<p class="empty-state">No vendors returned.</p>';

  // Criteria chart — winner's per-criteria scores
  const critItems = winner
    ? CRITERIA_KEYS.map(([key, label]) => ({ label, value: winner[key] ?? 0, display: winner[key] ?? '—', alt: true }))
    : [];
  el('criteriaChart').innerHTML = critItems.length
    ? barChart(critItems)
    : '<p class="empty-state">Criteria scores unavailable.</p>';
  el('weightLegend').innerHTML = Object.entries(WEIGHT_LABELS).map(([key, label]) =>
    `<span class="chip" data-tip="${escapeHtml(label)}">${escapeHtml(label)} · ${Math.round((defaultWeights[key] || 0) * 100)}%</span>`).join('');

  // Rankings table
  const tbody = el('rankingsBody');
  tbody.innerHTML = vendors.length
    ? vendors.map((v) => `
      <tr>
        <td><strong>#${escapeHtml(v.rank)}</strong></td>
        <td>${escapeHtml(v.vendorName)}</td>
        <td class="col-score">
          <div class="score-cell">
            <div class="mini-track"><div class="mini-fill ${v.rank === 1 ? 'top' : ''}" style="width:${Math.min(100, Number(v.weightedScore) || 0)}%"></div></div>
            <span class="mono">${escapeHtml(v.weightedScore ?? '—')}</span>
          </div>
        </td>
        <td>$${escapeHtml(Number(v.quotedPrice || 0).toLocaleString())}</td>
        <td>${escapeHtml((v.riskIndicators || [])[0] || 'Low')}</td>
      </tr>`).join('')
    : '<tr><td colspan="5" class="empty-cell">No vendors returned.</td></tr>';

  // Rationale — built only from returned fields
  const rationale = [];
  if (winner) {
    rationale.push(`<p class="rationale-winner">${escapeHtml(summary.winner || winner.vendorName)} is the recommended awardee</p>`);
    if (winner.evidenceSummary) rationale.push(`<p>${escapeHtml(winner.evidenceSummary)}</p>`);
    if ((winner.strengths || []).length) rationale.push(`<p><strong>Strengths:</strong> ${escapeHtml(winner.strengths.join(', '))}</p>`);
    if ((winner.weaknesses || []).length) rationale.push(`<p><strong>Weaknesses:</strong> ${escapeHtml(winner.weaknesses.join(', '))}</p>`);
    if ((winner.missingInformation || []).length) rationale.push(`<p><strong>Missing information:</strong> ${escapeHtml(winner.missingInformation.join(', '))}</p>`);
  } else {
    rationale.push('<p>No recommendation could be derived from the evaluation response.</p>');
  }
  el('rationaleBox').innerHTML = rationale.join('');

  // Risk panel
  const riskVendors = vendors.filter((v) => (v.riskIndicators || []).length);
  el('riskPanel').innerHTML = riskVendors.length
    ? riskVendors.map((v) => `
      <div class="risk-item">
        <span class="risk-vendor">${escapeHtml(v.vendorName)}</span>
        <ul>${v.riskIndicators.map((r) => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
      </div>`).join('')
    : '<p class="risk-none">No risk indicators reported by the evaluation.</p>';

  // Evidence detail cards
  el('vendorDetails').innerHTML = vendors.length
    ? vendors.map((v) => `
      <div class="evidence-card">
        <h3>#${escapeHtml(v.rank)} · ${escapeHtml(v.vendorName)}</h3>
        <p>${escapeHtml(v.evidenceSummary || 'Evidence summary not available.')}</p>
        <div class="metric-grid">
          ${CRITERIA_KEYS.map(([key, label]) => `<div class="metric"><label>${label}</label><strong>${escapeHtml(v[key] ?? '—')}</strong></div>`).join('')}
          <div class="metric"><label>Weighted</label><strong>${escapeHtml(v.weightedScore ?? '—')}</strong></div>
        </div>
        <p><strong>Strengths:</strong> ${escapeHtml((v.strengths || []).join(', ') || 'Not specified')}</p>
        <p><strong>Weaknesses:</strong> ${escapeHtml((v.weaknesses || []).join(', ') || 'Not specified')}</p>
        <p><strong>Risk indicators:</strong> ${escapeHtml((v.riskIndicators || []).join(', ') || 'No notable risks')}</p>
        <p><strong>Missing information:</strong> ${escapeHtml((v.missingInformation || []).join(', ') || 'None identified')}</p>
      </div>`).join('')
    : '<p class="empty-state">No vendor evidence returned.</p>';

  const badge = el('resultsBadge');
  badge.hidden = false;
  badge.textContent = String(vendors.length);
};

/* ================= Report export ================= */

const downloadReport = () => {
  if (!lastResult) { toast('No evaluation result to export.', 'error'); return; }
  const data = lastResult;
  const vendors = data.vendors || [];
  const verification = data.verification || {};
  const rows = vendors.map((v) => `
    <tr><td>${v.rank}</td><td>${escapeHtml(v.vendorName)}</td><td>${v.weightedScore ?? '—'}</td>
    <td>$${Number(v.quotedPrice || 0).toLocaleString()}</td>
    <td>${escapeHtml((v.riskIndicators || []).join('; ') || 'None')}</td></tr>`).join('');
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>BIDVEIL Evaluation Report</title>
<style>body{font-family:system-ui,sans-serif;max-width:860px;margin:40px auto;color:#1a2433}h1{font-size:22px}table{border-collapse:collapse;width:100%;margin:16px 0}td,th{border:1px solid #ccc;padding:8px 10px;text-align:left;font-size:13px}th{background:#f0f4fa}.meta{color:#555;font-size:13px}code{font-family:monospace;font-size:12px}</style></head><body>
<h1>BIDVEIL Evaluation Report</h1>
<p class="meta">Generated ${new Date().toISOString()} · Tender: ${escapeHtml(lastPayload?.tender?.title || '—')} · Model: ${escapeHtml(verification.model || '—')}</p>
<p><strong>Recommended awardee:</strong> ${escapeHtml(data.summary?.winner || '—')} · <strong>Average score:</strong> ${data.summary?.averageScore ?? '—'} · <strong>Verification state:</strong> ${escapeHtml(verification.state || '—')}</p>
<table><thead><tr><th>Rank</th><th>Bidder</th><th>Score</th><th>Price</th><th>Risk</th></tr></thead><tbody>${rows}</tbody></table>
<h2>Verification evidence</h2>
<p class="meta">State: ${escapeHtml(verification.state || '—')} · Signature kind: ${escapeHtml(verification.responseSignatureKind || verification.signatureType || '—')} · Nonce: ${escapeHtml(verification.nonce || '—')} · Completion: ${escapeHtml(verification.completionId || '—')} · Signed model: ${escapeHtml(verification.signedModelId || '—')}</p>
<p class="meta">AI-assisted decision support only. Not an automatic or legally binding procurement decision.</p>
</body></html>`;
  const blob = new Blob([html], { type: 'text/html' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `bidveil-report-${Date.now()}.html`;
  link.click();
  URL.revokeObjectURL(url);
  toast('Report downloaded.', 'success');
};

/* ================= Session history ================= */

const recordSessionEvaluation = (data) => {
  const verification = data.verification || {};
  const entry = {
    timestamp: new Date(),
    tenderTitle: lastPayload?.tender?.title || 'Untitled tender',
    winner: data.summary?.winner || '—',
    state: verification.state || 'UNKNOWN',
    averageScore: typeof data.summary?.averageScore === 'number' ? data.summary.averageScore : null,
    vendorCount: Array.isArray(data.vendors) ? data.vendors.length : 0,
    result: data,
  };
  sessionEvaluations.unshift(entry);
  renderSessionActivity();
  renderHistory();
};

const renderSessionActivity = () => {
  el('ssCount').textContent = String(sessionEvaluations.length);
  const latest = sessionEvaluations[0];
  el('ssLastState').textContent = latest ? latest.state : '—';
  el('ssLastWinner').textContent = latest ? latest.winner : '—';

  const container = el('sessionActivity');
  if (!sessionEvaluations.length) {
    container.innerHTML = '<div class="empty-state"><p>No evaluations yet this session.</p><button class="btn btn-sm btn-primary" id="ctaEvaluate2b">Start your first evaluation</button></div>';
    el('ctaEvaluate2b').addEventListener('click', () => switchView('evaluate'));
    return;
  }
  container.innerHTML = sessionEvaluations.slice(0, 5).map((entry) => `
    <div class="activity-item">
      <span class="activity-title">${escapeHtml(entry.tenderTitle)}</span>
      <span class="activity-meta">${escapeHtml(entry.state)} · ${escapeHtml(entry.winner)} · ${entry.timestamp.toLocaleTimeString()}</span>
    </div>`).join('');
};

const historyFilters = () => ({
  query: (el('historySearch').value || '').toLowerCase(),
  state: el('historyFilter').value,
});

const renderHistory = () => {
  const { query, state } = historyFilters();
  const filtered = sessionEvaluations.filter((entry) => {
    if (state && entry.state !== state) return false;
    if (query && !`${entry.tenderTitle} ${entry.winner} ${entry.state}`.toLowerCase().includes(query)) return false;
    return true;
  });

  const container = el('historyList');
  if (!sessionEvaluations.length) {
    container.innerHTML = '<div class="empty-state"><p>No evaluations recorded yet this session.</p></div>';
    return;
  }
  if (!filtered.length) {
    container.innerHTML = '<div class="empty-state"><p>No records match the current filters.</p></div>';
    return;
  }
  container.innerHTML = filtered.map((entry, index) => `
    <div class="activity-item">
      <span class="activity-title">${escapeHtml(entry.tenderTitle)}</span>
      <span class="activity-meta">${escapeHtml(entry.timestamp.toLocaleString())} · ${escapeHtml(entry.state)} · winner: ${escapeHtml(entry.winner)}${entry.averageScore !== null ? ` · avg ${entry.averageScore}` : ''} · ${entry.vendorCount} bidders</span>
      <span style="margin-top:6px"><button class="btn btn-sm btn-ghost" data-load="${sessionEvaluations.indexOf(entry)}" type="button">View result</button></span>
    </div>`).join('');

  container.querySelectorAll('[data-load]').forEach((button) => {
    button.addEventListener('click', () => {
      const entry = sessionEvaluations[Number(button.dataset.load)];
      if (entry?.result) {
        lastResult = entry.result;
        renderResults(entry.result);
        updateVerificationCard(entry.result.verification || {});
        switchView('results');
      }
    });
  });
};

/* ================= Health ================= */

const loadHealth = async () => {
  const pill = el('serviceStatus');
  const pillText = el('serviceStatusText');
  try {
    const res = await fetch('/api/health');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const health = await res.json();

    el('ovApiStatus').textContent = health.status === 'ok' ? 'Operational' : 'Degraded';
    el('ovApiHint').textContent = 'BIDVEIL service responding';
    el('ovModel').textContent = health.inferenceProvider || 'none';
    ['hcApi', 'hcModel'].forEach((id) => el(id).classList.add('loaded'));

    if (health.inferenceProvider && health.inferenceProvider !== 'none') {
      pill.className = 'status-pill status-ok';
      pillText.textContent = 'Provider configured';
    } else {
      pill.className = 'status-pill status-degraded';
      pillText.textContent = 'No provider configured';
    }

    el('ovVerificationNote').textContent = health.inferenceProvider && health.inferenceProvider !== 'none'
      ? 'An inference provider is configured. Evaluations will include provider metadata.'
      : 'No inference provider is configured. Evaluations will fail with INFERENCE_UNAVAILABLE.';
  } catch (error) {
    pill.className = 'status-pill status-error';
    pillText.textContent = 'Service unreachable';
    el('ovApiStatus').textContent = 'Unreachable';
    el('ovApiHint').textContent = error.message;
    el('ovModel').textContent = '—';
    ['hcApi', 'hcModel'].forEach((id) => el(id).classList.add('loaded'));
    el('ovVerificationNote').textContent = 'Service status could not be determined.';
  }
};

/* ================= Evaluation ================= */

const handleEvaluate = async () => {
  if (evaluating) return;
  const errors = validateForm();
  showFormErrors(errors);
  if (errors.length) {
    toast(`${errors.length} issue${errors.length > 1 ? 's' : ''} must be fixed before evaluation.`, 'error');
    return;
  }

  evaluating = true;
  const button = el('evaluateButton');
  button.disabled = true;
  button.textContent = 'Evaluating…';
  resetProgress();
  appendLog('Uploading documents');
  el('verificationUnavailable').hidden = true;

  try {
    lastPayload = getFormState();
    const cards = Array.from(document.querySelectorAll('.vendor-card'));
    const formData = new FormData();
    formData.append('payload', JSON.stringify(lastPayload));
    let hasUploads = false;
    cards.forEach((card, index) => {
      (card._fileQueue || []).forEach((entry) => {
        formData.append(`bid_${index}`, entry.file, entry.file.name);
        hasUploads = true;
      });
    });
    if (!hasUploads) appendLog('No documents — evaluating proposal text only');

    const res = await fetch('/api/evaluate/stream', { method: 'POST', body: formData });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      renderProcessingFinal(data.processing || [], data.documents || []);
      updateVerificationCard(data.verification || {});
      throw new Error(data.error || `Evaluation request failed (HTTP ${res.status}).`);
    }

    const streamEvent = await readEvaluationStream(res);
    const data = streamEvent.result;
    renderProcessingFinal(data.processing || [], data.documents || []);
    updateVerificationCard(data.verification || {});

    if (streamEvent.statusCode >= 400 || !data || !Array.isArray(data.vendors)) {
      throw new Error(data?.error || 'Evaluation request failed.');
    }

    renderResults(data);
    recordSessionEvaluation(data);
    toast(`Evaluation complete — ${data.summary?.winner || 'winner'} recommended.`, 'success');
    switchView('results');
  } catch (error) {
    updateVerificationCard({
      mode: 'error',
      state: 'INFERENCE_FAILED',
      status: error.message,
      failureReason: error.message,
    });
    if (!el('processingDetails').children.length) appendLog('Failed / verification unavailable');
    el('resultsEmpty').hidden = false;
    el('resultsContent').hidden = true;
    el('resultsBadge').hidden = true;
    toast(error.message, 'error');
    switchView('verification');
  } finally {
    evaluating = false;
    button.disabled = false;
    button.textContent = 'Run evaluation';
  }
};

/* ================= Manual Scoring ================= */

const CRITERIA_CONFIG = [
  { id: 'technical_compliance', name: 'Technical Compliance', required: true },
  { id: 'relevant_experience', name: 'Relevant Experience', required: true },
  { id: 'delivery_timeline', name: 'Delivery Timeline', required: true },
  { id: 'eligibility_and_documentation', name: 'Eligibility & Documentation', required: true },
];

const renderManualScoring = () => {
  const container = el('manualVendorList');
  const payload = lastPayload || getFormState();
  const bids = payload.bids || [];

  if (bids.length === 0) {
    container.innerHTML = '<p class="empty-state">No bidders configured. Go to Evaluate tab to add bidders first.</p>';
    el('submitManualScores').disabled = true;
    return;
  }

  container.innerHTML = bids.map((bid, index) => `
    <div class="manual-vendor-card" data-vendor-index="${index}">
      <div class="manual-vendor-header">
        <h4>${escapeHtml(bid.vendorName || `Bidder ${index + 1}`)}</h4>
        <span class="chip chip-ghost">$${Number(bid.quotedPrice || 0).toLocaleString()}</span>
      </div>
      <div class="manual-score-fields">
        ${CRITERIA_CONFIG.map(c => `
          <div class="score-field">
            <label for="score_${index}_${c.id}">${escapeHtml(c.name)} ${c.required ? '<span class="required">*</span>' : ''}</label>
            <div class="score-input-group">
              <input type="number" id="score_${index}_${c.id}" min="0" max="100" step="1"
                class="score-input" data-vendor="${index}" data-criterion="${c.id}"
                placeholder="0-100" required="${c.required}">
              <span class="score-unit">/ 100</span>
            </div>
            <textarea class="evidence-input" id="evidence_${index}_${c.id}"
              placeholder="Justification and evidence..." rows="2"></textarea>
          </div>
        `).join('')}
      </div>
      <div class="manual-vendor-footer">
        <div class="field-group">
          <label>Strengths</label>
          <textarea id="strengths_${index}" rows="2" placeholder="Key strengths..."></textarea>
        </div>
        <div class="field-group">
          <label>Weaknesses</label>
          <textarea id="weaknesses_${index}" rows="2" placeholder="Areas for improvement..."></textarea>
        </div>
      </div>
    </div>
  `).join('');

  // Bind input events for real-time validation
  container.querySelectorAll('.score-input').forEach(input => {
    input.addEventListener('input', validateManualScores);
  });

  el('submitManualScores').disabled = false;
  updateManualScoreSummary();
};

const validateManualScores = () => {
  const container = el('manualVendorList');
  const inputs = container.querySelectorAll('.score-input');
  let isValid = true;

  inputs.forEach(input => {
    const value = parseInt(input.value);
    const required = input.required;
    const criterion = CRITERIA_CONFIG.find(c => c.id === input.dataset.criterion);

    if (required && (isNaN(value) || value < 0 || value > 100)) {
      input.classList.add('invalid');
      isValid = false;
    } else if (!isNaN(value) && (value < 0 || value > 100)) {
      input.classList.add('invalid');
      isValid = false;
    } else {
      input.classList.remove('invalid');
    }
  });

  el('submitManualScores').disabled = !isValid;
  updateManualScoreSummary();
  return isValid;
};

const updateManualScoreSummary = () => {
  const container = el('manualVendorList');
  const payload = lastPayload || getFormState();
  const bids = payload.bids || [];
  const summary = el('manualScoreSummary');

  if (bids.length === 0) {
    summary.innerHTML = '<p class="empty-state">No bidders to score.</p>';
    return;
  }

  const weights = defaultWeights;
  const vendorScores = bids.map((bid, index) => {
    let total = 0;
    let hasMissing = false;

    CRITERIA_CONFIG.forEach(c => {
      const input = el(`score_${index}_${c.id}`);
      const value = parseInt(input?.value || 0);
      if (c.required && (isNaN(value) || input?.value === '')) {
        hasMissing = true;
      } else {
        total += (value || 0) * (weights[c.id] || 0);
      }
    });

    return {
      name: bid.vendorName || `Bidder ${index + 1}`,
      score: hasMissing ? null : Math.round(total * 100) / 100,
      missing: hasMissing
    };
  });

  summary.innerHTML = `
    <div class="score-summary-list">
      ${vendorScores.map(v => `
        <div class="score-summary-item">
          <span>${escapeHtml(v.name)}</span>
          <strong class="${v.missing ? 'text-muted' : ''}">${v.missing ? '—' : v.score}</strong>
        </div>
      `).join('')}
    </div>
    <p class="fine-print">Scores are calculated using default weights. Price score is auto-calculated.</p>
  `;
};

const getManualScoresPayload = () => {
  const payload = lastPayload || getFormState();
  const bids = payload.bids || [];

  bids.forEach((bid, index) => {
    bid.scores = {};
    bid.evidence = {};
    bid.strengths = [];
    bid.weaknesses = [];
    bid.missingInformation = [];
    bid.riskIndicators = [];

    CRITERIA_CONFIG.forEach(c => {
      const scoreInput = el(`score_${index}_${c.id}`);
      const evidenceInput = el(`evidence_${index}_${c.id}`);
      bid.scores[c.id] = parseInt(scoreInput?.value || 0);
      bid.evidence[c.id] = evidenceInput?.value || '';
    });

    const strengthsInput = el(`strengths_${index}`);
    const weaknessesInput = el(`weaknesses_${index}`);
    if (strengthsInput?.value) {
      bid.strengths = strengthsInput.value.split('\n').filter(s => s.trim());
    }
    if (weaknessesInput?.value) {
      bid.weaknesses = weaknessesInput.value.split('\n').filter(s => s.trim());
    }
  });

  payload.evaluationMode = 'manual';
  return payload;
};

const handleManualScoreSubmit = async () => {
  if (!validateManualScores()) {
    toast('Please fix invalid scores before submitting.', 'error');
    return;
  }

  const button = el('submitManualScores');
  button.disabled = true;
  button.textContent = 'Submitting…';

  try {
    const payload = getManualScoresPayload();
    lastPayload = payload;

    const res = await fetch('/api/evaluate/manual', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Submission failed (HTTP ${res.status})`);
    }

    const data = await res.json();
    renderResults(data);
    recordSessionEvaluation(data);
    toast('Manual evaluation complete — rankings calculated.', 'success');
    switchView('results');
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = 'Submit & Rank';
  }
};

/* ================= Init ================= */

window.addEventListener('DOMContentLoaded', () => {
  updateVerificationCard({ state: 'WAITING', status: 'Waiting for evaluation.' });
  loadDemo();
  loadHealth();
  renderSessionActivity();
  renderHistory();

  document.querySelectorAll('.nav-item').forEach((item) => {
    item.addEventListener('click', () => switchView(item.dataset.view));
  });
  el('menuBtn').addEventListener('click', () => {
    el('sidebar').classList.contains('open') ? closeSidebar() : openSidebar();
  });
  el('sidebarScrim').addEventListener('click', closeSidebar);

  el('ctaEvaluate').addEventListener('click', () => switchView('evaluate'));
  el('ctaEvaluate2').addEventListener('click', () => switchView('evaluate'));
  el('ctaEvaluate3').addEventListener('click', () => switchView('evaluate'));
  el('ctaDemo').addEventListener('click', () => { loadDemo(); switchView('evaluate'); });
  el('ctaVerify').addEventListener('click', () => switchView('verification'));

  el('loadDemo').addEventListener('click', loadDemo);
  el('addVendor').addEventListener('click', () => {
    const container = el('vendorList');
    if (container.children.length >= LIMITS.maxVendors) {
      showFormErrors([`At most ${LIMITS.maxVendors} bidders are allowed.`]);
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.innerHTML = createVendorCard('', '', '');
    const newCard = wrapper.firstElementChild;
    container.appendChild(newCard);
    bindVendorCard(newCard);
    updateReadiness();
    newCard.querySelector('.vendor-name').focus();
  });

  el('evaluateButton').addEventListener('click', handleEvaluate);
  el('downloadReport').addEventListener('click', downloadReport);
  el('submitManualScores').addEventListener('click', handleManualScoreSubmit);

  el('historySearch').addEventListener('input', renderHistory);
  el('historyFilter').addEventListener('change', renderHistory);
  el('historyClear').addEventListener('click', () => {
    sessionEvaluations.length = 0;
    renderSessionActivity();
    renderHistory();
    toast('Session history cleared.', 'info');
  });
});
