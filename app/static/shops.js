const panel = document.getElementById('shop-panel');
const body = document.getElementById('shop-body');
const status = document.getElementById('shop-status');
const trucks = document.querySelector('select[name=truck_id]');
const vendorInput = document.querySelector('input[name=vendor]');

let map = null;

const setStatus = (text) => { if (status) status.textContent = text || ''; };

const unitLabel = () => {
  const option = trucks.selectedOptions[0];
  return option && option.value ? option.textContent.trim() : '';
};

const dropMap = () => {
  if (map) { map.remove(); map = null; }
};

const askFirst = () => {
  dropMap();
  setStatus('');
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

const drawMap = () => {
  const node = document.getElementById('shop-map');
  if (!node || typeof L === 'undefined') return;
  const lat = parseFloat(node.dataset.lat);
  const lon = parseFloat(node.dataset.lon);
  const placed = isFinite(lat) && isFinite(lon);
  map = L.map(node, { scrollWheelZoom: false });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: '© OpenStreetMap contributors',
  }).addTo(map);
  if (placed) {
    const bounds = [[lat, lon]];
    L.marker([lat, lon]).addTo(map).bindPopup(node.dataset.label || 'Here');
    let pins = [];
    try { pins = JSON.parse(node.dataset.shops || '[]'); } catch (err) { pins = []; }
    for (const pin of pins) {
      const marker = L.circleMarker([pin.lat, pin.lon], {
        radius: 6, weight: 2, fillOpacity: 0.85, ...pinStyle(pin.open),
      }).addTo(map);
      const label = document.createElement('div');
      label.textContent = pin.name + ' — ' + pin.miles + ' mi';
      marker.bindPopup(label);
      bounds.push([pin.lat, pin.lon]);
    }
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

const load = async (truckId, params) => {
  if (!truckId) return;
  dropMap();
  setStatus('Looking…');
  body.textContent = '';
  const waiting = document.createElement('p');
  waiting.className = 'empty';
  waiting.textContent = 'Asking OpenStreetMap what is nearby. This can take a few seconds.';
  body.append(waiting);
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
    setStatus('');
    failed('Could not load shops — ' + err.message + '.');
    return;
  }
  setStatus('');
  body.innerHTML = markup;
  drawMap();
  wireVendorPicks();
  wireSearch();
};

if (panel && body && trucks) {
  trucks.addEventListener('change', () => {
    if (trucks.value) askFirst(); else { dropMap(); panel.hidden = true; }
  });
  if (trucks.value) askFirst();
}
