// CHI Packet Tracer — Interactive Frontend
const CH_COLOR = { REQ:'#ff9c52', SNP:'#36d1c4', RSP:'#ff5c97', DAT:'#5da9ff', CRD:'#f3d65a', ACT:'#b48efa' };

const SCENARIOS = [
  { label: 'Read from dirty owner', opcode:'ReadShared', src_id:'RN0', address:'0x2000' },
  { label: 'Write shared line', opcode:'WriteUnique', src_id:'RN0', address:'0x1000', data:'0xDADA5501' },
  { label: 'Clean shared CMO', opcode:'CleanShared', src_id:'RN1', address:'0x2800' },
  { label: 'Invalidate self', opcode:'MakeInvalid', src_id:'RN0', address:'0x1000' },
];

// ---- State ----
let snapshot = null;
let events = [];
let stepIndex = -1;
let playToken = 0;
let selectedNode = null;
let dragging = null;
let dragOff = {x:0, y:0};
let speedMultiplier = 1; // controlled by slider (0.1× to 2×)

// ---- DOM refs ----
const $ = (s) => document.querySelector(s);
const dom = {
  form: $('#txn-form'), selOp: $('#sel-opcode'), selSrc: $('#sel-src'),
  inpAddr: $('#inp-addr'), inpData: $('#inp-data'), dataRow: $('#data-row'),
  canvas: $('#canvas'), svgLinks: $('#svg-links'), nodeLayer: $('#node-layer'),
  pktLayer: $('#packet-layer'), inspector: $('#inspector'), inspTitle: $('#insp-title'),
  inspBody: $('#insp-body'), closeInsp: $('#close-insp'), toast: $('#toast'),
  drawerBody: $('#drawer-body'), drawerTab: $('#drawer-tab'), drawer: $('#drawer'),
  evtCount: $('#evt-count'), statusPill: $('#status-pill'),
  scenarioList: $('#scenario-list'), legend: $('#legend'),
  ctxMenu: $('#ctx-menu'),
  btnReset: $('#btn-reset'), btnStep: $('#btn-step'), btnPlay: $('#btn-play'),
  speedSlider: $('#speed-slider'), speedLabel: $('#speed-label'),
};

// ---- Boot ----
init();
async function init() {
  bindUI();
  renderLegend();
  renderScenarios();
  snapshot = await api('/api/state');
  applySnapshot();
}

// ---- UI Bindings ----
function bindUI() {
  dom.form.addEventListener('submit', onSend);
  dom.selOp.addEventListener('change', syncDataRow);
  dom.closeInsp.addEventListener('click', closeInspector);
  dom.drawerTab.addEventListener('click', toggleDrawer);
  dom.btnReset.addEventListener('click', onReset);
  dom.btnStep.addEventListener('click', onStep);
  dom.btnPlay.addEventListener('click', onPlayAll);
  dom.speedSlider.addEventListener('input', onSpeedChange);
  document.addEventListener('click', () => dom.ctxMenu.classList.add('hidden'));
  document.addEventListener('contextmenu', (e) => { if (!e.target.closest('.node')) { dom.ctxMenu.classList.add('hidden'); }});
  window.addEventListener('pointermove', onDragMove);
  window.addEventListener('pointerup', onDragEnd);
}

function onSpeedChange() {
  // Slider 1-10 maps to multiplier: 1=0.1×(slow) 5=1×(normal) 10=2×(fast)
  const v = +dom.speedSlider.value;
  if (v <= 5) speedMultiplier = 0.1 + (v - 1) * 0.225; // 1→0.1, 5→1.0
  else speedMultiplier = 1 + (v - 5) * 0.2;            // 6→1.2, 10→2.0
  dom.speedLabel.textContent = speedMultiplier.toFixed(1) + '×';
  // Update CSS transition for in-flight packets
  document.documentElement.style.setProperty('--pkt-speed', (1.1 / speedMultiplier) + 's');
}

function renderLegend() {
  dom.legend.innerHTML = Object.entries(CH_COLOR).map(([ch, col]) =>
    `<div class="leg-item"><span class="leg-dot" style="background:${col}"></span>${ch}</div>`
  ).join('');
}

function renderScenarios() {
  dom.scenarioList.innerHTML = SCENARIOS.map((s, i) =>
    `<button type="button" class="scenario-btn" data-idx="${i}">${s.label}</button>`
  ).join('');
  dom.scenarioList.addEventListener('click', (e) => {
    const btn = e.target.closest('.scenario-btn');
    if (!btn) return;
    const s = SCENARIOS[+btn.dataset.idx];
    dom.selOp.value = s.opcode;
    dom.selSrc.value = s.src_id;
    dom.inpAddr.value = s.address;
    dom.inpData.value = s.data || '';
    syncDataRow();
  });
}

function syncDataRow() {
  dom.dataRow.classList.toggle('hidden', dom.selOp.value !== 'WriteUnique');
}

// ---- Snapshot rendering ----
function applySnapshot() {
  if (!snapshot) return;
  hydrateSrcSelect();
  renderLinks();
  renderNodes();
}

function hydrateSrcSelect() {
  const rns = snapshot.nodes.filter(n => n.kind === 'RN');
  const prev = dom.selSrc.value;
  dom.selSrc.innerHTML = rns.map(n => `<option value="${n.node_id}">${n.node_id}</option>`).join('');
  if (rns.some(n => n.node_id === prev)) dom.selSrc.value = prev;
}

function renderLinks() {
  const nodes = Object.fromEntries(snapshot.nodes.map(n => [n.node_id, n]));
  dom.svgLinks.innerHTML = snapshot.links.map((lk, i) => {
    const s = nodes[lk.src], d = nodes[lk.dst];
    const mx = (s.x + d.x) / 2, my = (s.y + d.y) / 2;
    return `
      <line class="link-line" id="link-${i}" data-pair="${lk.src}:${lk.dst}" x1="${s.x}" y1="${s.y}" x2="${d.x}" y2="${d.y}"/>
      <text class="link-label" x="${mx}" y="${my - 6}">${lk.label}</text>
    `;
  }).join('');
}

function renderNodes() {
  dom.nodeLayer.innerHTML = '';
  snapshot.nodes.forEach(n => {
    const el = document.createElement('div');
    el.className = 'node' + (selectedNode === n.node_id ? ' selected' : '') + (n.kind === 'ICN' ? ' node-icn' : '');
    el.dataset.id = n.node_id;
    el.style.left = n.x + 'px';
    el.style.top = n.y + 'px';
    el.style.setProperty('--node-color', n.color);

    // Build inline cache view
    const cacheLines = snapshot.caches[n.node_id] || [];
    let cacheHtml = '';
    if (cacheLines.length) {
      cacheHtml = `<div class="node-cache"><div class="nc-title">Cache</div>` +
        cacheLines.map(l => `<div class="nc-line"><span class="nc-addr">${l.address}</span><span class="nc-state nc-st-${l.state}">${l.state}</span></div>`).join('') +
        `</div>`;
    }

    // Build inline snoop filter view
    // ICN shows ALL entries (the SF lives there); other nodes show entries they participate in
    const isICN = n.kind === 'ICN';
    const sfEntries = isICN
      ? snapshot.snoop_filter
      : snapshot.snoop_filter.filter(e => e.home === n.node_id || e.owner === n.node_id || e.sharers.includes(n.node_id));
    let sfHtml = '';
    if (sfEntries.length) {
      sfHtml = `<div class="node-sf"><div class="nc-title">${isICN ? 'Snoop Filter' : 'SF'}</div>` +
        sfEntries.map(e => {
          if (isICN) {
            // ICN view: show owner and sharers for each address
            const ownLabel = e.owner ? e.owner : '—';
            const shrLabel = e.sharers.length ? e.sharers.join(',') : '—';
            return `<div class="nc-line"><span class="nc-addr">${e.address}</span><span class="nc-role nc-r-${e.owner ? 'own' : 'shr'}">${ownLabel}</span><span class="nc-state nc-st-${e.state_hint}">${e.state_hint.slice(0,2)}</span></div>`;
          }
          const role = e.owner === n.node_id ? 'own' : e.home === n.node_id ? 'home' : 'shr';
          return `<div class="nc-line"><span class="nc-addr">${e.address}</span><span class="nc-role nc-r-${role}">${role}</span><span class="nc-state nc-st-${e.state_hint}">${e.state_hint.slice(0,2)}</span></div>`;
        }).join('') +
        `</div>`;
    }

    el.innerHTML = `
      <div class="node-bar"></div>
      <div class="node-label">${n.label}</div>
      <div class="node-id">${n.node_id}</div>
      <span class="node-kind">${n.kind}</span>
      ${cacheHtml}${sfHtml}
    `;
    el.addEventListener('pointerdown', (e) => onNodePointerDown(e, n));
    el.addEventListener('click', (e) => { e.stopPropagation(); onNodeClick(n); });
    el.addEventListener('contextmenu', (e) => { e.preventDefault(); e.stopPropagation(); showCtxMenu(e, n); });
    dom.nodeLayer.appendChild(el);
  });
  // Click on canvas background to deselect
  dom.canvas.addEventListener('click', (e) => {
    if (e.target === dom.canvas || e.target === dom.nodeLayer) { selectedNode = null; closeInspector(); renderNodes(); }
  }, { once: false });
}

// ---- Node interactions ----
function onNodePointerDown(e, node) {
  const rect = dom.canvas.getBoundingClientRect();
  dragOff = { x: e.clientX - rect.left - node.x, y: e.clientY - rect.top - node.y };
  dragging = node.node_id;
  e.target.closest('.node').setPointerCapture(e.pointerId);
}
function onDragMove(e) {
  if (!dragging) return;
  const rect = dom.canvas.getBoundingClientRect();
  const node = snapshot.nodes.find(n => n.node_id === dragging);
  node.x = Math.max(70, Math.min(rect.width - 70, e.clientX - rect.left - dragOff.x));
  node.y = Math.max(50, Math.min(rect.height - 50, e.clientY - rect.top - dragOff.y));
  renderLinks();
  const el = dom.nodeLayer.querySelector(`[data-id="${dragging}"]`);
  if (el) { el.style.left = node.x + 'px'; el.style.top = node.y + 'px'; }
}
function onDragEnd() {
  if (dragging) { saveLayout(); dragging = null; }
}

function onNodeClick(node) {
  selectedNode = node.node_id;
  renderNodes();
  openInspector(node);
}

function showCtxMenu(e, node) {
  dom.ctxMenu.classList.remove('hidden');
  dom.ctxMenu.style.left = e.clientX + 'px';
  dom.ctxMenu.style.top = e.clientY + 'px';
  const isRN = node.kind === 'RN';
  dom.ctxMenu.innerHTML = `
    <button class="ctx-item" data-action="inspect">&#x1F50D; Inspect ${node.node_id}</button>
    ${isRN ? `<button class="ctx-item" data-action="read">&#x2193; ReadShared from here</button>
    <button class="ctx-item" data-action="write">&#x2191; WriteUnique from here</button>` : ''}
    <div class="ctx-sep"></div>
    <button class="ctx-item" data-action="cache">&#x1F4BE; View cache</button>
  `;
  dom.ctxMenu.querySelectorAll('.ctx-item').forEach(btn => {
    btn.addEventListener('click', () => {
      dom.ctxMenu.classList.add('hidden');
      const action = btn.dataset.action;
      if (action === 'inspect' || action === 'cache') openInspector(node);
      else if (action === 'read') { dom.selOp.value = 'ReadShared'; dom.selSrc.value = node.node_id; syncDataRow(); }
      else if (action === 'write') { dom.selOp.value = 'WriteUnique'; dom.selSrc.value = node.node_id; syncDataRow(); }
    });
  });
}

// ---- Inspector ----
function openInspector(node) {
  dom.inspector.classList.remove('closed');
  dom.inspector.style.width = '280px';
  dom.inspTitle.textContent = node.label + ' (' + node.node_id + ')';
  const cache = snapshot.caches[node.node_id] || [];
  const sfEntries = snapshot.snoop_filter.filter(e => e.home === node.node_id || e.sharers.includes(node.node_id) || e.owner === node.node_id);
  const credits = snapshot.credits[node.node_id] || {};

  let html = `<div class="insp-section"><h4>Cache Lines</h4>`;
  if (cache.length === 0) html += `<p style="color:var(--muted)">Empty</p>`;
  else {
    html += `<table><tr><th>Addr</th><th>State</th><th>Data</th></tr>`;
    cache.forEach(l => { html += `<tr><td>${l.address}</td><td><span class="state-badge">${l.state}</span></td><td style="font-family:monospace;font-size:0.72rem">${l.data}</td></tr>`; });
    html += `</table>`;
  }
  html += `</div>`;

  html += `<div class="insp-section"><h4>Snoop Filter</h4>`;
  if (sfEntries.length === 0) html += `<p style="color:var(--muted)">No entries</p>`;
  else {
    sfEntries.forEach(e => {
      html += `<table><tr><th>Addr</th><td>${e.address}</td></tr><tr><th>Owner</th><td>${e.owner||'—'}</td></tr><tr><th>Sharers</th><td>${e.sharers.join(', ')||'—'}</td></tr><tr><th>State</th><td><span class="state-badge">${e.state_hint}</span></td></tr></table>`;
    });
  }
  html += `</div>`;

  html += `<div class="insp-section"><h4>Credits</h4><table>`;
  Object.entries(credits).forEach(([ch, v]) => {
    const pct = (v / 8 * 100).toFixed(0);
    html += `<tr><th>${ch}</th><td><div style="display:flex;align-items:center;gap:6px"><div style="flex:1;height:6px;border-radius:3px;background:var(--border)"><div style="height:100%;width:${pct}%;border-radius:3px;background:${CH_COLOR[ch]||'var(--muted)'}"></div></div><span style="font-size:0.7rem">${v}</span></div></td></tr>`;
  });
  html += `</table></div>`;

  dom.inspBody.innerHTML = html;
}

function closeInspector() {
  dom.inspector.classList.add('closed');
  selectedNode = null;
  renderNodes();
}

// ---- Drawer / Timeline ----
function toggleDrawer() {
  dom.drawer.classList.toggle('open');
}

function renderTimeline() {
  dom.evtCount.textContent = events.length;
  if (!events.length) { dom.drawerBody.innerHTML = '<span style="color:var(--muted);font-size:0.76rem;padding:8px">No events yet. Send a transaction.</span>'; return; }
  dom.drawerBody.innerHTML = events.map((ev, i) => `
    <div class="evt-chip${i === stepIndex ? ' active' : ''}" data-idx="${i}">
      <span class="ch" data-ch="${ev.channel}">${ev.channel}</span>
      <div class="evt-title">${ev.title}</div>
      <div class="evt-route">${ev.src} → ${ev.dst}</div>
    </div>
  `).join('');
  // scroll active into view
  const active = dom.drawerBody.querySelector('.evt-chip.active');
  if (active) active.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
}

// ---- Transaction API ----
async function onSend(e) {
  e.preventDefault();
  const fd = new FormData(dom.form);
  const payload = {
    opcode: fd.get('opcode'), src_id: fd.get('src_id'), address: fd.get('address'),
    data: fd.get('data') || null, size: 64, qos: 2, ns: false,
    client_state: buildClientState(),
  };
  setStatus('busy', 'Simulating...');
  const result = await api('/api/transaction', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  events = result.events;
  snapshot = result.snapshot;
  stepIndex = -1;
  applySnapshot();
  renderTimeline();
  dom.drawer.classList.add('open');
  showToast(result.summary);
  setStatus('ok', 'Done');
  await playEvents(result.events);
}

function buildClientState() {
  if (!snapshot) return null;
  return {
    caches: snapshot.caches,
    snoop_filter: snapshot.snoop_filter,
    credits: snapshot.credits,
    history: snapshot.history || [],
    next_txn_id: snapshot.next_txn_id || 17,
  };
}

async function onReset() {
  snapshot = await api('/api/reset', { method:'POST' });
  events = []; stepIndex = -1;
  applySnapshot(); renderTimeline();
  closeInspector();
  showToast('Fabric reset to initial CHI state.');
  setStatus('ok', 'Ready');
}

async function onStep() {
  if (!events.length) return;
  stepIndex = Math.min(stepIndex + 1, events.length - 1);
  renderTimeline();
  await animateEvent(events[stepIndex]);
}

async function onPlayAll() {
  if (!events.length) return;
  const token = ++playToken;
  setStatus('busy', 'Playing...');
  for (let i = 0; i < events.length; i++) {
    if (token !== playToken) return;
    stepIndex = i;
    renderTimeline();
    await animateEvent(events[i]);
    await wait(180 / speedMultiplier);
  }
  setStatus('ok', 'Done');
}

async function playEvents(evts) {
  const token = ++playToken;
  for (let i = 0; i < evts.length; i++) {
    if (token !== playToken) return;
    stepIndex = i;
    renderTimeline();
    await animateEvent(evts[i]);
    await wait(120 / speedMultiplier);
  }
}

// ---- Animations ----
async function animateEvent(ev) {
  // Highlight nodes
  highlightNode(ev.src);
  highlightNode(ev.dst);
  glowLink(ev.src, ev.dst, CH_COLOR[ev.channel] || CH_COLOR.ACT);

  if (ev.channel !== 'ACT' && ev.src !== ev.dst) {
    await firePacket(ev);
  } else {
    await wait(350 / speedMultiplier);
  }
  clearGlow();
}

function highlightNode(id) {
  const el = dom.nodeLayer.querySelector(`[data-id="${id}"]`);
  if (el) { el.classList.add('active-anim'); setTimeout(() => el.classList.remove('active-anim'), 600); }
}

function glowLink(src, dst, color) {
  const line = dom.svgLinks.querySelector(`[data-pair="${src}:${dst}"], [data-pair="${dst}:${src}"]`);
  if (line) { line.classList.add('glow'); line.style.setProperty('--glow-color', color); }
}
function clearGlow() {
  dom.svgLinks.querySelectorAll('.glow').forEach(l => { l.classList.remove('glow'); l.style.removeProperty('--glow-color'); });
}

async function firePacket(ev) {
  const srcN = snapshot.nodes.find(n => n.node_id === ev.src);
  const dstN = snapshot.nodes.find(n => n.node_id === ev.dst);
  if (!srcN || !dstN) { await wait(300 / speedMultiplier); return; }

  const flightMs = 1100 / speedMultiplier;  // 2× slower base flight
  const dwellMs = 900 / speedMultiplier;     // hold at destination so user can read
  const pkt = document.createElement('div');
  pkt.className = 'pkt';
  pkt.dataset.ch = ev.channel;
  // Build info label from packet fields
  let infoText = ev.title || ev.channel;
  if (ev.packet) {
    const p = ev.packet;
    const parts = [p.opcode];
    if (p.addr) parts.push(p.addr);
    if (p.payload) parts.push(p.payload.length > 10 ? p.payload.slice(0, 10) + '…' : p.payload);
    infoText = parts.join(' ');
  }
  pkt.dataset.info = infoText;
  pkt.style.setProperty('--pkt-color', CH_COLOR[ev.channel] || CH_COLOR.ACT);
  pkt.style.transition = `left ${flightMs}ms cubic-bezier(0.22,0.9,0.36,1), top ${flightMs}ms cubic-bezier(0.22,0.9,0.36,1), opacity 0.15s`;
  pkt.style.left = srcN.x + 'px'; pkt.style.top = srcN.y + 'px';
  dom.pktLayer.appendChild(pkt);
  await wait(20);
  pkt.style.left = dstN.x + 'px'; pkt.style.top = dstN.y + 'px';
  await wait(flightMs + 50);
  // Dwell at destination so user can see the packet info
  pkt.classList.add('pkt-arrived');
  await wait(dwellMs);
  pkt.style.opacity = '0';
  await wait(200 / speedMultiplier);
  pkt.remove();
}

// ---- Layout persistence ----
async function saveLayout() {
  if (!snapshot) return;
  const positions = snapshot.nodes.map(n => ({ node_id: n.node_id, x: Math.round(n.x), y: Math.round(n.y) }));
  snapshot = await api('/api/layout', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ positions }) });
  applySnapshot();
}

// ---- Utilities ----
function showToast(msg) {
  dom.toast.textContent = msg;
  dom.toast.classList.add('show');
  setTimeout(() => dom.toast.classList.remove('show'), 4000);
}
function setStatus(type, text) {
  dom.statusPill.textContent = text;
  dom.statusPill.classList.toggle('busy', type === 'busy');
}
function wait(ms) { return new Promise(r => setTimeout(r, ms)); }
async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let msg = `Error ${res.status}`;
    try { const j = await res.json(); msg = j.detail || msg; } catch {}
    showToast(msg); throw new Error(msg);
  }
  return res.json();
}
