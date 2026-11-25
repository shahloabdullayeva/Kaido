const fuelNode = document.getElementById('fuel-map');

const FUEL_TONES = [
  { color: '#17703a', fillColor: '#5fbf7f' },
  { color: '#a35a00', fillColor: '#e8b552' },
  { color: '#b42318', fillColor: '#ef8a7f' },
];

if (fuelNode && typeof L !== 'undefined') {
  let stations = [];
  try { stations = JSON.parse(fuelNode.dataset.stations || '[]'); } catch (err) { stations = []; }
  const map = L.map(fuelNode, { scrollWheelZoom: true, wheelPxPerZoomLevel: 90 });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    referrerPolicy: 'strict-origin-when-cross-origin',
  }).addTo(map);
  const prices = stations.map((s) => s.avg).filter((v) => v !== null).sort((a, b) => a - b);
  const cut = (share) => prices[Math.min(prices.length - 1, Math.floor(prices.length * share))];
  const low = cut(1 / 3);
  const high = cut(2 / 3);
  const bounds = [];
  for (const station of stations) {
    let tone = FUEL_TONES[1];
    if (station.avg !== null && station.avg <= low) tone = FUEL_TONES[0];
    else if (station.avg !== null && station.avg >= high) tone = FUEL_TONES[2];
    const marker = L.circleMarker([station.lat, station.lon], {
      radius: Math.min(12, 5 + Math.sqrt(station.fills) * 1.5), weight: 2, fillOpacity: 0.85, ...tone,
    }).addTo(map);
    const label = station.name + (station.avg !== null ? ' — $' + station.avg.toFixed(3) + '/gal' : '');
    marker.bindTooltip(label);
    const box = document.createElement('div');
    box.className = 'map-popup';
    const title = document.createElement('div');
    title.className = 'map-popup-unit';
    title.textContent = station.name;
    box.append(title);
    for (const text of [station.where, station.avg !== null ? 'Avg paid $' + station.avg.toFixed(3) + '/gal' : null,
      station.fills + ' fill' + (station.fills === 1 ? '' : 's') + ' · ' + station.gallons.toLocaleString() + ' gal']) {
      if (!text) continue;
      const row = document.createElement('div');
      row.textContent = text;
      box.append(row);
    }
    marker.bindPopup(box);
    bounds.push([station.lat, station.lon]);
  }
  if (bounds.length) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 9 });
}
