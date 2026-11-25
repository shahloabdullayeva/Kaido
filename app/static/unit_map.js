const unitMap = document.querySelector('[data-unit-map]');

if (unitMap && typeof L !== 'undefined') {
  const lat = parseFloat(unitMap.dataset.lat);
  const lon = parseFloat(unitMap.dataset.lon);
  const map = L.map(unitMap, { scrollWheelZoom: false, zoomControl: true });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    referrerPolicy: 'strict-origin-when-cross-origin',
  }).addTo(map);
  L.circleMarker([lat, lon], { radius: 8, weight: 2, color: '#1d4ed8', fillColor: '#60a5fa', fillOpacity: 0.9 })
    .addTo(map).bindTooltip(unitMap.dataset.label || '');
  map.setView([lat, lon], 12);
}
