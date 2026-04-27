/* azaload dashboard — vanilla JS SPA */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  filter: 'all',
  search: '',
  signals: [],     // mix BUY/SELL/HOLD signals
  pumps: {},       // key = "type:symbol" -> pump signal
  alerts: [],      // ordered most-recent first
  watchlist: [],
  status: null,
  config: null,
};

// --------------------------------------------------------------------------
// API helpers
// --------------------------------------------------------------------------

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

// --------------------------------------------------------------------------
// Rendering
// --------------------------------------------------------------------------

function fmt(num, digits = 2) {
  if (num === null || num === undefined || Number.isNaN(num)) return '—';
  if (Math.abs(num) >= 1000) return num.toLocaleString('en-US', { maximumFractionDigits: digits });
  return Number(num).toFixed(digits);
}

function fmtVol(num) {
  if (!num || Number.isNaN(num)) return '—';
  if (num >= 1e9) return (num / 1e9).toFixed(1) + 'B';
  if (num >= 1e6) return (num / 1e6).toFixed(1) + 'M';
  if (num >= 1e3) return (num / 1e3).toFixed(1) + 'K';
  return String(Math.round(num));
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function effectiveAction(sig, pump) {
  if (pump && pump.direction && pump.direction !== 'NONE') return pump.direction;
  return sig.action;
}

function renderHeaderStats() {
  $('#stat-watchlist').textContent = state.watchlist.length;
  if (state.status) {
    $('#stat-cycles').textContent = state.status.scan_count ?? 0;
  }
  $('#stat-alerts').textContent = state.alerts.length;
  const dot = $('#status-dot');
  dot.className = 'stat status-dot ' + (state.status?.is_scanning ? 'scan' : 'live');
  dot.title = state.status?.is_scanning ? 'Scan en cours' : 'Inactif';
}

function renderWatchlist() {
  const root = $('#watchlist');
  if (!state.watchlist.length) {
    root.innerHTML = '<div class="empty-hint" style="padding:12px">Aucun actif. Cliquez sur <b>+ Catalogue</b>.</div>';
    return;
  }
  root.innerHTML = state.watchlist.map(a => `
    <div class="watchlist-item" data-key="${a.asset_type}:${a.symbol}">
      <div>
        <div>${a.symbol}</div>
        <div class="meta">${a.name} · ${a.asset_type} · ${a.interval}</div>
      </div>
      <button class="remove" title="Retirer" data-rm="${a.asset_type}:${a.symbol}">✕</button>
    </div>
  `).join('');

  $$('.watchlist-item .remove').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const [type, symbol] = btn.dataset.rm.split(':');
      const r = await api(`/api/watchlist/${type}/${encodeURIComponent(symbol)}`, { method: 'DELETE' });
      state.watchlist = r.watchlist;
      renderWatchlist();
      renderGrid();
    });
  });
}

function signalCardHtml(sig, pump) {
  const action = effectiveAction(sig, pump);
  const isPumpDump = action === 'LONG' || action === 'SHORT';
  const conf = isPumpDump ? pump.probability : sig.confidence;
  const entry = isPumpDump ? pump.entry_price : sig.entry_price;
  const sl = isPumpDump ? pump.stop_loss : sig.stop_loss;
  const tp = isPumpDump ? pump.take_profit : sig.take_profit;

  return `
    <div class="card action-${action} ${pump && pump.direction !== 'NONE' ? 'pump-active' : ''}"
         data-key="${sig.asset_type}:${sig.symbol}">
      <div class="row1">
        <div>
          <span class="symbol">${sig.symbol}</span>
          <span class="name">${sig.name}</span>
        </div>
        <span class="badge action-${action}">${action}</span>
      </div>
      <div class="row2">
        ${sig.asset_type} · ${sig.interval} · ${fmtTime(sig.timestamp)}
      </div>
      <div class="conf-bar"><div class="conf-bar-fill" style="width:${Math.max(0, Math.min(100, conf))}%"></div></div>
      <div class="row2">${isPumpDump ? 'Probabilité' : 'Confiance'} : <b>${fmt(conf, 1)}%</b></div>
      <div class="levels">
        <div><label>Entry</label><b>${fmt(entry, 4)}</b></div>
        <div><label>SL</label><b>${fmt(sl, 4)}</b></div>
        <div><label>TP</label><b>${fmt(tp, 4)}</b></div>
      </div>
    </div>
  `;
}

function applyFilter(sig, pump) {
  if (state.search) {
    const q = state.search.toLowerCase();
    if (!`${sig.symbol} ${sig.name}`.toLowerCase().includes(q)) return false;
  }
  if (state.filter === 'all') return true;
  const action = effectiveAction(sig, pump);
  return action === state.filter;
}

function renderGrid() {
  const root = $('#signals-grid');
  if (!state.signals.length && !state.watchlist.length) {
    root.innerHTML = `<div class="empty-hint">
      Watchlist vide. Cliquez sur <b>+ Catalogue</b> pour ajouter des actifs.
    </div>`;
    return;
  }
  if (!state.signals.length) {
    root.innerHTML = `<div class="empty-hint">
      Premier cycle en cours… cliquez sur <b>Scan now</b> pour forcer.
    </div>`;
    return;
  }

  // Trier: pump/dump en tête, puis BUY/SELL avec confiance haute, puis HOLD
  const items = state.signals
    .map(sig => ({ sig, pump: state.pumps[`${sig.asset_type}:${sig.symbol}`] }))
    .filter(({ sig, pump }) => applyFilter(sig, pump))
    .sort((a, b) => {
      const aPump = a.pump && a.pump.direction !== 'NONE';
      const bPump = b.pump && b.pump.direction !== 'NONE';
      if (aPump !== bPump) return aPump ? -1 : 1;
      const aHold = a.sig.action === 'HOLD';
      const bHold = b.sig.action === 'HOLD';
      if (aHold !== bHold) return aHold ? 1 : -1;
      return (b.sig.confidence || 0) - (a.sig.confidence || 0);
    });

  if (!items.length) {
    root.innerHTML = `<div class="empty-hint">Aucun actif ne correspond au filtre.</div>`;
    return;
  }

  root.innerHTML = items.map(({ sig, pump }) => signalCardHtml(sig, pump)).join('');
  $$('.card', root).forEach(card => {
    card.addEventListener('click', () => openDetail(card.dataset.key));
  });
}

function alertHtml(a) {
  const cls = `alert kind-${a.kind} action-${a.action || ''} dir-${a.direction || ''}`;
  const head = a.kind === 'pump_dump'
    ? `<b>⚡ ${a.direction}</b> · ${a.symbol} · ${fmt(a.probability, 1)}%`
    : `<b>${a.action}</b> · ${a.symbol} · ${fmt(a.confidence, 1)}%`;
  const reasons = (a.reasons || []).slice(0, 4).map(r => `<li>${r}</li>`).join('');
  return `
    <div class="${cls}">
      <div class="head">${head}<span class="when">${fmtTime(a.timestamp || a.added_at)}</span></div>
      <div>Entry ${fmt(a.entry_price, 4)} · SL ${fmt(a.stop_loss, 4)} · TP ${fmt(a.take_profit, 4)} · R/R ${fmt(a.risk_reward, 2)}</div>
      ${reasons ? `<ul>${reasons}</ul>` : ''}
    </div>
  `;
}

function renderAlerts() {
  const root = $('#alerts-feed');
  if (!state.alerts.length) {
    root.innerHTML = `<div class="empty-hint">En attente d'alertes…</div>`;
    return;
  }
  root.innerHTML = state.alerts.slice(0, 30).map(alertHtml).join('');
}

// --------------------------------------------------------------------------
// Detail dialog
// --------------------------------------------------------------------------

function openDetail(key) {
  const sig = state.signals.find(s => `${s.asset_type}:${s.symbol}` === key);
  if (!sig) return;
  const pump = state.pumps[key];
  $('#detail-title').textContent = `${sig.symbol} — ${sig.name}`;

  const breakdown = sig.strategy_breakdown || {};
  const breakdownRows = Object.entries(breakdown)
    .map(([k, v]) => `<tr><td>${k}</td><td>${v >= 0 ? '+' : ''}${fmt(v, 3)}</td></tr>`)
    .join('');

  const reasons = (sig.reasons || []).map(r => `<li>${r}</li>`).join('');

  let pumpBlock = '';
  if (pump) {
    const triggers = pump.triggers || {};
    const triggerRows = Object.entries(triggers)
      .filter(([, v]) => typeof v === 'boolean')
      .map(([k, v]) => `<tr><td>${k}</td><td>${v ? '✓' : '·'}</td></tr>`)
      .join('');
    const pumpReasons = (pump.reasons || []).map(r => `<li>${r}</li>`).join('');
    pumpBlock = `
      <h3>⚡ Pump/Dump · ${pump.direction} · ${fmt(pump.probability, 1)}%</h3>
      ${pumpReasons ? `<ul>${pumpReasons}</ul>` : ''}
      ${triggerRows ? `<table>${triggerRows}</table>` : ''}
    `;
  }

  $('#detail-body').innerHTML = `
    <div><b>${sig.action}</b> · confiance ${fmt(sig.confidence, 1)}% · ${sig.asset_type} · ${sig.interval}</div>
    <div class="levels">
      <div><label>Entry</label><b>${fmt(sig.entry_price, 6)}</b></div>
      <div><label>Stop Loss</label><b>${fmt(sig.stop_loss, 6)}</b></div>
      <div><label>Take Profit</label><b>${fmt(sig.take_profit, 6)}</b></div>
    </div>
    <div>R/R : ${fmt(sig.risk_reward, 2)}</div>

    <h3>Stratégies</h3>
    <table>${breakdownRows}</table>

    <h3>Raisons</h3>
    <ul>${reasons}</ul>

    ${pumpBlock}
  `;
  $('#detail-dialog').showModal();
}

// --------------------------------------------------------------------------
// Catalogue
// --------------------------------------------------------------------------

async function loadCatalogStats() {
  const stats = await api('/api/catalog/stats');
  $('#catalog-stats').innerHTML = Object.entries(stats)
    .map(([k, v]) => `<span><b>${v}</b> ${k.replace('_', ' ')}</span>`)
    .join('');
}

async function loadCatalog() {
  const q = $('#catalog-search').value.trim();
  const type = $('#catalog-type').value;
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (type) params.set('type', type);
  params.set('limit', '300');
  const r = await api(`/api/catalog?${params}`);

  const watchKeys = new Set(state.watchlist.map(a => `${a.asset_type}:${a.symbol}`));
  $('#catalog-list').innerHTML = r.entries.map(e => {
    const inList = watchKeys.has(`${e.asset_type}:${e.symbol}`);
    return `
      <div class="catalog-row">
        <div><span class="sym">${e.symbol}</span></div>
        <div>
          <div class="name">${e.name}</div>
          <div class="meta">${e.asset_type} · ${e.interval} ${e.tags?.length ? '· ' + e.tags.join(', ') : ''}</div>
        </div>
        <div class="vol">${e.quote_volume_24h ? fmtVol(e.quote_volume_24h) + ' USDT/24h' : ''}</div>
        <button class="add" data-add='${JSON.stringify(e).replace(/'/g, '&#39;')}' ${inList ? 'disabled' : ''}>
          ${inList ? '✓ ajouté' : '+ ajouter'}
        </button>
      </div>
    `;
  }).join('') || '<div class="empty-hint">Aucun résultat</div>';

  $$('.catalog-row .add').forEach(btn => {
    btn.addEventListener('click', async () => {
      const e = JSON.parse(btn.dataset.add);
      btn.disabled = true;
      btn.textContent = '...';
      try {
        const r = await api('/api/watchlist', {
          method: 'POST',
          body: JSON.stringify(e),
        });
        state.watchlist = r.watchlist;
        renderWatchlist();
        btn.textContent = '✓ ajouté';
      } catch (err) {
        btn.disabled = false;
        btn.textContent = '+ ajouter';
        alert('Erreur: ' + err.message);
      }
    });
  });
}

// --------------------------------------------------------------------------
// Config
// --------------------------------------------------------------------------

function setNested(form, dottedName, value) {
  const input = form.elements[dottedName];
  if (input != null) input.value = value;
}

async function loadConfig() {
  state.config = await api('/api/config');
  const f = $('#config-form');
  setNested(f, 'poll_interval_seconds', state.config.poll_interval_seconds);
  setNested(f, 'risk.min_confidence_to_alert', state.config.risk.min_confidence_to_alert);
  setNested(f, 'risk.sl_atr_multiplier', state.config.risk.sl_atr_multiplier);
  setNested(f, 'risk.tp_atr_multiplier', state.config.risk.tp_atr_multiplier);
  setNested(f, 'pump_dump.min_probability', state.config.pump_dump.min_probability);
  setNested(f, 'pump_dump.volume_spike_ratio', state.config.pump_dump.volume_spike_ratio);
  setNested(f, 'pump_dump.price_accel_atr_mult', state.config.pump_dump.price_accel_atr_mult);
  setNested(f, 'pump_dump.rsi_thrust_delta', state.config.pump_dump.rsi_thrust_delta);
  setNested(f, 'pump_dump.volatility_expansion', state.config.pump_dump.volatility_expansion);
}

async function saveConfig(e) {
  e.preventDefault();
  const f = e.target;
  const data = new FormData(f);
  const payload = { risk: {}, pump_dump: {} };
  for (const [k, v] of data.entries()) {
    if (v === '') continue;
    if (k.startsWith('risk.')) payload.risk[k.slice(5)] = Number(v);
    else if (k.startsWith('pump_dump.')) payload.pump_dump[k.slice(10)] = Number(v);
    else payload[k] = Number(v);
  }
  await api('/api/config', { method: 'POST', body: JSON.stringify(payload) });
  $('#config-dialog').close();
}

// --------------------------------------------------------------------------
// Initial load + SSE stream
// --------------------------------------------------------------------------

async function refreshAll() {
  const [signals, pumps, alerts, watchlist, status] = await Promise.all([
    api('/api/signals'),
    api('/api/pumps'),
    api('/api/alerts'),
    api('/api/watchlist'),
    api('/api/status'),
  ]);
  state.signals = signals.signals;
  state.pumps = Object.fromEntries(pumps.pumps.map(p => [`${p.asset_type}:${p.symbol}`, p]));
  state.alerts = alerts.alerts;
  state.watchlist = watchlist.watchlist;
  state.status = status;

  renderHeaderStats();
  renderWatchlist();
  renderGrid();
  renderAlerts();
}

function startStream() {
  const es = new EventSource('/api/stream');

  es.addEventListener('status', (ev) => {
    state.status = JSON.parse(ev.data);
    renderHeaderStats();
  });
  es.addEventListener('signal', (ev) => {
    const sig = JSON.parse(ev.data);
    const idx = state.signals.findIndex(s => s.symbol === sig.symbol && s.asset_type === sig.asset_type);
    if (idx >= 0) state.signals[idx] = sig;
    else state.signals.push(sig);
    renderGrid();
  });
  es.addEventListener('pump', (ev) => {
    const p = JSON.parse(ev.data);
    state.pumps[`${p.asset_type}:${p.symbol}`] = p;
    renderGrid();
  });
  es.addEventListener('alert', (ev) => {
    const a = JSON.parse(ev.data);
    state.alerts.unshift(a);
    if (state.alerts.length > 200) state.alerts.length = 200;
    renderAlerts();
    renderHeaderStats();
  });
  es.addEventListener('watchlist', (ev) => {
    state.watchlist = JSON.parse(ev.data);
    renderWatchlist();
  });
  es.addEventListener('error', () => {
    // EventSource va tenter de se reconnecter automatiquement
  });
}

// --------------------------------------------------------------------------
// UI wiring
// --------------------------------------------------------------------------

function wireUI() {
  $$('.chip').forEach(b => {
    b.addEventListener('click', () => {
      $$('.chip').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      state.filter = b.dataset.filter;
      renderGrid();
    });
  });

  $('#search-input').addEventListener('input', (e) => {
    state.search = e.target.value;
    renderGrid();
  });

  $('#btn-scan').addEventListener('click', async () => {
    try { await api('/api/scan', { method: 'POST' }); } catch {}
  });

  $('#btn-catalog').addEventListener('click', async () => {
    await loadCatalogStats();
    await loadCatalog();
    $('#catalog-dialog').showModal();
  });

  $('#catalog-search').addEventListener('input', debounce(loadCatalog, 250));
  $('#catalog-type').addEventListener('change', loadCatalog);
  $('#catalog-refresh').addEventListener('click', loadCatalog);

  $('#btn-config').addEventListener('click', async () => {
    await loadConfig();
    $('#config-dialog').showModal();
  });
  $('#config-form').addEventListener('submit', saveConfig);

  $$('[data-close-dialog]').forEach(b => {
    b.addEventListener('click', () => document.getElementById(b.dataset.closeDialog).close());
  });
}

function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

// --------------------------------------------------------------------------

(async function main() {
  wireUI();
  try { await refreshAll(); } catch (e) { console.error(e); }
  startStream();
  setInterval(refreshAll, 30_000);  // safety net si SSE drops
})();
