// 信道测量分析软件 前端逻辑
// 设计: docs/specs/2026-06-16-channel-analysis-ui-implementation-spec.md

// ---- ECharts 离线兜底（本地 echarts.min.js 缺失时不至于整页崩） ----
if (!window.echarts) {
  window.echarts = {
    init(container) {
      container.innerHTML = '<div style="padding:12px;color:#66788a;font-size:13px">ECharts 未加载（缺 /static/echarts.min.js）</div>';
      return { setOption() {}, resize() {}, getDataURL() { return ''; }, dispatchAction() {} };
    }
  };
}

// ---- colormap：色标固定，取值范围自适应（不写死 dB） ----
const JET_STOPS = ['#00008f', '#0000ff', '#0080ff', '#00ffff', '#80ff80', '#ffff00', '#ff8000', '#ff0000', '#800000'];
const HOT_STOPS = ['#000000', '#3b0000', '#8f0000', '#ff3000', '#ff8000', '#ffd000', '#ffff60', '#ffffff'];

function robustRange(values, loPct = 0, hiPct = 100) {
  const sorted = values.filter(Number.isFinite).slice().sort((a, b) => a - b);
  if (!sorted.length) return [0, 1];
  const q = p => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(p / 100 * (sorted.length - 1))))];
  let lo = q(loPct), hi = q(hiPct);
  if (hi - lo < 1e-6) hi = lo + 1;
  return [lo, hi];
}

// ---- 帧间隔自检测 + 降采样到 ~1 CIR/秒 ----
function detectDisplayStep(dataset) {
  const rx = dataset.rxGps || [];
  if (rx.length < 2) return { decim: 1, dtSec: 1 };
  const dts = [];
  for (let i = 1; i < rx.length; i++) dts.push(Number(rx[i].timeSec) - Number(rx[i - 1].timeSec));
  dts.sort((a, b) => a - b);
  const medDt = dts[Math.floor(dts.length / 2)] || 1;
  const decim = medDt > 0 && medDt < 1 ? Math.max(1, Math.round(1 / medDt)) : 1;
  return { decim, dtSec: medDt };
}

// ---- frame-id 映射（不依赖数组下标对齐） ----
function buildFrameIndex(dataset) {
  const map = new Map();
  (dataset.framePayloads || []).forEach(p => map.set(p.frame, { payload: p }));
  (dataset.rxGps || []).forEach(g => { if (map.has(g.frame)) map.get(g.frame).gps = g; });
  const orderedFrames = Array.from(map.keys()).sort((a, b) => a - b);
  return { map, orderedFrames };
}

const AppState = {
  dataset: null,
  datasetName: null,
  uiState: 'IDLE',          // IDLE | ANALYZING | LOADING_DATA | READY | ERROR
  frameIndex: { map: new Map(), orderedFrames: [] },
  decim: 1,
  dtSec: 1,
  sliderValue: 0,
  playing: false,
  timer: null,
  cursor: false,
  charts: {},
  leafletMap: null,
  leafletLayers: {},
  selectedFileRole: null,
  rxBinName: null,
  calBinName: null,
  pollTimer: null,
};
window.AppState = AppState;

const DATASET_DEPENDENT_CONTROLS = ['frameSlider', 'playPauseBtn', 'jumpInput', 'jumpBtn', 'exportCsvBtn'];

function setUiState(state) {
  AppState.uiState = state;
  const ready = state === 'READY';
  DATASET_DEPENDENT_CONTROLS.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = !ready; });
  document.querySelectorAll('.export-fig-btn[data-chart]').forEach(b => { b.disabled = !ready; });
}

function resetUI() {
  // 只清状态/禁用控件，不改 AppState.uiState —— 状态转换由调用方的 setUiState() 决定，
  // 否则会覆盖调用方刚设好的状态，导致 syncFrame() 的状态门禁错误地拦截首次加载。
  stopPlayback();
  AppState.sliderValue = 0;
  const slider = document.getElementById('frameSlider');
  slider.max = '0'; slider.value = '0';
  DATASET_DEPENDENT_CONTROLS.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = true; });
  document.querySelectorAll('.export-fig-btn[data-chart]').forEach(b => { b.disabled = true; });
  const label = document.getElementById('playbackTimeLabel');
  if (label) label.textContent = '-- s / -- s';
}

// ---------------- 布局初始化 ----------------
function initLayout() {
  AppState.charts.pdpWaterfall = echarts.init(document.getElementById('pdpWaterfallChart'));
  AppState.charts.dopplerWaterfall = echarts.init(document.getElementById('dopplerWaterfallChart'));
  AppState.charts.delayTime = echarts.init(document.getElementById('delayTimeChart'));
  AppState.charts.dopplerTime = echarts.init(document.getElementById('dopplerTimeChart'));
  AppState.charts.pdp = echarts.init(document.getElementById('pdpChart'));
  initLeafletMap();
  window.addEventListener('resize', () => {
    Object.values(AppState.charts).forEach(c => c.resize());
    if (AppState.leafletMap) AppState.leafletMap.invalidateSize();
  });
}

function initLeafletMap() {
  if (!window.L || AppState.leafletMap) return;
  const el = document.getElementById('mapLeaflet');
  if (!el) return;
  AppState.leafletMap = L.map(el, { preferCanvas: true, zoomControl: true });
  L.tileLayer('/tiles/base/{z}/{x}/{y}.jpg', { maxZoom: 19, attribution: 'Tiles &copy; Esri' }).addTo(AppState.leafletMap);
  AppState.leafletMap.setView([40.3032, 115.7719], 17);
}

// ---------------- 控件绑定 ----------------
function bindControls() {
  document.getElementById('datasetSelect').addEventListener('change', e => loadDatasetFromApi(e.target.value));
  document.getElementById('frameSlider').addEventListener('input', e => syncFrame(Number(e.target.value)));
  document.getElementById('playPauseBtn').addEventListener('click', togglePlayback);
  document.getElementById('jumpBtn').addEventListener('click', jumpToSeconds);
  document.getElementById('cursorToggle').addEventListener('change', e => { AppState.cursor = e.target.checked; rerenderAll(); });

  document.getElementById('importBtn').addEventListener('click', doImport);
  document.getElementById('analyzeBtn').addEventListener('click', () => runAnalyze(false));
  document.getElementById('reanalyzeBtn').addEventListener('click', () => runAnalyze(true));

  document.querySelectorAll('input[name="txMode"]').forEach(el => el.addEventListener('change', updateTxModeUI));
  document.getElementById('rxChooseBtn').addEventListener('click', () => chooseLocalFile('rx'));
  document.getElementById('calChooseBtn').addEventListener('click', () => chooseLocalFile('calibration'));
  document.getElementById('hiddenFileInput').addEventListener('change', onLocalFileChosen);

  document.querySelectorAll('.export-fig-btn[data-chart]').forEach(btn =>
    btn.addEventListener('click', () => exportChartPng(btn.dataset.chart)));
  document.getElementById('exportCsvBtn').addEventListener('click', exportPdpCsv);
}

function chooseLocalFile(role) { AppState.selectedFileRole = role; document.getElementById('hiddenFileInput').click(); }

function onLocalFileChosen(event) {
  const file = event.target.files[0];
  if (!file) return;
  if (AppState.selectedFileRole === 'rx') {
    AppState.rxBinName = file.name;
    document.getElementById('rxPath').value = file.name;
  } else if (AppState.selectedFileRole === 'calibration') {
    AppState.calBinName = file.name;
    document.getElementById('calPath').value = file.name;
  }
  event.target.value = '';
}

function updateTxModeUI() {
  const moving = document.querySelector('input[name="txMode"]:checked').value === 'moving';
  document.getElementById('txStaticInputs').hidden = moving;
  document.getElementById('txBinBtn').hidden = !moving;
}

// ---------------- 导入 / 分析 ----------------
function doImport() {
  if (!AppState.rxBinName) { alert('请先选择 Rx 数据'); document.querySelector('[data-kind="rx"]').classList.add('attn'); return; }
  markLoaded('rxLoadState', true);
  markLoaded('calLoadState', !!AppState.calBinName);   // 校准可选；未选保持 pending
  document.getElementById('datasetStatus').textContent = '已导入，待分析';
  document.getElementById('datasetStatus').className = 'status-pill warning';
}

function parseCarrier() {
  const v = parseFloat(document.getElementById('carrierHzInput').value);
  if (!Number.isFinite(v) || v <= 0) return null;
  const unit = document.getElementById('carrierUnitSelect').value;
  return unit === 'GHz' ? v * 1e9 : v * 1e6;
}

async function runAnalyze(force) {
  if (!AppState.rxBinName) { alert('请先选择 Rx 数据'); return; }
  const carrierHz = parseCarrier();
  if (carrierHz === null) { alert('请填写载波频率（算 Doppler 用）'); document.getElementById('carrierHzInput').focus(); return; }
  const txMode = document.querySelector('input[name="txMode"]:checked').value;
  const body = {
    rxBinName: AppState.rxBinName, calBinName: AppState.calBinName || null, carrierHz, txMode, force,
    txLat: numOrNull('txLat'), txLon: numOrNull('txLon'), txAlt: numOrNull('txAlt'),
  };
  setUiState('ANALYZING');
  showProgress(true, 0, '提交分析…');
  try {
    const res = await fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error((await res.json()).detail || res.status);
    const out = await res.json();
    if (out.status === 'ready') { showProgress(false); await loadDatasetFromApi(out.datasetName); }
    else if (out.status === 'running') pollAnalyze(out.jobId);
  } catch (err) {
    showProgress(false); setUiState('ERROR'); alert(`分析失败：${err.message}`);
  }
}

function pollAnalyze(jobId) {
  clearInterval(AppState.pollTimer);
  AppState.pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/analyze/status/${jobId}`);
      if (!res.ok) throw new Error(res.status);
      const s = await res.json();
      showProgress(true, s.progress || 0, `分析中… ${Math.round(s.progress || 0)}%`);
      if (s.status === 'done') { clearInterval(AppState.pollTimer); showProgress(false); await loadDatasetFromApi(s.datasetName); }
      else if (s.status === 'error') { clearInterval(AppState.pollTimer); showProgress(false); setUiState('ERROR'); alert(`分析失败：${s.detail || '未知错误'}`); }
    } catch (err) {
      clearInterval(AppState.pollTimer); showProgress(false); setUiState('ERROR'); alert(`分析状态查询失败：${err.message}`);
    }
  }, 1500);
}

function showProgress(show, pct = 0, label = '') {
  document.getElementById('analyzeProgress').hidden = !show;
  document.getElementById('analyzeProgressFill').style.width = `${pct}%`;
  document.getElementById('analyzeProgressLabel').textContent = label;
}

// ---------------- 数据加载（原子、有序） ----------------
async function loadDatasetList() {
  const res = await fetch('/api/datasets');
  const payload = await res.json();
  const select = document.getElementById('datasetSelect');
  select.innerHTML = '';
  payload.datasets.forEach(name => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    if (name === payload.default) opt.selected = true;
    select.appendChild(opt);
  });
}

async function checkBackend() {
  const status = document.getElementById('backendStatus');
  try {
    const res = await fetch('/api/health');
    const payload = await res.json();
    status.textContent = `后端正常 · ${payload.datasetCount} 个数据集`;
    status.className = 'status-pill ok';
  } catch (err) {
    status.textContent = '后端不可用';
    status.className = 'status-pill warning';
  }
}

async function loadDatasetFromApi(name = 'default') {
  setUiState('LOADING_DATA');
  resetUI();
  try {
    const res = await fetch(`/api/datasets/${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error(`dataset load failed: ${res.status}`);
    const dataset = await res.json();
    AppState.dataset = dataset;
    AppState.datasetName = name === 'default' ? (document.getElementById('datasetSelect').value || name) : name;
    AppState.frameIndex = buildFrameIndex(dataset);
    const step = detectDisplayStep(dataset);
    AppState.decim = step.decim; AppState.dtSec = step.dtSec;
    const slider = document.getElementById('frameSlider');
    slider.max = String(Math.max(0, Math.floor((AppState.frameIndex.orderedFrames.length - 1) / AppState.decim)));
    slider.value = '0'; AppState.sliderValue = 0;

    document.getElementById('datasetStatus').textContent = '数据已加载';
    document.getElementById('datasetStatus').className = 'status-pill ok';

    updatePdpWaterfall();
    updateDopplerWaterfall();
    updateDelayTime();
    updateDopplerTime();
    syncFrame(0);
    setUiState('READY');
  } catch (err) {
    setUiState('ERROR'); resetUI();
    document.getElementById('datasetStatus').textContent = '数据加载失败';
    document.getElementById('datasetStatus').className = 'status-pill warning';
    console.error(err);
  }
}

// ---------------- 汇总图（可交互，风格照参照图） ----------------
function visualMapContinuous(range, colors) {
  // 竖直色条放右侧，贴合 matplotlib 参照图的 colorbar 布局；calculable:false 只做静态展示
  return { type: 'continuous', min: range[0], max: range[1], dimension: 2, calculable: false, orient: 'vertical', right: 6, top: 'middle', itemWidth: 14, itemHeight: 140, text: ['高', '低'], textGap: 6, inRange: { color: colors } };
}
function dataZoomXY() { return [{ type: 'inside' }, { type: 'inside', orient: 'vertical' }]; }
function axisPointerOpt() { return AppState.cursor ? { axisPointer: { show: true, type: 'cross' } } : {}; }

const SPEED_OF_LIGHT_MPS = 299792458;
const MAX_DISPLAY_DISTANCE_M = 2000;
const MAX_DISPLAY_DELAY_NS = MAX_DISPLAY_DISTANCE_M / SPEED_OF_LIGHT_MPS * 1e9; // ~6671 ns

function updatePdpWaterfall() {
  const wf = AppState.dataset?.cirWaterfall;
  if (!wf) return;
  const cutoff = wf.delayNs.findIndex(d => Number(d) > MAX_DISPLAY_DELAY_NS);
  const lastIdx = cutoff === -1 ? wf.delayNs.length : cutoff;
  const delayNs = wf.delayNs.slice(0, lastIdx);
  const powerDb = wf.powerDb.map(row => row.slice(0, lastIdx));
  const range = robustRange(powerDb.flat());
  const data = powerDb.flatMap((row, t) => row.map((v, d) => [t, d, Number(v)]));
  AppState.charts.pdpWaterfall.setOption({
    tooltip: { position: 'top', formatter: p => `t=${wf.timeSec[p.data[0]]?.toFixed?.(1) ?? p.data[0]}s<br/>delay=${delayNs[p.data[1]]}ns<br/>power=${p.data[2].toFixed(1)} dB` },
    grid: { left: 56, right: 64, top: 16, bottom: 40 },
    xAxis: { type: 'category', name: 'Time (s)', nameLocation: 'middle', nameGap: 28, data: wf.timeSec.map(v => Number(v).toFixed(0)), axisLabel: { interval: Math.ceil(wf.timeSec.length / 8) } },
    yAxis: { type: 'category', name: 'Delay (ns)', data: delayNs, axisLabel: { interval: Math.ceil(delayNs.length / 8) } },
    visualMap: visualMapContinuous(range, JET_STOPS),
    series: [{ type: 'heatmap', data, progressive: 8000 }],
    ...axisPointerOpt(),
  }, true);
}

function updateDopplerWaterfall() {
  const dw = AppState.dataset?.dopplerTimeWaterfall;
  if (!dw) return;
  const range = robustRange(dw.powerDb.flat());
  const data = dw.powerDb.flatMap((row, dIdx) => row.map((v, tIdx) => [tIdx, dIdx, Number(v)]));
  AppState.charts.dopplerWaterfall.setOption({
    tooltip: { position: 'top', formatter: p => `t=${dw.timeSec[p.data[0]]?.toFixed?.(1) ?? p.data[0]}s<br/>doppler=${dw.dopplerHz[p.data[1]]}Hz<br/>power=${p.data[2].toFixed(1)} dB` },
    grid: { left: 56, right: 64, top: 16, bottom: 40 },
    xAxis: { type: 'category', name: 'Time (s)', nameLocation: 'middle', nameGap: 28, data: dw.timeSec.map(v => Number(v).toFixed(0)), axisLabel: { interval: Math.ceil(dw.timeSec.length / 8) } },
    yAxis: { type: 'category', name: 'Doppler (Hz)', data: dw.dopplerHz.map(v => Number(v).toFixed(0)), axisLabel: { interval: Math.ceil(dw.dopplerHz.length / 8) } },
    visualMap: visualMapContinuous(range, JET_STOPS),
    series: [{ type: 'heatmap', data, progressive: 8000 }],
    ...axisPointerOpt(),
  }, true);
}

function scatterChart(chart, xKey, yKey, xName, yName) {
  const mpc = AppState.dataset?.mpcScatter || [];
  if (!mpc.length) return;
  const range = robustRange(mpc.map(m => m.powerDb));
  const data = mpc.map(m => [Number(m[xKey]), Number(m[yKey]), Number(m.powerDb)]);
  chart.setOption({
    tooltip: { trigger: 'item', formatter: p => `${xName}=${p.data[0].toFixed(1)}<br/>${yName}=${p.data[1].toFixed(1)}<br/>power=${p.data[2].toFixed(1)} dB` },
    grid: { left: 60, right: 64, top: 16, bottom: 40 },
    xAxis: { type: 'value', name: xName, nameLocation: 'middle', nameGap: 28, scale: true },
    yAxis: { type: 'value', name: yName, scale: true },
    visualMap: visualMapContinuous(range, HOT_STOPS),
    dataZoom: dataZoomXY(),
    series: [{ type: 'scatter', symbolSize: 6, data }],
    ...axisPointerOpt(),
  }, true);
}
function updateDelayTime() { scatterChart(AppState.charts.delayTime, 'timeSec', 'delayNs', 'Measurement time (s)', 'Delay (ns)'); }
function updateDopplerTime() { scatterChart(AppState.charts.dopplerTime, 'timeSec', 'dopplerHz', 'Measurement time (s)', 'Doppler (Hz)'); }

// ---------------- 逐帧交互 ----------------
function currentEntry() {
  const { orderedFrames, map } = AppState.frameIndex;
  if (!orderedFrames.length) return null;
  const idx = Math.min(orderedFrames.length - 1, AppState.sliderValue * AppState.decim);
  return map.get(orderedFrames[idx]) || null;
}

function totalTimeSec() {
  const { orderedFrames, map } = AppState.frameIndex;
  if (!orderedFrames.length) return null;
  const lastEntry = map.get(orderedFrames[orderedFrames.length - 1]);
  return Number(lastEntry?.payload?.timeSec ?? null);
}

function updatePlaybackReadout() {
  const label = document.getElementById('playbackTimeLabel');
  if (!label) return;
  const total = totalTimeSec();
  const cur = currentEntry()?.payload?.timeSec;
  if (total === null || !Number.isFinite(total) || !Number.isFinite(cur)) {
    label.textContent = '-- s / -- s';
    return;
  }
  label.textContent = `${Number(cur).toFixed(1)} s / ${total.toFixed(1)} s`;
  const jumpInput = document.getElementById('jumpInput');
  if (jumpInput) { jumpInput.max = String(total); jumpInput.placeholder = `跳转秒 (0–${total.toFixed(0)})`; }
}

function syncFrame(sliderValue) {
  if (AppState.uiState !== 'READY' && AppState.uiState !== 'LOADING_DATA') return;
  const maxV = Number(document.getElementById('frameSlider').max || 0);
  AppState.sliderValue = Math.max(0, Math.min(maxV, sliderValue));
  document.getElementById('frameSlider').value = String(AppState.sliderValue);
  updatePdpCurve();
  updateMapPanel();
  updateStatusBar();
  updatePlaybackReadout();
}

function updatePdpCurve() {
  const curve = currentEntry()?.payload?.pdpCurve;
  if (!curve) return;
  const cutoff = curve.delayNs.findIndex(d => Number(d) > MAX_DISPLAY_DELAY_NS);
  const lastIdx = cutoff === -1 ? curve.delayNs.length : cutoff;
  const delayNs = curve.delayNs.slice(0, lastIdx);
  const powerDb = curve.powerDb.slice(0, lastIdx);
  AppState.charts.pdp.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 52, right: 16, top: 18, bottom: 38 },
    xAxis: { type: 'category', name: 'Delay (ns)', nameLocation: 'middle', nameGap: 26, data: delayNs },
    yAxis: { type: 'value', name: curve.relative ? 'Rel dB' : 'dB' },
    series: [{ type: 'line', showSymbol: false, smooth: false, data: powerDb, lineStyle: { color: '#2474d2', width: 2 }, areaStyle: { color: 'rgba(36,116,210,0.12)' } }],
    ...axisPointerOpt(),
  }, true);
}

function updateMapPanel() {
  const ds = AppState.dataset;
  if (!ds || !AppState.leafletMap || !window.L) return;
  const rx = ds.rxGps || [];
  const tx = ds.txGps;
  const cur = currentEntry()?.gps;
  if (!rx.length || !tx || !cur) return;
  Object.values(AppState.leafletLayers).forEach(l => l && AppState.leafletMap.removeLayer(l));
  const rxLatLng = rx.map(p => [Number(p.lat), Number(p.lon)]).filter(p => Number.isFinite(p[0]) && Number.isFinite(p[1]));
  const txLatLng = [Number(tx.lat), Number(tx.lon)];
  AppState.leafletLayers.rxLine = L.polyline(rxLatLng, { color: '#2474d2', weight: 3, opacity: 0.85 }).addTo(AppState.leafletMap);
  AppState.leafletLayers.tx = L.circleMarker(txLatLng, { radius: 7, color: '#9d2a2a', fillColor: '#e55353', fillOpacity: 0.95 }).addTo(AppState.leafletMap).bindTooltip('Tx');
  AppState.leafletLayers.rx = L.circleMarker([Number(cur.lat), Number(cur.lon)], { radius: 8, color: '#fff', weight: 3, fillColor: '#19a974', fillOpacity: 0.95 }).addTo(AppState.leafletMap).bindTooltip('当前 Rx');
  const bounds = L.latLngBounds([...rxLatLng, txLatLng]);
  if (bounds.isValid()) AppState.leafletMap.fitBounds(bounds.pad(0.18), { animate: false, maxZoom: 18 });
  setTimeout(() => AppState.leafletMap.invalidateSize(), 0);
}

function updateStatusBar() {
  const ds = AppState.dataset; if (!ds) return;
  const entry = currentEntry();
  const stats = entry?.payload?.stats || {};
  const summary = ds.meta?.summary || {};
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set('sbScene', (ds.meta?.name || AppState.datasetName || '--').replace(/\.bin$/i, ''));
  set('sbTxMode', ds.meta?.txMode === 'moving' ? 'Tx 运动' : 'Tx 静止');
  set('sbCarrier', document.getElementById('carrierHzInput').value ? `${document.getElementById('carrierHzInput').value} ${document.getElementById('carrierUnitSelect').value}` : '--');
  set('sbTime', `${Number(entry?.payload?.timeSec ?? 0).toFixed(2)} s`);
  set('sbDist', Number.isFinite(stats.distanceM) ? `${stats.distanceM.toFixed(2)} m` : '--');
  set('sbNmpc', summary.mpcCandidates ?? (ds.mpcScatter?.length ?? '--'));
  set('sbWindows', summary.nWindows ?? (ds.framePayloads?.length ?? '--'));
  set('sbDt', `${AppState.dtSec.toFixed(3)} s`);
}

// ---------------- 回放 ----------------
function togglePlayback() { AppState.playing ? stopPlayback() : startPlayback(); }
function startPlayback() {
  AppState.playing = true;
  document.getElementById('playPauseBtn').textContent = '暂停';
  AppState.timer = setInterval(() => {
    const maxV = Number(document.getElementById('frameSlider').max || 0);
    syncFrame(AppState.sliderValue >= maxV ? 0 : AppState.sliderValue + 1);
  }, 300);
}
function stopPlayback() {
  AppState.playing = false;
  const btn = document.getElementById('playPauseBtn'); if (btn) btn.textContent = '播放';
  clearInterval(AppState.timer);
}

function jumpToSeconds() {
  const sec = parseFloat(document.getElementById('jumpInput').value);
  if (!Number.isFinite(sec)) return;
  const { orderedFrames, map } = AppState.frameIndex;
  let best = 0, bestDiff = Infinity;
  orderedFrames.forEach((fid, i) => {
    const t = Number(map.get(fid)?.payload?.timeSec ?? 0);
    const d = Math.abs(t - sec);
    if (d < bestDiff) { bestDiff = d; best = i; }
  });
  syncFrame(Math.floor(best / AppState.decim));
}

// ---------------- 导出 ----------------
function exportChartPng(key) {
  const chart = AppState.charts[key];
  if (!chart) return;
  const url = chart.getDataURL({ pixelRatio: 2, backgroundColor: '#fff' });
  const a = document.createElement('a');
  a.href = url; a.download = `${(AppState.datasetName || 'chart').replace(/\.json$/, '')}_${key}.png`; a.click();
}

function exportPdpCsv() {
  const curve = currentEntry()?.payload?.pdpCurve;
  if (!curve) return;
  const rows = ['delayNs,powerDb', ...curve.delayNs.map((d, i) => `${d},${curve.powerDb[i]}`)];
  const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${(AppState.datasetName || 'pdp').replace(/\.json$/, '')}_frame${AppState.sliderValue}.csv`; a.click();
  URL.revokeObjectURL(a.href);
}

function rerenderAll() {
  if (AppState.uiState !== 'READY') return;
  updatePdpWaterfall(); updateDopplerWaterfall(); updateDelayTime(); updateDopplerTime(); updatePdpCurve();
}

// ---------------- 工具 ----------------
function markLoaded(id, loaded) { const el = document.getElementById(id); if (el) el.className = `load-dot ${loaded ? 'ok' : 'pending'}`; }
function numOrNull(id) { const v = parseFloat(document.getElementById(id)?.value); return Number.isFinite(v) ? v : null; }

window.addEventListener('DOMContentLoaded', async () => {
  initLayout();
  bindControls();
  updateTxModeUI();
  setUiState('IDLE');
  await checkBackend();
  await loadDatasetList();
  await loadDatasetFromApi('default');
});
