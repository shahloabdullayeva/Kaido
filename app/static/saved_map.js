const savedNode = document.getElementById('saved-map');

const textLine = (parent, text, className) => {
  if (!text) return;
  const row = document.createElement('div');
  if (className) row.className = className;
  row.textContent = text;
  parent.append(row);
};

const shopPopup = (shop) => {
  const box = document.createElement('div');
  box.className = 'map-popup';
  textLine(box, shop.name, 'map-popup-unit');
  textLine(box, shop.address);
  textLine(box, shop.phone);
  textLine(box, shop.note, 'shop-note');
  textLine(box, shop.by ? 'Saved by ' + shop.by : null, 'subtle');
  const link = document.createElement('a');
  link.href = shop.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = 'Open in Google Maps';
  box.append(link);
  return box;
};

if (savedNode && typeof L !== 'undefined') {
  let shops = [];
  let trucks = [];
  try { shops = JSON.parse(savedNode.dataset.shops || '[]'); } catch (err) { shops = []; }
  try { trucks = JSON.parse(savedNode.dataset.trucks || '[]'); } catch (err) { trucks = []; }
  const map = L.map(savedNode, { scrollWheelZoom: false, preferCanvas: true });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    referrerPolicy: 'strict-origin-when-cross-origin',
  }).addTo(map);
  const bounds = [];
  for (const shop of shops) {
    const marker = L.circleMarker([shop.lat, shop.lon], {
      radius: 5, weight: 1, color: '#1d4ed8', fillColor: '#60a5fa', fillOpacity: 0.9,
    }).addTo(map);
    marker.bindTooltip(shop.name);
    marker.bindPopup(() => shopPopup(shop));
    bounds.push([shop.lat, shop.lon]);
  }
  for (const truck of trucks) {
    L.circleMarker([truck.lat, truck.lon], {
      radius: 6, weight: 2, color: '#000000', fillColor: '#ffcc00', fillOpacity: 1,
    }).addTo(map).bindTooltip('Unit ' + truck.unit);
  }
  if (bounds.length) map.fitBounds(bounds, { padding: [20, 20], maxZoom: 9 });
  else map.setView([39.5, -98.35], 4);
}
