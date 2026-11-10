const defaultWeights = {
  technical_compliance: 0.3,
  price_competitiveness: 0.25,
  relevant_experience: 0.2,
  delivery_timeline: 0.15,
  eligibility_and_documentation: 0.1,
};

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}[character]));

const createVendorCard = (name = '', price = '', proposal = '', files = []) => `
  <div class="vendor-card">
    <div class="vendor-card-header">
      <input class="vendor-name" value="${escapeHtml(name)}" placeholder="Vendor name" />
      <button class="ghost remove-vendor" type="button">Remove</button>
    </div>
    <div class="two-col">
      <div class="field-group">
        <label>Quoted price</label>
        <input class="vendor-price" type="number" value="${escapeHtml(price)}" placeholder="250000" />
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

const getFormState = () => {
  const cards = Array.from(document.querySelectorAll('.vendor-card'));
  return {
    tender: {
      title: document.getElementById('tenderTitle').value,
      description: document.getElementById('tenderDescription').value,
      maximumBudget: Number(document.getElementById('maximumBudget').value || 0),
      deadline: document.getElementById('submissionDeadline').value,
      eligibilityRequirements: document.getElementById('eligibilityRequirements').value,
      technicalRequirements: document.getElementById('technicalRequirements').value,
      evaluationCriteria: document.getElementById('evaluationCriteria').value,
      weights: defaultWeights,
    },
    bids: cards.map((card) => ({
      vendorName: card.querySelector('.vendor-name').value || 'Unnamed vendor',
      quotedPrice: Number(card.querySelector('.vendor-price').value || 0),
      proposalText: card.querySelector('.vendor-proposal').value || '',
    })),
  };
};

const renderVendorCards = (vendors) => {
  const container = document.getElementById('vendorList');
  container.innerHTML = vendors.map((vendor) => createVendorCard(vendor.name, vendor.price, vendor.proposal, vendor.files || [])).join('');

  container.querySelectorAll('.remove-vendor').forEach((button) => {
    button.addEventListener('click', () => {
      const card = button.closest('.vendor-card');
      if (container.children.length > 1) {
        card.remove();
      }
    });
  });

  container.querySelectorAll('.vendor-files').forEach((input) => {
    input.addEventListener('change', (event) => {
      const names = Array.from(event.target.files || []).map((file) => file.name);
      const fileLabel = input.parentElement.querySelector('.uploaded-files');
      fileLabel.textContent = names.length ? names.join(', ') : 'No files selected; text summary will be used for evaluation.';
    });
  });
};

const loadDemo = () => {
  document.getElementById('tenderTitle').value = 'Modern Secure Government Data Platform';
  document.getElementById('tenderDescription').value = 'Procurement for a secure government data platform with migration, governance, and modernization requirements.';
  document.getElementById('maximumBudget').value = '1000000';
  document.getElementById('submissionDeadline').value = '2026-12-31';
  document.getElementById('eligibilityRequirements').value = 'Vendor must have three comparable public sector modernizations and valid security certifications.';
  document.getElementById('technicalRequirements').value = 'Need secure integration, RBAC, encrypted data transport, monitoring, and phased rollout.';
  document.getElementById('evaluationCriteria').value = 'Technical compliance, price competitiveness, relevant experience, delivery timeline, eligibility and documentation.';

  renderVendorCards([
    { name: 'Northstar Systems', price: '820000', proposal: 'Secure migration architecture with strong governance and phased rollout. Includes data retention and system monitoring.' },
    { name: 'Meridian Consulting', price: '740000', proposal: 'Cost-effective delivery with experience in public sector change programs and analytics modernization.' },
    { name: 'Helio DataWorks', price: '910000', proposal: 'Strong technical depth with governance and analytics integration; slightly higher cost and longer timeline.' },
  ]);
};

const updateVerificationCard = (verification = {}) => {
  const badge = document.getElementById('verificationBadge');
  const list = document.getElementById('verificationDetails');
  const { attestationVerified, gatewayVerified, modelVerified, responseSignatureKind, status } = verification;

  const verified = verification.mode === 'live'
    && attestationVerified === true
    && modelVerified === true
    && responseSignatureKind === 'provider_tee';
  badge.textContent = verified
    ? 'Model TEE verified'
    : responseSignatureKind === 'gateway'
      ? 'Gateway only'
      : 'Verification unavailable';
  badge.className = `badge ${verified ? 'success' : 'warning'}`;

  const rows = [
    `Gateway attestation: ${gatewayVerified === true ? 'verified by SDK' : 'not reported'}`,
    `Model TEE attestation: ${verified ? 'verified' : 'not proven'}`,
    `Response signature: ${responseSignatureKind || 'unavailable'}`,
    `Status: ${status || 'Awaiting run'}`,
  ];
  list.replaceChildren(...rows.map((row) => {
    const item = document.createElement('li');
    item.textContent = row;
    return item;
  }));
};

const renderProcessing = (processing = [], documents = []) => {
  const list = document.getElementById('processingDetails');
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
  const list = document.getElementById('processingDetails');
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
  const tbody = document.getElementById('rankingsBody');
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
  const details = document.getElementById('vendorDetails');
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

  document.getElementById('winnerName').textContent = winner;
  document.getElementById('averageScore').textContent = typeof average === 'number' ? `${average} / 100` : average;
  document.getElementById('modelName').textContent = model;
};

const handleEvaluate = async () => {
  const button = document.getElementById('evaluateButton');
  button.disabled = true;
  button.textContent = 'Evaluating...';

  try {
    const payload = getFormState();
    const cards = Array.from(document.querySelectorAll('.vendor-card'));
    const formData = new FormData();
    formData.append('payload', JSON.stringify(payload));
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
      const data = await res.json();
      renderProcessing(data.processing || [{ status: 'Failed / verification unavailable' }], data.documents || []);
      updateVerificationCard(data.verification || {});
      throw new Error(data.error || 'Evaluation request failed.');
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
  } catch (error) {
    updateVerificationCard({ mode: 'error', status: error.message, responseSignatureKind: 'unavailable', attestationVerified: false, gatewayVerified: false, modelVerified: false });
    if (!document.getElementById('processingDetails').children.length) {
      setCurrentProcessing('Failed / verification unavailable');
    }
    document.getElementById('winnerName').textContent = 'Evaluation failed';
    document.getElementById('averageScore').textContent = '—';
    document.getElementById('modelName').textContent = '—';
    const failure = document.createElement('p');
    failure.className = 'responsive-note';
    failure.textContent = error.message;
    document.getElementById('vendorDetails').replaceChildren(failure);
  } finally {
    button.disabled = false;
    button.textContent = 'Evaluate bids';
  }
};

window.addEventListener('DOMContentLoaded', () => {
  loadDemo();
  document.getElementById('loadDemo').addEventListener('click', loadDemo);
  document.getElementById('addVendor').addEventListener('click', () => {
    const container = document.getElementById('vendorList');
    const card = document.createElement('div');
    card.innerHTML = createVendorCard('', '', '', []);
    const newCard = card.firstElementChild;
    container.appendChild(newCard);

    newCard.querySelector('.remove-vendor').addEventListener('click', () => {
      if (container.children.length > 1) {
        newCard.remove();
      }
    });

    newCard.querySelector('.vendor-files').addEventListener('change', (event) => {
      const names = Array.from(event.target.files || []).map((file) => file.name);
      const fileLabel = newCard.querySelector('.uploaded-files');
      fileLabel.textContent = names.length ? names.join(', ') : 'No files selected; text summary will be used for evaluation.';
    });
  });
  document.getElementById('evaluateButton').addEventListener('click', handleEvaluate);
});
