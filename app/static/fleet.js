const node = document.getElementById('fleet-map');

const TONES = {
  bad: { color: '#cc0000', fillColor: '#dd8888' },
  warn: { color: '#996600', fillColor: '#ccaa66' },
  ok: { color: '#006600', fillColor: '#66aa66' },
};

const line = (parent, text, className) => {
  if (!text) return;
  const row = document.createElement('div');
  if (className) row.className = className;
  row.textContent = text;
  parent.append(row);
};

const popupFor = (truck) => {
  const box = document.createElement('div');
  box.className = 'map-popup';
  const title = document.createElement('div');
  title.className = 'map-popup-unit';
  title.textContent = truck.unit;
  box.append(title);
  line(box, truck.driver || 'No driver assigned', 'map-popup-driver');
  line(box, truck.truck);
  line(box, truck.where);
  line(box, truck.when ? 'Reported ' + truck.when + (truck.source ? ' by ' + truck.source : '') : null, 'subtle');
  line(box, truck.duty ? truck.duty + (truck.drive_left ? ' · ' + truck.drive_left + ' drive left' : '') + ' (Horizon ELD)' : null, 'subtle');
  line(box, truck.odometer, 'subtle');
  const flags = [];
  if (truck.breakdowns) flags.push(truck.breakdowns + ' open breakdown' + (truck.breakdowns > 1 ? 's' : ''));
  if (truck.faults) flags.push(truck.faults + ' active fault' + (truck.faults > 1 ? 's' : ''));
  if (truck.status && truck.status !== 'active') flags.push(truck.status);
  line(box, flags.join(' · '), 'map-popup-flags');
  const link = document.createElement('a');
  link.href = '/trucks/' + truck.id;
  link.textContent = 'Open this truck';
  box.append(link);
  return box;
};

if (node && typeof L !== 'undefined') {
  let trucks = [];
  try { trucks = JSON.parse(node.dataset.trucks || '[]'); } catch (err) { trucks = []; }
  const map = L.map(node, { scrollWheelZoom: false });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    referrerPolicy: 'strict-origin-when-cross-origin',
  }).addTo(map);
  const bounds = [];
  for (const truck of trucks) {
    const marker = L.circleMarker([truck.lat, truck.lon], {
      radius: 7, weight: 2, fillOpacity: 0.85, ...(TONES[truck.tone] || TONES.ok),
    }).addTo(map);
    marker.bindTooltip(truck.unit + (truck.driver ? ' — ' + truck.driver : ''));
    marker.bindPopup(popupFor(truck));
    bounds.push([truck.lat, truck.lon]);
  }
  if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 9 });
  else map.setView([39.5, -98.35], 4);
}
