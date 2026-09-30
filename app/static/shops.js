const panel = document.getElementById('shop-panel');
const body = document.getElementById('shop-body');
const status = document.getElementById('shop-status');
const trucks = document.querySelector('select[name=truck_id]');
const vendorInput = document.querySelector('input[name=vendor]');
const kindSelect = document.querySelector('select[name=kind]');
const oilPanel = document.getElementById('oil-panel');
const oilBody = document.getElementById('oil-body');
const notesField = document.querySelector('textarea[name=description]');
let oilFor = null;

const isOil = () => kindSelect && kindSelect.value === 'oil';
const realTruck = () => trucks && /^\d+$/.test(trucks.value);

const progressBar = (host) => {
  host.textContent = '';
  host.hidden = false;
  const track = document.createElement('div');
  track.className = 'progress-track';
  const fill = document.createElement('div');
  fill.className = 'progress-fill';
  track.append(fill);
  const text = document.createElement('div');
  text.className = 'progress-text';
  host.append(track, text);
  let shown = 0;
  let floor = 0;
  let ceiling = 0;
  let label = '';
  const paint = () => {
    fill.style.width = shown.toFixed(1) + '%';
    text.textContent = label + ' — ' + Math.floor(shown) + '%';
  };
  const timer = setInterval(() => {
    if (shown < ceiling) shown = Math.min(ceiling, shown + Math.max(0.15, (ceiling - shown) * 0.04));
    paint();
  }, 120);
  return {
    stage(from, to, words) {
      floor = from;
      ceiling = to;
      label = words;
      if (shown < floor) shown = floor;
      paint();
    },
    finish(words) {
      clearInterval(timer);
      shown = 100;
      label = words || 'Done';
      paint();
      setTimeout(() => { host.hidden = true; }, 1500);
    },
    stop() {
      clearInterval(timer);
      host.hidden = true;
    },
  };
};

const loadOil = async () => {
  if (!oilPanel || !oilBody) return;
  if (!isOil() || !realTruck()) { oilPanel.hidden = true; oilFor = null; return; }
  if (oilFor === trucks.value) { oilPanel.hidden = false; return; }
  oilFor = trucks.value;
  oilPanel.hidden = false;
  oilBody.textContent = '';
  const oilProgressHost = document.createElement('div');
  oilProgressHost.className = 'progress pad';
  oilBody.append(oilProgressHost);
  const oilProgress = progressBar(oilProgressHost);
  oilProgress.stage(0, 35, 'Reading the engine off the VIN');
  const toClaude = setTimeout(() => oilProgress.stage(35, 95, 'Claude is working out the oil'), 1200);
  try {
    const response = await fetch('/maintenance/oil/' + encodeURIComponent(oilFor), { credentials: 'same-origin' });
    if (!response.ok) throw new Error('the server answered ' + response.status);
    const html = await response.text();
    clearTimeout(toClaude);
    oilProgress.stop();
    oilBody.innerHTML = html;
    for (const button of oilBody.querySelectorAll('[data-oil-note]')) {
      button.addEventListener('click', () => {
        if (!notesField) return;
        const line = 'Oil: ' + button.dataset.oilNote;
        notesField.value = notesField.value ? notesField.value + '\n' + line : line;
        button.textContent = 'Added';
      });
    }
  } catch (err) {
    clearTimeout(toClaude);
    oilProgress.stop();
    oilFor = null;
    oilBody.textContent = '';
    const line = document.createElement('p');
    line.className = 'empty';
    line.textContent = 'Could not get an oil suggestion — ' + err.message + '.';
    oilBody.append(line);
  }
};

let map = null;
let markers = [];
let searchRun = 0;
const progressHost = document.getElementById('shop-progress');

const setStatus = (text) => { if (status) status.textContent = text || ''; };

const unitLabel = () => {
  const option = trucks.selectedOptions[0];
  return option && option.value ? option.textContent.trim() : '';
};

const dropMap = () => {
  if (map) { map.remove(); map = null; }
  markers = [];
};

const askFirst = () => {
  dropMap();
  setStatus('');
  if (progressHost) progressHost.hidden = true;
  body.textContent = '';
  const wrap = document.createElement('div');
  wrap.className = 'pad';
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'btn ghost';
  button.textContent = 'Find a shop for ' + unitLabel();
  button.addEventListener('click', () => load(trucks.value));
  const note = document.createElement('p');
  note.className = 'subtle';
  note.textContent = 'Starts from the last position Samsara reported. If there is none, type where the truck is.';
  wrap.append(button, note);
  body.append(wrap);
  panel.hidden = false;
};

const failed = (message) => {
  body.textContent = '';
  const line = document.createElement('p');
  line.className = 'empty';
  line.textContent = message;
  const again = document.createElement('button');
  again.type = 'button';
  again.className = 'btn ghost small';
  again.textContent = 'Try again';
  again.addEventListener('click', () => load(trucks.value));
  const wrap = document.createElement('div');
  wrap.className = 'pad';
  wrap.append(again);
  body.append(line, wrap);
};

const pinStyle = (state) => {
  if (state === 'open') return { color: '#006600', fillColor: '#66aa66' };
  if (state === 'closed') return { color: '#cc0000', fillColor: '#dd8888' };
  return { color: '#996600', fillColor: '#ccaa66' };
};

const popupFor = (pin) => {
  const box = document.createElement('div');
  box.className = 'shop-popup';
  const name = document.createElement('strong');
  name.textContent = pin.name;
  const facts = document.createElement('div');
  facts.textContent = pin.miles + ' mi' + (pin.hours ? ' · ' + pin.hours : '');
  const where = document.createElement('div');
  where.textContent = pin.address || 'Address not listed';
  const phone = document.createElement('div');
  phone.textContent = pin.phone ? pin.phone : 'No phone listed';
  const actions = document.createElement('div');
  actions.className = 'shop-actions';
  if (pin.dial) {
    const call = document.createElement('a');
    call.className = 'btn small';
    call.href = 'tel:' + pin.dial;
    call.textContent = 'Call';
    actions.append(call);
  }
  if (pin.maps) {
    const maps = document.createElement('a');
    maps.className = 'btn ghost small';
    maps.href = pin.maps;
    maps.target = '_blank';
    maps.rel = 'noopener noreferrer';
    maps.textContent = 'Google Maps';
    actions.append(maps);
  }
  box.append(name, facts, where, phone, actions);
  return box;
};

const highlight = (index) => {
  markers.forEach((entry, i) => {
    if (!entry) return;
    entry.marker.setRadius(i === index ? 12 : 6);
    entry.marker.setStyle({ weight: i === index ? 4 : 2 });
    if (i === index) entry.marker.bringToFront();
  });
  for (const row of body.querySelectorAll('.shop-list li')) {
    row.classList.toggle('active', Number(row.dataset.shop) - 1 === index);
  }
};

const showShop = (index) => {
  const entry = markers[index];
  if (!map || !entry) return;
  highlight(index);
  entry.marker.setPopupContent(popupFor(entry.pin));
  map.flyTo([entry.pin.lat, entry.pin.lon], 15, { duration: 0.6 });
  map.once('moveend', () => entry.marker.openPopup());
  document.getElementById('shop-map').scrollIntoView({ block: 'center', behavior: 'smooth' });
};

const drawMap = () => {
  const node = document.getElementById('shop-map');
  if (!node || typeof L === 'undefined') return;
  const lat = parseFloat(node.dataset.lat);
  const lon = parseFloat(node.dataset.lon);
  const placed = isFinite(lat) && isFinite(lon);
  map = L.map(node, { scrollWheelZoom: false });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    referrerPolicy: 'strict-origin-when-cross-origin',
  }).addTo(map);
  if (placed) {
    const bounds = [[lat, lon]];
    L.marker([lat, lon]).addTo(map).bindPopup(node.dataset.label || 'Here');
    let pins = [];
    try { pins = JSON.parse(node.dataset.shops || '[]'); } catch (err) { pins = []; }
    pins.forEach((pin, index) => {
      const marker = L.circleMarker([pin.lat, pin.lon], {
        radius: 6, weight: 2, fillOpacity: 0.85, ...pinStyle(pin.open),
      }).addTo(map);
      marker.bindPopup(() => popupFor(pin));
      marker.on('click', () => highlight(index));
      markers[index] = { marker, pin };
      bounds.push([pin.lat, pin.lon]);
    });
    map.fitBounds(bounds, { padding: [24, 24], maxZoom: 11 });
  } else {
    map.setView([39.5, -98.35], 4);
  }
  map.on('click', (event) => {
    load(trucks.value, {
      lat: event.latlng.lat.toFixed(5),
      lon: event.latlng.lng.toFixed(5),
    });
  });
};

const wireVendorPicks = () => {
  for (const button of body.querySelectorAll('[data-pick-vendor]')) {
    button.addEventListener('click', () => {
      if (!vendorInput) return;
      vendorInput.value = button.dataset.pickVendor;
      vendorInput.scrollIntoView({ block: 'center' });
      vendorInput.focus();
      setStatus('Vendor set to ' + button.dataset.pickVendor);
    });
  }
  for (const button of body.querySelectorAll('[data-show-shop]')) {
    button.addEventListener('click', () => showShop(Number(button.dataset.showShop) - 1));
  }
};

const wireSearch = () => {
  const input = body.querySelector('#shop-where');
  const button = body.querySelector('[data-shop-search]');
  if (!input || !button) return;
  const go = () => {
    const asked = input.value.trim();
    if (asked) load(trucks.value, { q: asked });
  };
  button.addEventListener('click', go);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); go(); }
  });
};

const getJson = async (url) => {
  const response = await fetch(url, { headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' });
  if (!response.ok) throw new Error('the server answered ' + response.status);
  return response.json();
};

const fillAdvice = (data) => {
  const pick = body.querySelector('#shop-pick');
  const aiState = body.querySelector('#shop-ai-state');
  if (data.state === 'ok') {
    if (pick && (data.pick || data.why)) {
      pick.textContent = '';
      if (data.pick) {
        const strong = document.createElement('strong');
        strong.textContent = 'Send it to ' + data.pick + '. ';
        pick.append(strong);
      }
      pick.append(document.createTextNode(data.why || ''));
      pick.hidden = false;
    }
    for (const [number, text] of Object.entries(data.notes || {})) {
      const note = body.querySelector('li[data-shop="' + number + '"] [data-note]');
      if (note && text) { note.textContent = text; note.hidden = false; }
    }
  } else if (aiState) {
    aiState.textContent = data.state === 'paused' ? "AI notes are paused — today's budget is spent. They come back tomorrow."
      : data.state === 'off' ? 'AI notes are off — no ANTHROPIC_API_KEY set.' : 'AI notes did not come back this time.';
  }
};

const fillAddress = (row, data) => {
  const index = Number(row.dataset.shop) - 1;
  const entry = markers[index];
  const spot = row.querySelector('[data-address]');
  if (spot) spot.textContent = data.address || (entry && entry.pin.address) || 'Address not listed — use Google Maps.';
  if (data.maps) {
    const link = row.querySelector('[data-maps]');
    if (link) link.href = data.maps;
  }
  if (entry) {
    if (data.address) entry.pin.address = data.address;
    if (data.maps) entry.pin.maps = data.maps;
    if (entry.marker.isPopupOpen()) entry.marker.setPopupContent(popupFor(entry.pin));
  }
};

const followUp = async (run, truckId, query, meter) => {
  const rows = [...body.querySelectorAll('.shop-list li[data-needs-address]')];
  const foot = body.querySelector('#shop-foot');
  const wantAi = foot && foot.dataset.ai === 'on' && body.querySelectorAll('.shop-list li').length > 0;
  const units = rows.length + (wantAi ? 3 : 0);
  if (!units) { meter.finish(body.querySelector('.shop-list') ? 'Shops found' : 'Done'); return; }
  let done = 0;
  let aiDone = !wantAi;
  let found = 0;
  const words = () => {
    const parts = [];
    if (!aiDone) parts.push('Claude is comparing the shops');
    if (found < rows.length) parts.push('finding addresses ' + found + ' of ' + rows.length);
    return parts.join(' · ') || 'Finishing';
  };
  const step = () => meter.stage(50 + 50 * done / units, Math.min(99, 50 + 50 * (done + (aiDone ? 1 : 3)) / units), words());
  step();
  const advice = wantAi ? getJson('/maintenance/shops/' + encodeURIComponent(truckId) + '/advice' + (query ? '?' + query : ''))
    .then((data) => { if (run === searchRun) fillAdvice(data); })
    .catch(() => { if (run === searchRun) fillAdvice({ state: 'none' }); })
    .finally(() => { aiDone = true; done += 3; if (run === searchRun) step(); }) : Promise.resolve();
  for (const row of rows) {
    if (run !== searchRun) return;
    const params = new URLSearchParams({ lat: row.dataset.lat, lon: row.dataset.lon, name: row.dataset.name });
    try {
      fillAddress(row, await getJson('/maintenance/shops/address?' + params.toString()));
    } catch (err) {
      fillAddress(row, { address: null });
    }
    found += 1;
    done += 1;
    if (run === searchRun) step();
  }
  await advice;
  if (run === searchRun) meter.finish('Done');
};

const load = async (truckId, params) => {
  if (!truckId) return;
  const run = ++searchRun;
  dropMap();
  setStatus('');
  body.textContent = '';
  const meter = progressHost ? progressBar(progressHost) : { stage() {}, finish() {}, stop() {} };
  meter.stage(0, 48, 'Asking OpenStreetMap what is nearby');
  const query = new URLSearchParams(params || {}).toString();
  let markup = '';
  try {
    const response = await fetch('/maintenance/shops/' + encodeURIComponent(truckId) + (query ? '?' + query : ''), {
      headers: { 'X-Requested-With': 'fetch' },
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error('the server answered ' + response.status);
    markup = await response.text();
  } catch (err) {
    if (run !== searchRun) return;
    meter.stop();
    failed('Could not load shops — ' + err.message + '.');
    return;
  }
  if (run !== searchRun) { meter.stop(); return; }
  body.innerHTML = markup;
  drawMap();
  wireVendorPicks();
  wireSearch();
  followUp(run, truckId, query, meter);
};

const refreshShops = () => {
  if (!realTruck()) { dropMap(); panel.hidden = true; return; }
  if (isOil()) { panel.hidden = false; load(trucks.value); } else askFirst();
};

if (panel && body && trucks) {
  trucks.addEventListener('change', () => { refreshShops(); loadOil(); });
  if (kindSelect) {
    kindSelect.addEventListener('change', () => {
      loadOil();
      if (isOil() && realTruck() && !map) { panel.hidden = false; load(trucks.value); }
    });
  }
  if (realTruck()) { refreshShops(); loadOil(); }
}
