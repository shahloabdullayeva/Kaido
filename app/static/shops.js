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
  button.textContent = 'Find shops near ' + unitLabel();
  button.addEventListener('click', () => load(trucks.value));
  const note = document.createElement('p');
  note.className = 'subtle';
  note.textContent = 'Uses the last position Samsara reported for this truck.';
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
  if (!isFinite(lat) || !isFinite(lon)) return;
  map = L.map(node, { scrollWheelZoom: false });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: '© OpenStreetMap contributors',
  }).addTo(map);
  const bounds = [[lat, lon]];
  L.marker([lat, lon]).addTo(map).bindPopup(node.dataset.label || 'Truck');
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

const load = async (truckId) => {
  if (!truckId) return;
  dropMap();
  setStatus('Looking…');
  body.textContent = '';
  const waiting = document.createElement('p');
  waiting.className = 'empty';
  waiting.textContent = 'Asking OpenStreetMap what is near the truck. This can take a few seconds.';
  body.append(waiting);
  let markup = '';
  try {
    const response = await fetch('/maintenance/shops/' + encodeURIComponent(truckId), {
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
};

if (panel && body && trucks) {
  trucks.addEventListener('change', () => {
    if (trucks.value) askFirst(); else { dropMap(); panel.hidden = true; }
  });
  if (trucks.value) askFirst();
}
