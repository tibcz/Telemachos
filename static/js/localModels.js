// static/js/localModels.js
//
// The curated local-model picker, as a normal modal.
//
// It began life as a standalone page at /models, which meant leaving the app,
// a document that did not scroll, and none of the window behaviour every other
// panel has. This is the same feature wired into the app the way Gallery,
// Theme and the rest are: a .modal in index.html, registered with the modal
// manager so it minimises to the dock, closes on Escape, and inherits the
// theme without a second copy of the CSS.

import Modals from './modalManager.js';

const MODAL_ID = 'local-models-modal';

let runtime = { available: false, running: false, tier: null };
let pollTimer = null;

const byId = (id) => document.getElementById(id);

// Below a gigabyte "0.0 GB" tells the reader nothing, so fall back to MB.
function humanSize(bytes) {
  return bytes >= 1073741824
    ? (bytes / 1073741824).toFixed(1) + ' GB'
    : Math.max(1, Math.round(bytes / 1048576)) + ' MB';
}

function renderMachine(data) {
  const host = byId('local-models-machine');
  if (!host) return;
  host.innerHTML = '<span class="lm-dot"></span><span>' +
    (data.memory_gb > 0
      ? 'This Mac has <strong>' + data.memory_gb + ' GB</strong> of memory'
      : 'Could not read this Mac’s memory, so every option is shown') +
    '</span>';
}

function renderTiers(data) {
  const grid = byId('local-models-grid');
  if (!grid) return;
  grid.innerHTML = '';

  let busy = false;

  data.tiers.forEach((tier) => {
    const recommended = tier.id === data.recommended;
    const working = tier.state === 'resolving' || tier.state === 'downloading';
    if (working) busy = true;

    const card = document.createElement('div');
    card.className = 'lm-card';
    if (recommended) card.dataset.recommended = '1';

    const info = document.createElement('div');
    info.innerHTML =
      '<div class="lm-head"><span class="lm-name">' + tier.label + '</span>' +
      (recommended ? '<span class="lm-tag rec">Recommended</span>' : '') +
      (tier.installed ? '<span class="lm-tag">Installed</span>' : '') +
      '</div>' +
      '<div class="lm-meta">' + tier.params + ' · ' + tier.quant +
      ' · about ' + tier.approx_size_gb + ' GB · ' + tier.hardware + '</div>' +
      '<div class="lm-desc">' + tier.summary + '</div>' +
      (tier.error ? '<div class="lm-err">' + tier.error + '</div>' : '');

    const actions = document.createElement('div');
    actions.className = 'lm-action';

    if (working) {
      const pct = tier.total ? Math.round(tier.downloaded / tier.total * 100) : 0;
      actions.innerHTML =
        '<div class="lm-progress"><div class="lm-bar" style="width:' + pct + '%"></div></div>' +
        '<div class="lm-status">' +
        (tier.total ? pct + '% · ' + humanSize(tier.downloaded) + ' of ' + humanSize(tier.total)
                    : 'Preparing…') + '</div>';
      const cancel = document.createElement('button');
      cancel.className = 'lm-btn';
      cancel.textContent = 'Cancel';
      cancel.onclick = () => call(tier.id, 'cancel', 'POST');
      actions.appendChild(cancel);

    } else if (tier.installed) {
      const serving = runtime.running && runtime.tier === tier.id;

      const status = document.createElement('div');
      status.className = 'lm-status';
      status.textContent = serving ? 'Running on this Mac' : humanSize(tier.installed_bytes) + ' on disk';

      if (runtime.available) {
        const use = document.createElement('button');
        use.className = 'lm-btn' + (serving ? '' : ' primary');
        use.textContent = serving ? 'Stop' : 'Use this model';
        use.onclick = serving
          ? () => fetch('/api/local-models/runtime/stop', { method: 'POST' }).then(refresh)
          : () => {
              use.disabled = true;
              use.textContent = 'Starting…';
              call(tier.id, 'serve', 'POST');
            };
        actions.appendChild(use);
      }

      const remove = document.createElement('button');
      remove.className = 'lm-btn danger';
      remove.textContent = 'Remove';
      remove.disabled = serving;
      remove.onclick = () => call(tier.id, '', 'DELETE');
      actions.append(status, remove);

    } else {
      const get = document.createElement('button');
      get.className = 'lm-btn' + (recommended ? ' primary' : '');
      get.textContent = 'Download';
      // One download at a time: they are gigabytes over one connection.
      get.disabled = busy;
      get.onclick = () => call(tier.id, 'download', 'POST');
      actions.appendChild(get);
    }

    card.append(info, actions);
    grid.appendChild(card);
  });

  // Poll only while something is moving, and only while the modal is open.
  clearInterval(pollTimer);
  pollTimer = null;
  if (busy && isOpen()) pollTimer = setInterval(refresh, 1000);
}

async function call(tier, path, method) {
  const url = '/api/local-models/' + encodeURIComponent(tier) + (path ? '/' + path : '');
  try { await fetch(url, { method }); } catch (_) {}
  refresh();
}

async function refresh() {
  if (!isOpen()) { clearInterval(pollTimer); pollTimer = null; return; }
  try {
    const [list, rt] = await Promise.all([
      fetch('/api/local-models'),
      fetch('/api/local-models/runtime/status'),
    ]);
    if (rt.ok) runtime = await rt.json();
    if (list.ok) {
      const data = await list.json();
      renderMachine(data);
      renderTiers(data);
    }
  } catch (_) {}
}

function isOpen() {
  const modal = byId(MODAL_ID);
  return !!modal && !modal.classList.contains('hidden');
}

function openModal() {
  const modal = byId(MODAL_ID);
  if (!modal) return;
  modal.classList.remove('hidden');
  refresh();
}

function closeModal() {
  const modal = byId(MODAL_ID);
  if (modal) modal.classList.add('hidden');
  clearInterval(pollTimer);
  pollTimer = null;
}

export function initLocalModels() {
  const modal = byId(MODAL_ID);
  if (!modal) return;

  const openBtn = byId('tool-models-btn');
  if (openBtn) {
    openBtn.addEventListener('click', () => {
      isOpen() ? closeModal() : openModal();
    });
  }

  const closeBtn = byId('close-local-models');
  if (closeBtn) closeBtn.addEventListener('click', closeModal);

  // Clicking the backdrop closes, same as the other modals.
  modal.addEventListener('click', (event) => {
    if (event.target === modal) closeModal();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isOpen()) closeModal();
  });

  try {
    Modals.register(MODAL_ID, {
      sidebarBtnId: 'tool-models-btn',
      closeFn: () => closeModal(),
      restoreFn: () => {},
      label: 'Models',
    });
  } catch (_) {
    // The dock is a nicety; the modal works without it.
  }
}

export default { initLocalModels };
