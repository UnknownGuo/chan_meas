// ECharts 优先从 CDN 加载；如果离线或 CDN 不可达，启用一个轻量 canvas fallback，
// 保证本地工程调试时页面仍然能显示图表占位/基础曲线，而不是整页报错。
if (!window.echarts) {
  window.echarts = {
    init(container) {
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(320, container.clientWidth || 640);
      canvas.height = Math.max(180, container.clientHeight || 260);
      canvas.style.width = '100%';
      canvas.style.height = '100%';
      container.innerHTML = '';
      container.appendChild(canvas);
      const chart = {
        canvas,
        option: null,
        setOption(option) { this.option = option; drawFallbackChart(canvas, option); },
        resize() {
          canvas.width = Math.max(320, container.clientWidth || 640);
          canvas.height = Math.max(180, container.clientHeight || 260);
          if (this.option) drawFallbackChart(canvas, this.option);
        }
      };
      return chart;
    }
  };
}

function drawFallbackChart(canvas, option) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#f8fbff';
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = '#d8e2ee';
  ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
  ctx.fillStyle = '#66788a';
  ctx.font = '13px sans-serif';
  ctx.fillText('离线图表 fallback（CDN ECharts 未加载）', 14, 22);
  const series = option?.series?.[0] || {};
  const data = series.data || [];
  if (!data.length) return;
  const plot = { x: 42, y: 36, w: w - 58, h: h - 55 };
  if (series.type === 'heatmap') {
    const maxX = Math.max(...data.map(d => d[0]), 1), maxY = Math.max(...data.map(d => d[1]), 1);
    data.forEach(d => {
      const v = Number(d[2]);
      const t = Math.max(0, Math.min(1, (v + 110) / 110));
      ctx.fillStyle = `rgb(${Math.round(30 + 220 * t)}, ${Math.round(80 + 120 * t)}, ${Math.round(150 - 80 * t)})`;
      ctx.fillRect(plot.x + d[0] / maxX * plot.w, plot.y + d[1] / maxY * plot.h, Math.max(1, plot.w / (maxX + 1)), Math.max(1, plot.h / (maxY + 1)));
    });
  } else if (series.type === 'scatter') {
    const xs = data.map(d => Number(d[0])), ys = data.map(d => Number(d[1]));
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    ctx.fillStyle = '#2474d2';
    data.forEach(d => {
      const x = plot.x + (Number(d[0]) - minX) / Math.max(maxX - minX, 1e-9) * plot.w;
      const y = plot.y + plot.h - (Number(d[1]) - minY) / Math.max(maxY - minY, 1e-9) * plot.h;
      ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill();
    });
  } else if (series.type === 'line') {
    const vals = data.map(Number); const min = Math.min(...vals), max = Math.max(...vals);
    ctx.strokeStyle = '#2474d2'; ctx.lineWidth = 2; ctx.beginPath();
    vals.forEach((v, i) => {
      const x = plot.x + i / Math.max(vals.length - 1, 1) * plot.w;
      const y = plot.y + plot.h - (v - min) / Math.max(max - min, 1e-9) * plot.h;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }); ctx.stroke();
  } else if (series.type === 'bar') {
    const vals = data.map(Number); const max = Math.max(...vals, 1);
    ctx.fillStyle = '#2474d2';
    vals.forEach((v, i) => ctx.fillRect(plot.x + i * plot.w / vals.length, plot.y + plot.h - v / max * plot.h, plot.w / vals.length * 0.72, v / max * plot.h));
  }
}

const AppState = {
  dataset: null,
  currentFrame: 0,
  playing: false,
  timer: null,
  charts: {},
  dpsdCache: new Map(),
  dpsdRequestToken: 0,
  datasetName: null,
  leafletMap: null,
  leafletLayers: {},
  selectedFileRole: null,
};
window.AppState = AppState;

function initLayout() {
  AppState.charts.cir = echarts.init(document.getElementById('cirWaterfallChart'));
  AppState.charts.dpsd = echarts.init(document.getElementById('dpsdChart'));
  AppState.charts.pdp = echarts.init(document.getElementById('pdpChart'));
  initLeafletMap();
  window.addEventListener('resize', () => {
    Object.values(AppState.charts).forEach(chart => chart.resize());
    if (AppState.leafletMap) AppState.leafletMap.invalidateSize();
  });
}

function initLeafletMap() {
  if (!window.L || AppState.leafletMap) return;
  const el = document.getElementById('mapLeaflet');
  if (!el) return;
  AppState.leafletMap = L.map(el, { preferCanvas: true, zoomControl: true });
  L.tileLayer('/tiles/base/{z}/{x}/{y}.jpg', {
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri, OpenStreetMap contributors',
  }).addTo(AppState.leafletMap);
  AppState.leafletMap.setView([40.3032, 115.7719], 17);
}

function bindControls() {
  document.getElementById('loadDefaultBtn').addEventListener('click', () => loadDatasetFromApi('default'));
  document.getElementById('datasetSelect').addEventListener('change', event => loadDatasetFromApi(event.target.value));
  document.getElementById('frameSlider').addEventListener('input', event => syncFrame(Number(event.target.value)));
  document.getElementById('playPauseBtn').addEventListener('click', togglePlayback);
  document.getElementById('prevFrameBtn').addEventListener('click', () => syncFrame(AppState.currentFrame - 1));
  document.getElementById('nextFrameBtn').addEventListener('click', () => syncFrame(AppState.currentFrame + 1));
  document.getElementById('showTrackLines').addEventListener('change', updateMapPanel);
  document.getElementById('sceneSelect').addEventListener('change', updateOverview);
  document.querySelectorAll('input[name="txMode"], #applyCalibration').forEach(el => el.addEventListener('change', updateOverview));

  const hiddenFileInput = document.getElementById('hiddenFileInput');
  hiddenFileInput.addEventListener('change', event => {
    const file = event.target.files[0];
    if (!file) return;
    if (AppState.selectedFileRole === 'rx') loadRxData(file);
    if (AppState.selectedFileRole === 'calibration') loadCalibrationData(file);
    if (AppState.selectedFileRole === 'txgps') loadTxGpsData(file);
    hiddenFileInput.value = '';
  });
  document.getElementById('rxChooseBtn').addEventListener('click', () => chooseLocalFile('rx'));
  document.getElementById('calChooseBtn').addEventListener('click', () => chooseLocalFile('calibration'));
  document.getElementById('txGpsChooseBtn').addEventListener('click', () => chooseLocalFile('txgps'));
}

async function loadDatasetList() {
  const response = await fetch('/api/datasets');
  const payload = await response.json();
  const select = document.getElementById('datasetSelect');
  select.innerHTML = '';
  payload.datasets.forEach(name => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    if (name === payload.default) option.selected = true;
    select.appendChild(option);
  });
}

async function checkBackend() {
  const status = document.getElementById('backendStatus');
  try {
    const response = await fetch('/api/health');
    const payload = await response.json();
    status.textContent = `后端正常 · ${payload.datasetCount} 个数据集`;
    status.className = 'status-pill ok';
  } catch (error) {
    status.textContent = '后端不可用，使用 mock 数据';
    status.className = 'status-pill warning';
    loadMockData();
  }
}

async function loadDatasetFromApi(name = 'default') {
  const response = await fetch(`/api/datasets/${encodeURIComponent(name)}`);
  if (!response.ok) throw new Error(`dataset load failed: ${response.status}`);
  const dataset = await response.json();
  setDataset(dataset, name);
}

function loadMockData() {
  const frames = 120;
  const delayNs = Array.from({ length: 64 }, (_, i) => i * 20);
  const timeSec = Array.from({ length: frames }, (_, i) => i / 100);
  const powerDb = timeSec.map((_, f) => delayNs.map((_, d) => -80 + 42 * Math.exp(-Math.pow(d - (12 + f % 30), 2) / 90)));
  const rxGps = timeSec.map((t, i) => ({ frame: i, timeSec: t, lat: 40.30316 + i * 1e-7, lon: 115.77190 + Math.sin(i / 15) * 3e-6, alt: 565 }));
  const frameStats = timeSec.map((t, i) => ({ frame: i, timeSec: t, distanceM: 8 + i * 0.05, peakPowerDb: -35 + Math.sin(i / 7), peakDelayNs: 240 + Math.sin(i / 8) * 60, meanPowerDb: -78, rmsDelayNs: 36, pathCount: 3 }));
  const mpcScatter = frameStats.flatMap(s => [0, 1, 2].map(p => ({ frame: s.frame, timeSec: s.timeSec, pathId: p + 1, delayNs: s.peakDelayNs + p * 70, dopplerHz: Math.sin(s.frame / 12 + p) * 18, powerDb: s.peakPowerDb - p * 6 })));
  setDataset({
    meta: { name: 'mock', frameRateHz: 100, numFrames: frames, bandwidthHz: 50e6, txMode: 'static' },
    txGps: { lat: 40.303232, lon: 115.771857, alt: 561.41, source: 'mock' },
    rxGps, frameStats,
    framePayloads: frameStats.map(s => ({ frame: s.frame, stats: s, pdpCurve: { frame: s.frame, delayNs, powerDb: powerDb[s.frame], relative: false }, powerDistribution: [] })),
    cirWaterfall: { delayNs, timeSec, powerDb },
    dopplerDelay: { delayNs, dopplerHz: Array.from({ length: 48 }, (_, i) => -50 + i * 100 / 47), powerDb: Array.from({ length: 48 }, (_, r) => delayNs.map((_, c) => -90 + 20 * Math.exp(-Math.pow(c - 15, 2) / 60) * Math.exp(-Math.pow(r - 25, 2) / 30))) },
    mpcScatter,
    jointDelayDoppler: { tracks: mpcScatter },
  }, 'mock');
}

function setDataset(dataset, sourceName) {
  AppState.dataset = dataset;
  AppState.datasetName = sourceName === 'default' ? (document.getElementById('datasetSelect').value || sourceName) : sourceName;
  AppState.dpsdCache = new Map();
  AppState.currentFrame = 0;
  document.getElementById('datasetStatus').textContent = '数据已加载';
  document.getElementById('datasetStatus').className = 'status-pill ok';
  document.getElementById('rxPath').value = dataset.meta?.name || sourceName;
  document.getElementById('txGpsPath').value = dataset.txGps?.source || 'dataset.txGps';
  markLoaded('rxLoadState', true);
  markLoaded('txGpsLoadState', true);
  const maxFrame = Math.max(0, Number(dataset.meta?.numFrames || dataset.frameStats?.length || 1) - 1);
  const slider = document.getElementById('frameSlider');
  slider.max = String(maxFrame);
  slider.value = '0';
  updateCIRPlot();
  updateDPSDPlot();
  updateMusicPlot();
  syncFrame(0);
}

function chooseLocalFile(role) {
  AppState.selectedFileRole = role;
  document.getElementById('hiddenFileInput').click();
}

// 后续真实接线点：这里可改成上传 .bin 到 FastAPI，再调用 Python 解析流水线。
async function loadRxData(file) {
  document.getElementById('rxPath').value = file.name;
  markLoaded('rxLoadState', true);
  if (file.name.endsWith('.json')) {
    const dataset = JSON.parse(await file.text());
    setDataset(dataset, file.name);
  }
}

function loadCalibrationData(file) {
  document.getElementById('calPath').value = file.name;
  markLoaded('calLoadState', true);
  updateOverview();
}

function loadTxGpsData(file) {
  document.getElementById('txGpsPath').value = file.name;
  markLoaded('txGpsLoadState', true);
  updateOverview();
}

function markLoaded(id, loaded) {
  document.getElementById(id).className = `load-dot ${loaded ? 'ok' : 'pending'}`;
}

function syncFrame(frameIndex) {
  if (!AppState.dataset) return;
  const maxFrame = Number(document.getElementById('frameSlider').max || 0);
  AppState.currentFrame = Math.max(0, Math.min(maxFrame, frameIndex));
  document.getElementById('frameSlider').value = String(AppState.currentFrame);
  updatePlaybackLabels();
  updateOverview();
  updateMapPanel();
  updatePDPPlot();
  updateStatsPanel();
}

function updatePlaybackLabels() {
  const ds = AppState.dataset;
  const stats = frameStat();
  const total = Number(ds.meta?.numFrames || ds.frameStats?.length || 1);
  const frameRate = Number(ds.meta?.frameRateHz || 100);
  const rawFrameRate = Number(ds.meta?.rawFrameRateHz || frameRate);
  document.getElementById('currentFrameLabel').textContent = `${AppState.currentFrame} / ${Math.max(0, total - 1)}`;
  document.getElementById('currentTimeLabel').textContent = `${Number(stats?.timeSec ?? AppState.currentFrame / frameRate).toFixed(3)} s`;
  document.getElementById('durationLabel').textContent = `${((total - 1) / frameRate).toFixed(3)} s`;
  document.getElementById('frameRateLabel').textContent = `${rawFrameRate.toFixed(1)} Hz`;
}

function togglePlayback() {
  AppState.playing = !AppState.playing;
  document.getElementById('playPauseBtn').textContent = AppState.playing ? '暂停' : '播放';
  if (AppState.playing) {
    AppState.timer = setInterval(() => {
      const maxFrame = Number(document.getElementById('frameSlider').max || 0);
      syncFrame(AppState.currentFrame >= maxFrame ? 0 : AppState.currentFrame + 1);
    }, 120);
  } else {
    clearInterval(AppState.timer);
  }
}

function updateOverview() {
  const overview = document.getElementById('overviewList');
  if (!AppState.dataset || !overview) return;
  const s = frameStat();
  const scene = document.getElementById('sceneSelect').selectedOptions[0].textContent;
  const txMode = document.querySelector('input[name="txMode"]:checked').value === 'static' ? 'Tx 静止' : 'Tx 运动';
  const items = [
    ['📦', 'Rx 数据状态', document.getElementById('rxPath').value || '未加载'],
    ['🧰', '校准数据状态', document.getElementById('calPath').value || '未加载'],
    ['📍', 'Tx GPS 数据状态', document.getElementById('txGpsPath').value || '未加载'],
    ['🛣️', '场景', scene],
    ['📡', 'Tx 模式', txMode],
    ['⏱️', '当前时间', `${Number(s?.timeSec || 0).toFixed(3)} s`],
    ['📏', 'Tx-Rx 距离', `${Number(s?.distanceM || 0).toFixed(2)} m`],
    ['🧪', '校准开关', document.getElementById('applyCalibration').checked ? '启用' : '关闭'],
  ];
  overview.innerHTML = items.map(([icon, label, value]) => `<li><div>${icon}</div><div><strong>${label}</strong><span>${escapeHtml(String(value))}</span></div></li>`).join('');
}

function updateMapPanel() {
  if (!AppState.dataset) return;
  const svg = document.getElementById('mapSvg');
  const panel = document.getElementById('mapPanel');
  const rx = AppState.dataset.rxGps || [];
  const tx = AppState.dataset.txGps;
  if (!rx.length || !tx) return;
  const cur = rx[Math.min(AppState.currentFrame, rx.length - 1)];
  const showLine = document.getElementById('showTrackLines').checked;
  if (AppState.leafletMap && window.L) {
    panel.classList.add('leaflet-active');
    Object.values(AppState.leafletLayers).forEach(layer => layer && AppState.leafletMap.removeLayer(layer));
    const rxLatLng = rx.map(p => [Number(p.lat), Number(p.lon)]).filter(p => Number.isFinite(p[0]) && Number.isFinite(p[1]));
    const txLatLng = [Number(tx.lat), Number(tx.lon)];
    if (showLine && rxLatLng.length > 1) AppState.leafletLayers.rxLine = L.polyline(rxLatLng, { color: '#2474d2', weight: 4, opacity: 0.85 }).addTo(AppState.leafletMap);
    AppState.leafletLayers.tx = L.circleMarker(txLatLng, { radius: 7, color: '#9d2a2a', fillColor: '#e55353', fillOpacity: 0.95 }).addTo(AppState.leafletMap).bindTooltip('Tx');
    AppState.leafletLayers.rx = L.circleMarker([Number(cur.lat), Number(cur.lon)], { radius: 8, color: '#ffffff', weight: 3, fillColor: '#19a974', fillOpacity: 0.95 }).addTo(AppState.leafletMap).bindTooltip(`Rx F${AppState.currentFrame}`);
    const bounds = L.latLngBounds([...rxLatLng, txLatLng]);
    if (bounds.isValid()) AppState.leafletMap.fitBounds(bounds.pad(0.18), { animate: false, maxZoom: 18 });
    setTimeout(() => AppState.leafletMap.invalidateSize(), 0);
    return;
  }
  const points = rx.map(p => ({ lat: Number(p.lat), lon: Number(p.lon) })).concat([{ lat: Number(tx.lat), lon: Number(tx.lon) }]);
  const lats = points.map(p => p.lat), lons = points.map(p => p.lon);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats), minLon = Math.min(...lons), maxLon = Math.max(...lons);
  const project = p => {
    const x = 60 + ((Number(p.lon) - minLon) / Math.max(maxLon - minLon, 1e-9)) * 880;
    const y = 360 - ((Number(p.lat) - minLat) / Math.max(maxLat - minLat, 1e-9)) * 300;
    return [x, y];
  };
  const path = rx.map(project).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const [txX, txY] = project(tx);
  const [cx, cy] = project(cur);
  svg.innerHTML = `
    <text x="34" y="38" fill="#456" font-size="16">GPS Track</text>
    ${showLine ? `<polyline points="${path}" fill="none" stroke="#2474d2" stroke-width="4" stroke-linejoin="round" opacity="0.88"/>` : ''}
    <circle cx="${txX}" cy="${txY}" r="9" fill="#e55353"/><text x="${txX + 12}" y="${txY - 8}" fill="#9d2a2a" font-size="14">Tx</text>
    <circle cx="${cx}" cy="${cy}" r="10" fill="#19a974" stroke="#fff" stroke-width="3"/><text x="${cx + 13}" y="${cy + 5}" fill="#116c4e" font-size="14">Rx F${AppState.currentFrame}</text>
  `;
}

function updateCIRPlot() {
  const wf = AppState.dataset?.cirWaterfall;
  if (!wf) return;
  AppState.charts.cir.setOption({
    tooltip: { position: 'top' },
    grid: { left: 48, right: 18, top: 22, bottom: 40 },
    xAxis: { type: 'category', name: 'Delay/ns', data: wf.delayNs, axisLabel: { interval: Math.ceil(wf.delayNs.length / 6) } },
    yAxis: { type: 'category', name: 'Time/s', data: wf.timeSec.map(v => Number(v).toFixed(2)), axisLabel: { interval: Math.ceil(wf.timeSec.length / 6) } },
    visualMap: { min: -100, max: 0, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#12365d', '#2474d2', '#f1c75b', '#e55353'] } },
    series: [{ type: 'heatmap', data: heatmapTriples(wf.powerDb), progressive: 8000 }]
  });
}

async function updateDPSDPlot() {
  let d = AppState.dataset?.dopplerDelay;
  const frame = AppState.currentFrame || 0;
  if (AppState.dataset?.meta?.dopplerDelaySidecar && AppState.datasetName) {
    const cacheKey = String(frame);
    if (AppState.dpsdCache.has(cacheKey)) {
      d = AppState.dpsdCache.get(cacheKey);
    } else {
      const token = ++AppState.dpsdRequestToken;
      try {
        const response = await fetch(`/api/datasets/${encodeURIComponent(AppState.datasetName)}/dpsd/${frame}`);
        if (response.ok) {
          d = await response.json();
          AppState.dpsdCache.set(cacheKey, d);
          if (token !== AppState.dpsdRequestToken) return;
        }
      } catch (error) {
        console.warn('DPSD sidecar fetch failed; using embedded fallback', error);
      }
    }
  }
  if (!d) return;
  const isDopplerTime = d.method === 'delay_averaged_doppler_time_fft';
  const xValues = isDopplerTime ? d.timeSec : (d.delayBins || d.delayNs || []);
  AppState.charts.dpsd.setOption({
    title: { text: '', left: 8, top: 0, textStyle: { fontSize: 12, color: '#456' } },
    tooltip: { position: 'top' },
    grid: { left: 54, right: 18, top: 28, bottom: 42 },
    xAxis: { type: 'category', name: isDopplerTime ? 'Time/s' : 'Delay Index', data: xValues.map(v => Number(v).toFixed(isDopplerTime ? 0 : 0)), axisLabel: { interval: Math.ceil(xValues.length / 7) } },
    yAxis: { type: 'category', name: 'Doppler/Hz', data: d.dopplerHz.map(v => Number(v).toFixed(1)), axisLabel: { interval: Math.ceil(d.dopplerHz.length / 6) } },
    visualMap: { min: -60, max: 0, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#00224e', '#004c99', '#00a6ca', '#f5d742', '#d7191c'] } },
    series: [{ type: 'heatmap', data: heatmapTriples(d.powerDb), progressive: 12000 }]
  }, true);
}

function updateMusicPlot() {
  const ds = AppState.dataset;
  const img = document.getElementById('mpcPng');
  if (!ds || !img) return;
  const rawName = ds.meta?.name || '';
  const stem = rawName.replace(/\.bin$/i, '');
  if (stem) {
    img.src = `/sage_outputs/figure4_style_0m_special_w20/${stem}/w20_separate_delay_time_power.png`;
    img.style.display = '';
  } else {
    img.style.display = 'none';
  }
}

function updateMusicTrackPlot() {
  // Kept for compatibility; updateMusicPlot now handles the PNG display.
  updateMusicPlot();
}

function updatePDPPlot() {
  const payload = framePayload();
  const curve = payload?.pdpCurve;
  if (!curve) return;
  AppState.charts.pdp.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 16, top: 20, bottom: 35 },
    xAxis: { type: 'category', name: 'Delay/ns', data: curve.delayNs },
    yAxis: { type: 'value', name: curve.relative ? 'Rel dB' : 'dB' },
    series: [{ type: 'line', showSymbol: false, smooth: true, data: curve.powerDb, lineStyle: { color: '#2474d2', width: 2 }, areaStyle: { color: 'rgba(36,116,210,0.12)' } }]
  });
}

function updateStatsPanel() {
  const s = frameStat() || {};
  const rows = [
    ['路径数', s.pathCount], ['最大功率', fmt(s.peakPowerDb, ' dB')], ['平均功率', fmt(s.meanPowerDb, ' dB')],
    ['峰值时延', fmt(s.peakDelayNs, ' ns')], ['均方根时延', fmt(s.rmsDelayNs, ' ns')], ['Tx-Rx 距离', fmt(s.distanceM, ' m')]
  ];
  document.querySelector('#statsTable tbody').innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v ?? '--'}</td></tr>`).join('');
}

function updatePowerDistribution() {
  const payload = framePayload();
  const dist = payload?.powerDistribution?.length ? payload.powerDistribution : buildDistribution(payload?.pdpCurve?.powerDb || []);
  AppState.charts.power.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 45, right: 14, top: 18, bottom: 35 },
    xAxis: { type: 'category', data: dist.map(d => d.label) },
    yAxis: { type: 'value', name: 'count' },
    series: [{ type: 'bar', data: dist.map(d => d.count), itemStyle: { color: '#2474d2' } }]
  });
}

function frameStat() { return AppState.dataset?.frameStats?.[Math.min(AppState.currentFrame, (AppState.dataset.frameStats?.length || 1) - 1)]; }
function framePayload() { return AppState.dataset?.framePayloads?.[Math.min(AppState.currentFrame, (AppState.dataset.framePayloads?.length || 1) - 1)]; }
function heatmapTriples(matrix) { return matrix.flatMap((row, y) => row.map((value, x) => [x, y, Number(value)])); }
function fmt(value, suffix) { return Number.isFinite(Number(value)) ? `${Number(value).toFixed(3)}${suffix}` : '--'; }
function escapeHtml(text) { return text.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function buildDistribution(values) {
  const bins = [['>-20', -20, Infinity], ['-20~-40', -40, -20], ['-40~-60', -60, -40], ['-60~-80', -80, -60], ['<-80', -Infinity, -80]];
  return bins.map(([label, lo, hi]) => ({ label, count: values.filter(v => Number(v) >= lo && Number(v) < hi).length }));
}

// 预留真实业务接口名，后续可被后端/WebSocket/pywebview 直接调用。
function renderMap(gpsData) { updateMapPanel(gpsData); }
function renderCIR(data, frame) { updateCIRPlot(data, frame); }
function renderDoppler(data, frame) { updateDPSDPlot(data, frame); }
function renderMPCScatter(data, frame) { updateMusicPlot(data, frame); }
function computeStatistics(frame) { return AppState.dataset?.frameStats?.[frame]; }

window.addEventListener('DOMContentLoaded', async () => {
  initLayout();
  bindControls();
  await checkBackend();
  await loadDatasetList();
  if (!AppState.dataset) await loadDatasetFromApi('default');
});
