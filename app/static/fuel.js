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

const suggestNode = document.getElementById('suggest-map');

if (suggestNode && typeof L !== 'undefined') {
  let data = {};
  try { data = JSON.parse(suggestNode.dataset.suggest || '{}'); } catch (err) { data = {}; }
  const map = L.map(suggestNode, { scrollWheelZoom: true, wheelPxPerZoomLevel: 90 });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    referrerPolicy: 'strict-origin-when-cross-origin',
  }).addTo(map);
  const pin = (text, kind, size) => L.divIcon({
    className: 'suggest-pin ' + kind,
    html: '<span>' + String(text).replace(/[&<>"']/g, (c) => '&#' + c.charCodeAt(0) + ';') + '</span>',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
  const popup = (title, lines, url) => {
    const box = document.createElement('div');
    box.className = 'map-popup';
    const head = document.createElement('div');
    head.className = 'map-popup-unit';
    head.textContent = title;
    box.append(head);
    for (const text of lines) {
      if (!text) continue;
      const row = document.createElement('div');
      row.textContent = text;
      box.append(row);
    }
    if (url) {
      const link = document.createElement('a');
      link.href = url; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Google Maps';
      box.append(link);
    }
    return box;
  };
  const bounds = [];
  if (data.route && data.route.length > 1) {
    L.polyline(data.route, { color: '#2a78d6', weight: 4, opacity: 0.6 }).addTo(map);
  }
  const stations = (data.stations || []).slice().reverse();
  for (const station of stations) {
    const size = station.best ? 32 : 24;
    const marker = L.marker([station.lat, station.lon], { icon: pin(String(station.rank), station.best ? 'best' : '', size), zIndexOffset: station.best ? 1000 : 0 });
    const price = station.net !== null ? '$' + station.net.toFixed(3) + '/gal' : 'no price';
    marker.bindTooltip((station.best ? 'Best: ' : '') + station.name + ' · ' + price)
      .bindPopup(popup(station.rank + '. ' + station.name, [station.where, station.miles + ' mi · ' + price], station.url))
      .addTo(map);
    bounds.push([station.lat, station.lon]);
  }
  if (data.truck) {
    const marker = L.marker([data.truck.lat, data.truck.lon], { icon: pin(data.truck.unit, 'truck', 28), zIndexOffset: 2000 });
    marker.bindTooltip('Unit ' + data.truck.unit).addTo(map);
    bounds.push([data.truck.lat, data.truck.lon]);
  }
  if (bounds.length > 1) map.fitBounds(bounds, { padding: [32, 32], maxZoom: 12 });
  else if (bounds.length) map.setView(bounds[0], 10);
}
