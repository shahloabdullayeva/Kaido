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
let lastParams = {};
const progressHost = document.getElementById('shop-progress');
const form = trucks ? trucks.form : null;
const savedField = (name) => (form ? form.querySelector('input[name=' + name + ']') : null);

const setStatus = (text) => { if (status) status.textContent = text || ''; };

const unitLabel = () => {
  const option = trucks.selectedOptions[0];
  return option && option.value ? option.textContent.trim() : '';
};

// Where the last search looked, saved with the work order so reopening it looks there again.
const remembered = () => {
  const lat = savedField('shop_lat');
  const lon = savedField('shop_lon');
  if (!lat || !lon || !lat.value || !lon.value) return null;
  const where = savedField('shop_where');
  return { lat: lat.value, lon: lon.value, where: where ? where.value : '' };
};

const remember = (place) => {
  const fields = { shop_lat: place ? place.lat : '', shop_lon: place ? place.lon : '', shop_where: place ? place.where : '' };
  for (const [name, value] of Object.entries(fields)) {
    const input = savedField(name);
    if (input) input.value = value || '';
  }
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
  const row = document.createElement('div');
  row.className = 'shop-where';
  const input = document.createElement('input');
  input.type = 'text';
  input.maxLength = 1000;
  input.placeholder = 'Address, city and state, truck stop, or a Google Maps link — empty for the Samsara position';
  const saved = remembered();
  if (saved) input.value = saved.where || '';
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'btn';
  button.textContent = 'Find shops for ' + unitLabel();
  const go = () => {
    const asked = input.value.trim();
    const place = remembered();
    if (!asked) load(trucks.value, {});
    else if (place && asked === place.where) load(trucks.value, place);
    else load(trucks.value, { q: asked });
  };
  button.addEventListener('click', go);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); go(); }
  });
  row.append(input, button);
  const note = document.createElement('p');
  note.className = 'subtle';
  note.textContent = saved
    ? 'This work order last looked near the place above. Clear the box to start from the Samsara position.'
    : 'Leave the box empty to start from the last position Samsara reported, or type where the truck is.';
  wrap.append(row, note);
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
  const params = lastParams;
  again.addEventListener('click', () => load(trucks.value, params));
  const wrap = document.createElement('div');
  wrap.className = 'pad';
  wrap.append(again);
  body.append(line, wrap);
};

const pinStyle = (pin) => {
  if (pin.saved) return { color: '#1d4ed8', fillColor: '#60a5fa' };
  if (pin.open === 'open') return { color: '#006600', fillColor: '#66aa66' };
  if (pin.open === 'closed') return { color: '#cc0000', fillColor: '#dd8888' };
  return { color: '#996600', fillColor: '#ccaa66' };
};

const popupFor = (pin) => {
  const box = document.createElement('div');
  box.className = 'shop-popup';
  const name = document.createElement('strong');
  name.textContent = pin.name + (pin.saved ? ' (saved)' : '');
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

// Two map engines behind one shape: Leaflet with OpenStreetMap tiles, or Google Maps when the
// shops came from Google (Google's terms require its places to be shown on a Google map).
const leafletMap = (node) => {
  const view = L.map(node, { scrollWheelZoom: false });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    referrerPolicy: 'strict-origin-when-cross-origin',
  }).addTo(view);
  return {
    addOrigin(lat, lon, label) { L.marker([lat, lon]).addTo(view).bindPopup(label); },
    addPin(pin, onClick) {
      const marker = L.circleMarker([pin.lat, pin.lon], {
        radius: pin.saved ? 8 : 6, weight: 2, fillOpacity: 0.85, ...pinStyle(pin),
      }).addTo(view);
      marker.bindPopup(() => popupFor(pin));
      marker.on('click', onClick);
      return {
        setActive(on) {
          marker.setRadius(on ? 12 : (pin.saved ? 8 : 6));
          marker.setStyle({ weight: on ? 4 : 2 });
          if (on) marker.bringToFront();
        },
        openPopup() { marker.setPopupContent(popupFor(pin)); marker.openPopup(); },
        refresh() { if (marker.isPopupOpen()) marker.setPopupContent(popupFor(pin)); },
      };
    },
    fit(points) { view.fitBounds(points, { padding: [24, 24], maxZoom: 11 }); },
    overview() { view.setView([39.5, -98.35], 4); },
    focus(lat, lon, then) {
      view.flyTo([lat, lon], 15, { duration: 0.6 });
      view.once('moveend', then);
    },
    onClick(handler) { view.on('click', (event) => handler(event.latlng.lat, event.latlng.lng)); },
    remove() { view.remove(); },
  };
};

let googleReady = null;
const loadGoogle = (key) => {
  if (!googleReady) {
    googleReady = new Promise((resolve, reject) => {
      window.kaidoMapsReady = resolve;
      const script = document.createElement('script');
      script.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(key)
        + '&loading=async&callback=kaidoMapsReady&v=weekly';
      script.async = true;
      script.onerror = () => { googleReady = null; reject(new Error('Google Maps did not load')); };
      document.head.append(script);
    });
  }
  return googleReady;
};

const googleMap = async (node, key) => {
  await loadGoogle(key);
  const { Map, InfoWindow } = await google.maps.importLibrary('maps');
  const { Marker } = await google.maps.importLibrary('marker');
  const view = new Map(node, {
    center: { lat: 39.5, lng: -98.35 }, zoom: 4, gestureHandling: 'cooperative',
    clickableIcons: false, mapTypeControl: false, streetViewControl: false,
  });
  const info = new InfoWindow();
  let showing = null;
  info.addListener('closeclick', () => { showing = null; });
  const dot = (pin, on) => {
    const style = pinStyle(pin);
    return {
      path: google.maps.SymbolPath.CIRCLE, scale: on ? 11 : (pin.saved ? 8 : 6),
      fillColor: style.fillColor, fillOpacity: 0.9, strokeColor: style.color, strokeWeight: on ? 4 : 2,
    };
  };
  return {
    addOrigin(lat, lon, label) {
      const marker = new Marker({ position: { lat, lng: lon }, map: view, title: label, zIndex: 1000 });
      marker.addListener('click', () => { showing = null; info.setContent(label); info.open({ anchor: marker, map: view }); });
    },
    addPin(pin, onClick) {
      const marker = new Marker({ position: { lat: pin.lat, lng: pin.lon }, map: view, icon: dot(pin, false), title: pin.name });
      const handle = {
        setActive(on) { marker.setIcon(dot(pin, on)); marker.setZIndex(on ? 999 : null); },
        openPopup() { showing = handle; info.setContent(popupFor(pin)); info.open({ anchor: marker, map: view }); },
        refresh() { if (showing === handle) info.setContent(popupFor(pin)); },
      };
      marker.addListener('click', () => { onClick(); handle.openPopup(); });
      return handle;
    },
    fit(points) {
      const bounds = new google.maps.LatLngBounds();
      points.forEach(([lat, lon]) => bounds.extend({ lat, lng: lon }));
      view.fitBounds(bounds, 24);
      google.maps.event.addListenerOnce(view, 'idle', () => { if (view.getZoom() > 11) view.setZoom(11); });
    },
    overview() {},
    focus(lat, lon, then) {
      view.panTo({ lat, lng: lon });
      view.setZoom(15);
      google.maps.event.addListenerOnce(view, 'idle', then);
    },
    onClick(handler) { view.addListener('click', (event) => handler(event.latLng.lat(), event.latLng.lng())); },
    remove() { node.textContent = ''; },
  };
};

const highlight = (index) => {
  markers.forEach((entry, i) => { if (entry) entry.handle.setActive(i === index); });
  for (const row of body.querySelectorAll('.shop-list li')) {
    row.classList.toggle('active', Number(row.dataset.shop) - 1 === index);
  }
};

const showShop = (index) => {
  const entry = markers[index];
  if (!map || !entry) return;
  highlight(index);
  map.focus(entry.pin.lat, entry.pin.lon, () => entry.handle.openPopup());
  document.getElementById('shop-map').scrollIntoView({ block: 'center', behavior: 'smooth' });
};

const drawMap = async (run) => {
  const node = document.getElementById('shop-map');
  if (!node) return;
  let view = null;
  if (node.dataset.map === 'google' && node.dataset.key) {
    try {
      view = await googleMap(node, node.dataset.key);
    } catch (err) {
      node.textContent = 'The Google map did not load (' + err.message + '). The list below still works.';
      node.classList.add('empty');
      return;
    }
  } else if (typeof L !== 'undefined') {
    view = leafletMap(node);
  }
  if (!view) return;
  if (run !== searchRun) { view.remove(); return; }
  map = view;
  const lat = parseFloat(node.dataset.lat);
  const lon = parseFloat(node.dataset.lon);
  if (isFinite(lat) && isFinite(lon)) {
    const points = [[lat, lon]];
    map.addOrigin(lat, lon, node.dataset.label || 'Here');
    let pins = [];
    try { pins = JSON.parse(node.dataset.shops || '[]'); } catch (err) { pins = []; }
    pins.forEach((pin, index) => {
      markers[index] = { pin, handle: map.addPin(pin, () => highlight(index)) };
      points.push([pin.lat, pin.lon]);
    });
    map.fit(points);
  } else {
    map.overview();
  }
  map.onClick((pickedLat, pickedLon) => {
    load(trucks.value, { lat: pickedLat.toFixed(5), lon: pickedLon.toFixed(5) });
  });
};

const rememberOrigin = () => {
  const node = document.getElementById('shop-map');
  if (!node || !node.dataset.kind) return;
  if (node.dataset.kind === 'samsara') { remember(null); return; }
  remember({
    lat: Number(node.dataset.lat).toFixed(5),
    lon: Number(node.dataset.lon).toFixed(5),
    where: node.dataset.where || '',
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
  const home = body.querySelector('[data-shop-samsara]');
  if (home) home.addEventListener('click', () => load(trucks.value, {}));
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
    entry.handle.refresh();
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
  if (params === undefined) params = remembered() || {};
  lastParams = params;
  const run = ++searchRun;
  dropMap();
  setStatus('');
  body.textContent = '';
  const meter = progressHost ? progressBar(progressHost) : { stage() {}, finish() {}, stop() {} };
  meter.stage(0, 48, 'Looking up what is nearby');
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
  rememberOrigin();
  wireVendorPicks();
  wireSearch();
  drawMap(run);
  followUp(run, truckId, query, meter);
};

const findNow = new URLSearchParams(window.location.search).has('find') || (panel && panel.hasAttribute('data-find'));

const refreshShops = () => {
  if (!realTruck()) { dropMap(); panel.hidden = true; return; }
  if (isOil() || findNow) { panel.hidden = false; load(trucks.value); } else askFirst();
};

if (panel && body && trucks) {
  trucks.addEventListener('change', () => { remember(null); refreshShops(); loadOil(); });
  if (kindSelect) {
    kindSelect.addEventListener('change', () => {
      loadOil();
      if (isOil() && realTruck() && !map) { panel.hidden = false; load(trucks.value); }
    });
  }
  if (realTruck()) { refreshShops(); loadOil(); }
}
