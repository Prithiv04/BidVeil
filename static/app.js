const defaultWeights = {
  technical_compliance: 0.3,
  price_competitiveness: 0.25,
  relevant_experience: 0.2,
  delivery_timeline: 0.15,
  eligibility_and_documentation: 0.1,
};

const LIMITS = {
  maxFileBytes: 10 * 1024 * 1024,
  maxFilesPerVendor: 10,
  maxVendors: 20,
  allowedExtensions: ['.pdf', '.txt'],
};

const sessionEvaluations = [];
let lastPayload = null;

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}[character]));

const el = (id) => document.getElementById(id);

/* ---------- Tabs ---------- */

const switchTab = (name) => {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.tab === name);
  });
  document.querySelectorAll('.tab-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id === `tab-${name}`);
  });
};

/* ---------- Vendor cards ---------- */

const createVendorCard = (name = '', price = '', proposal = '', files = []) => `
  <div class="vendor-card">
    <div class="vendor-card-header">
      <input class="vendor-name" value="${escapeHtml(name)}" placeholder="Vendor name" aria-label="Vendor name" />
      <button class="ghost remove-vendor" type="button">Remove</button>
    </div>
    <div class="two-col">
      <div class="field-group">
        <label>Quoted price</label>
        <input class="vendor-price" type="number" min="0" value="${escapeHtml(price)}" placeholder="250000" />
      </div>
      <div class="field-group">
        <label>Proposal summary</label>
        <textarea class="vendor-proposal" placeholder="Describe the bid summary...">${escapeHtml(proposal)}</textarea>
      </div>
    </div>
    <div class="field-group" style="margin-bottom: 0;">
      <label>Bid documents (optional)</label>
      <input class="vendor-files" type="file" multiple accept=".pdf,.txt" />
      <div class="responsive-note uploaded-files">${files.length ? files.map((file) => escapeHtml(file.name)).join(', ') : 'No files selected; text summary will be used for evaluation.'}</div>
    </div>
  </div>
`;

const bindVendorCard = (card) => {
  const remove = card.querySelector('.remove-vendor');
  if (remove) {
    remove.addEventListener('click', () => {
      const container = el('vendorList');
      if (container.children.length > 1) card.remove();
    });
  }
  const fileInput = card.querySelector('.vendor-files');
  if (fileInput) {
    fileInput.addEventListener('change', (event) => {
      const names = Array.from(event.target.files || []).map((file) => file.name);
      const fileLabel = card.querySelector('.uploaded-files');
      if (fileLabel) {
        fileLabel.textContent = names.length
          ? names.join(', ')
          : 'No files selected; text summary will be used for evaluation.';
      }
    });
  }
};

const renderVendorCards = (vendors) => {
  const container = el('vendorList');
  container.innerHTML = vendors.map((vendor) => createVendorCard(vendor.name, vendor.price, vendor.proposal, vendor.files || [])).join('');
  container.querySelectorAll('.vendor-card').forEach(bindVendorCard);
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
  };
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
    { name: 'Northstar Systems', price: '740000', proposal: 'Fictional Vendor A: lower quotation with moderate technical compliance, phased migration, and a 10-month delivery window. Sample file: samples/vendor-a-northstar.txt.' },
    { name: 'Meridian Consulting', price: '910000', proposal: 'Fictional Vendor B: higher quotation with excellent technical compliance, SOC 2 controls, comparable deployments, and a 7-month delivery window. Sample file: samples/vendor-b-meridian.txt.' },
    { name: 'Helio DataWorks', price: '820000', proposal: 'Fictional Vendor C: competitive quotation with incomplete documentation and missing security certification evidence. Sample file: samples/vendor-c-helio.txt.' },
  ]);
};

/* ---------- Client-side validation ---------- */

const validateForm = () => {
  const errors = [];
  const cards = Array.from(document.querySelectorAll('.vendor-card'));

  if (!cards.length) errors.push('At least one vendor is required.');
  if (cards.length > LIMITS.maxVendors) {
    errors.push(`At most ${LIMITS.maxVendors} vendors are allowed (found ${cards.length}).`);
  }

  cards.forEach((card, index) => {
    const label = card.querySelector('.vendor-name').value || `Vendor ${index + 1}`;
    const files = Array.from(card.querySelector('.vendor-files').files || []);
    if (files.length > LIMITS.maxFilesPerVendor) {
      errors.push(`${label}: at most ${LIMITS.maxFilesPerVendor} documents per vendor (found ${files.length}).`);
    }
    files.forEach((file) => {
      const ext = `.${(file.name.split('.').pop() || '').toLowerCase()}`;
      if (!LIMITS.allowedExtensions.includes(ext)) {
        errors.push(`${label}: "${file.name}" is not a supported type (PDF or TXT only).`);
      }
      if (file.size > LIMITS.maxFileBytes) {
        errors.push(`${label}: "${file.name}" exceeds the 10 MB per-document limit.`);
      }
      if (file.size === 0) {
        errors.push(`${label}: "${file.name}" is empty.`);
      }
    });
  });

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

/* ---------- Health / overview ---------- */

const verificationExplanationFor = (state, verification = {}) => {
  switch (state) {
    case 'MODEL_TEE_VERIFIED':
      return 'The official NEAR AI Inference SDK verified a provider_tee signature: the attestation report was nonce-bound, the model attestation was verified, and the response signature was verified against the retained request and response bytes. This is the strongest verification BIDVEIL reports.';
    case 'GATEWAY_ONLY':
      return 'A gateway signature was verified by the SDK, proving the response passed through the verified NEAR AI gateway. The signature kind was gateway, not provider_tee, so model-level TEE execution is NOT proven.';
    case 'SIGNATURE_VERIFIED':
    case 'ATTESTATION_VERIFIED':
      return 'Partial verification completed. See the details below for which checks passed and which are unavailable.';
    case 'VERIFICATION_FAILED':
      return 'A cryptographic verification check failed. The evaluation result is not trustworthy and should not be used.';
    case 'VERIFICATION_UNAVAILABLE':
      return 'Verification could not be performed — typically a provider-side issue such as billing (HTTP 402), connectivity, or timeout. No verification claims are made.';
    case 'ATTESTATION_PENDING':
      return 'Attestation verification is in progress.';
    default:
      return verification.status || 'Waiting for evaluation.';
  }
};

const updateVerificationCard = (verification = {}) => {
  const badge = el('verificationBadge');
  const list = el('verificationDetails');
  const explanation = el('verificationExplanation');
  const signatureKind = verification.responseSignatureKind || verification.signatureType || 'unavailable';
  const modelTee = verification.state === 'MODEL_TEE_VERIFIED'
    && verification.modelVerified === true
    && signatureKind === 'provider_tee';
  const state = verification.state
    || (modelTee ? 'MODEL_TEE_VERIFIED' : signatureKind === 'gateway' ? 'GATEWAY_ONLY' : 'WAITING');

  badge.textContent = state;
  badge.className = `badge ${verificationBadgeClass(state)}`;
  explanation.textContent = verificationExplanationFor(state, verification);

  const evidence = Array.isArray(verification.evidenceIds) && verification.evidenceIds.length
    ? verification.evidenceIds.join(', ')
    : 'none reported';
  const unavailable = Array.isArray(verification.unavailableChecks) && verification.unavailableChecks.length
    ? verification.unavailableChecks.join(' ')
    : 'none';
  const rows = [
    `Verification status: ${state}`,
    `Selected model: ${verification.model || 'pending'}`,
    `Model identity: ${verification.modelIdentity || 'not reported'}`,
    `Attestation: ${verification.attestationStatus || (verification.gatewayVerified ? 'gateway checked' : 'pending')}`,
    `Nonce verification: ${verification.nonceVerified === true ? 'matched' : 'not verified'}`,
    `Nonce: ${verification.nonce || 'not reported'}`,
    `Signature verification: ${verification.signatureVerified === true ? 'verified' : 'not verified'}`,
    `Signature type: ${signatureKind}`,
    `Hash verification: ${verification.hashVerified === true ? 'signed payload parsed' : 'not verified'}`,
    `Request hash: ${verification.requestHash || 'not reported'}`,
    `Response hash: ${verification.responseHash || 'not reported'}`,
    `Signed model id: ${verification.signedModelId || 'not reported'}`,
    `Completion id: ${verification.completionId || 'not reported'}`,
    `Provider type: ${verification.providerType || 'not reported'}`,
    `Verification timestamp: ${verification.verifiedAt || 'not reported'}`,
    `Evidence identifiers: ${evidence}`,
    `GPU evidence: ${verification.gpuEvidence || 'unavailable'}`,
    `Unavailable checks: ${unavailable}`,
    `Failure explanation: ${verification.failureReason || verification.status || 'none'}`,
  ];
  if (signatureKind === 'gateway' || state === 'GATEWAY_ONLY') {
    rows.push('Note: A gateway signature is not proof of model-level TEE execution.');
  }
  list.replaceChildren(...rows.map((row) => {
    const item = document.createElement('li');
    item.textContent = row;
    return item;
  }));

  const notice = el('verificationUnavailable');
  if (state === 'VERIFICATION_UNAVAILABLE' || state === 'VERIFICATION_FAILED') {
    notice.hidden = false;
    el('verificationUnavailableText').textContent = verification.failureReason || verification.status || '';
  } else {
    notice.hidden = true;
  }
};

const verificationBadgeClass = (state) => {
  if (state === 'MODEL_TEE_VERIFIED') return 'success';
  if (state === 'VERIFICATION_FAILED') return 'danger';
  if (state === 'VERIFICATION_UNAVAILABLE') return 'warning';
  if (state === 'GATEWAY_ONLY' || state === 'SIGNATURE_VERIFIED' || state === 'ATTESTATION_VERIFIED' || state === 'ATTESTATION_PENDING') {
    return 'warning';
  }
  return 'neutral';
};

/* ---------- Processing / results rendering ---------- */

const renderProcessing = (processing = [], documents = []) => {
  const list = el('processingDetails');
  const entries = [
    ...processing.map((item) => item.status),
    ...documents.map((document) => `${document.fileName}: ${document.status}${document.message ? ` — ${document.message}` : ''}`),
  ];
  list.replaceChildren(...entries.map((entry) => {
    const item = document.createElement('li');
    item.textContent = entry;
    return item;
  }));
};

const setCurrentProcessing = (state, append = false) => {
  const list = el('processingDetails');
  const item = document.createElement('li');
  item.textContent = state;
  if (append) {
    list.appendChild(item);
  } else {
    list.replaceChildren(item);
  }
};

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
      setCurrentProcessing(event.status, true);
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

const renderRankings = (vendors = []) => {
  const tbody = el('rankingsBody');
  if (!vendors.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">No vendors returned.</td></tr>';
    return;
  }
  tbody.innerHTML = vendors.map((vendor) => `
    <tr>
      <td>#${escapeHtml(vendor.rank)}</td>
      <td>${escapeHtml(vendor.vendorName)}</td>
      <td>${escapeHtml(vendor.weightedScore)}</td>
      <td>$${escapeHtml(Number(vendor.quotedPrice || 0).toLocaleString())}</td>
      <td>${escapeHtml(vendor.riskIndicators?.[0] || 'Low')}</td>
    </tr>
  `).join('');
};

const renderVendorDetails = (vendors = []) => {
  const details = el('vendorDetails');
  if (!vendors.length) {
    details.innerHTML = '<p class="empty-state">No vendor evidence returned.</p>';
    return;
  }
  details.innerHTML = vendors.map((vendor) => `
    <div class="evidence-card">
      <h3>${escapeHtml(vendor.rank)}. ${escapeHtml(vendor.vendorName)}</h3>
      <p class="responsive-note">${escapeHtml(vendor.evidenceSummary || 'Evidence summary not available.')}</p>
      <div class="metric-grid">
        <div class="metric"><label>Technical</label><strong>${escapeHtml(vendor.technicalComplianceScore)}</strong></div>
        <div class="metric"><label>Price</label><strong>${escapeHtml(vendor.priceCompetitivenessScore)}</strong></div>
        <div class="metric"><label>Experience</label><strong>${escapeHtml(vendor.relevantExperienceScore)}</strong></div>
        <div class="metric"><label>Delivery</label><strong>${escapeHtml(vendor.deliveryTimelineScore)}</strong></div>
        <div class="metric"><label>Eligibility</label><strong>${escapeHtml(vendor.eligibilityDocumentationScore)}</strong></div>
        <div class="metric"><label>Weighted score</label><strong>${escapeHtml(vendor.weightedScore)}</strong></div>
      </div>
      <p><strong>Strengths:</strong> ${escapeHtml((vendor.strengths || []).join(', ') || 'Not specified')}</p>
      <p><strong>Weaknesses:</strong> ${escapeHtml((vendor.weaknesses || []).join(', ') || 'Not specified')}</p>
      <p><strong>Risk indicators:</strong> ${escapeHtml((vendor.riskIndicators || []).join(', ') || 'No notable risks')}</p>
      <p><strong>Missing information:</strong> ${escapeHtml((vendor.missingInformation || []).join(', ') || 'None identified')}</p>
    </div>
  `).join('');
};

const updateSummary = (response) => {
  const winner = response?.summary?.winner || '—';
  const average = response?.summary?.averageScore ?? '—';
  const model = response?.verification?.model || '—';

  el('winnerName').textContent = winner;
  el('averageScore').textContent = typeof average === 'number' ? `${average} / 100` : average;
  el('modelName').textContent = model;
};

/* ---------- Session history & overview ---------- */

const recordSessionEvaluation = (data) => {
  const verification = data.verification || {};
  const state = verification.state || 'UNKNOWN';
  const winner = data.summary?.winner || '—';
  const average = data.summary?.averageScore;
  const tenderTitle = lastPayload?.tender?.title || 'Untitled tender';
  const entry = {
    timestamp: new Date(),
    tenderTitle,
    winner,
    state,
    averageScore: typeof average === 'number' ? average : null,
    vendorCount: Array.isArray(data.vendors) ? data.vendors.length : 0,
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
    container.innerHTML = '<p class="empty-state">No evaluations have been run in this session.</p>';
    return;
  }
  container.innerHTML = sessionEvaluations.slice(0, 5).map((entry) => `
    <div class="activity-item">
      <span class="activity-title">${escapeHtml(entry.tenderTitle)}</span>
      <span class="activity-meta">${escapeHtml(entry.state)} · ${escapeHtml(entry.winner)} · ${entry.timestamp.toLocaleTimeString()}</span>
    </div>
  `).join('');
};

const renderHistory = () => {
  const container = el('historyList');
  if (!sessionEvaluations.length) {
    container.innerHTML = '<p class="empty-state">No evaluations recorded yet. Completed evaluations will appear here for this session only.</p>';
    return;
  }
  container.innerHTML = sessionEvaluations.map((entry) => `
    <div class="activity-item">
      <span class="activity-title">${escapeHtml(entry.tenderTitle)}</span>
      <span class="activity-meta">${escapeHtml(entry.timestamp.toLocaleString())} · ${escapeHtml(entry.state)} · winner: ${escapeHtml(entry.winner)}${entry.averageScore !== null ? ` · avg ${entry.averageScore}` : ''} · ${entry.vendorCount} vendors</span>
    </div>
  `).join('');
};

const loadHealth = async () => {
  const pill = el('serviceStatus');
  const pillText = el('serviceStatusText');
  try {
    const res = await fetch('/api/health');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const health = await res.json();

    const configured = health.apiConfigured === true;
    const teeLive = health.teeMode === 'live';

    el('ovApiStatus').textContent = health.status === 'ok' ? 'Operational' : 'Degraded';
    el('ovTeeMode').textContent = teeLive ? 'Live (key configured)' : 'Unconfigured';
    el('ovModel').textContent = health.model || '—';
    el('ovStates').textContent = Array.isArray(health.verificationStates) ? String(health.verificationStates.length) : '—';

    if (configured && teeLive) {
      pill.className = 'status-pill status-ok';
      pillText.textContent = 'NEAR AI Cloud connected';
    } else if (configured) {
      pill.className = 'status-pill status-degraded';
      pillText.textContent = 'API key configured — verification limited';
    } else {
      pill.className = 'status-pill status-degraded';
      pillText.textContent = 'NEARAI_API_KEY not configured';
    }

    el('ovHealthNote').textContent = configured
      ? `Model: ${health.model}. TEE mode: ${health.teeMode}. ${Array.isArray(health.verificationStates) ? `${health.verificationStates.length} verification states supported.` : ''}`
      : 'NEARAI_API_KEY is not set. Evaluations will fail with VERIFICATION_UNAVAILABLE until a key is configured.';

    el('ovVerificationNote').textContent = teeLive
      ? 'Live verification is configured. Whether model-level TEE is proven depends on the signature kind returned by the provider for each evaluation.'
      : 'Live NEAR AI Cloud verification is not currently configured. The UI will report VERIFICATION_UNAVAILABLE honestly rather than simulating verification.';
  } catch (error) {
    pill.className = 'status-pill status-error';
    pillText.textContent = 'Service unreachable';
    el('ovApiStatus').textContent = 'Unreachable';
    el('ovTeeMode').textContent = 'Unknown';
    el('ovModel').textContent = '—';
    el('ovStates').textContent = '—';
    el('ovHealthNote').textContent = `Could not reach /api/health: ${error.message}`;
    el('ovVerificationNote').textContent = 'Service status could not be determined.';
  }
};

/* ---------- Evaluation ---------- */

const handleEvaluate = async () => {
  const button = el('evaluateButton');
  const retryButton = el('retryButton');
  const errors = validateForm();
  showFormErrors(errors);
  if (errors.length) return;

  button.disabled = true;
  button.textContent = 'Evaluating...';
  retryButton.hidden = true;
  el('verificationUnavailable').hidden = true;

  try {
    lastPayload = getFormState();
    const cards = Array.from(document.querySelectorAll('.vendor-card'));
    const formData = new FormData();
    formData.append('payload', JSON.stringify(lastPayload));
    let hasUploads = false;
    cards.forEach((card, index) => {
      Array.from(card.querySelector('.vendor-files').files || []).forEach((file) => {
        formData.append(`bid_${index}`, file, file.name);
        hasUploads = true;
      });
    });
    setCurrentProcessing(hasUploads ? 'Uploading documents' : 'Preparing confidential analysis');
    const res = await fetch('/api/evaluate/stream', {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      renderProcessing(data.processing || [{ status: 'Failed / verification unavailable' }], data.documents || []);
      updateVerificationCard(data.verification || {});
      throw new Error(data.error || `Evaluation request failed (HTTP ${res.status}).`);
    }
    const streamEvent = await readEvaluationStream(res);
    const data = streamEvent.result;
    if (streamEvent.statusCode >= 400) {
      renderProcessing(data.processing || [], data.documents || []);
      updateVerificationCard(data.verification || {});
      throw new Error(data.error || 'Evaluation request failed.');
    }
    if (!data || !Array.isArray(data.vendors)) {
      throw new Error('Evaluation response was malformed.');
    }

    updateVerificationCard(data.verification || {});
    renderProcessing(data.processing || [], data.documents || []);
    renderRankings(data.vendors);
    renderVendorDetails(data.vendors);
    updateSummary(data);
    recordSessionEvaluation(data);
    retryButton.hidden = false;
    switchTab('verification');
  } catch (error) {
    updateVerificationCard({
      mode: 'error',
      state: 'VERIFICATION_FAILED',
      status: error.message,
      failureReason: error.message,
      responseSignatureKind: 'unavailable',
      attestationVerified: false,
      gatewayVerified: false,
      modelVerified: false,
    });
    if (!el('processingDetails').children.length) {
      setCurrentProcessing('Failed / verification unavailable');
    }
    el('winnerName').textContent = 'Evaluation failed';
    el('averageScore').textContent = '—';
    el('modelName').textContent = '—';
    el('vendorDetails').innerHTML = '';
    const failure = document.createElement('p');
    failure.className = 'empty-state';
    failure.textContent = error.message;
    el('vendorDetails').appendChild(failure);
    retryButton.hidden = false;
    switchTab('verification');
  } finally {
    button.disabled = false;
    button.textContent = 'Evaluate bids';
  }
};

/* ---------- Init ---------- */

window.addEventListener('DOMContentLoaded', () => {
  updateVerificationCard({ state: 'WAITING', status: 'Waiting for evaluation.' });
  loadDemo();
  loadHealth();
  renderSessionActivity();
  renderHistory();

  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  el('loadDemo').addEventListener('click', loadDemo);
  el('addVendor').addEventListener('click', () => {
    const container = el('vendorList');
    if (container.children.length >= LIMITS.maxVendors) {
      showFormErrors([`At most ${LIMITS.maxVendors} vendors are allowed.`]);
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.innerHTML = createVendorCard('', '', '', []);
    const newCard = wrapper.firstElementChild;
    container.appendChild(newCard);
    bindVendorCard(newCard);
  });
  el('evaluateButton').addEventListener('click', handleEvaluate);
  el('retryButton').addEventListener('click', handleEvaluate);
});
