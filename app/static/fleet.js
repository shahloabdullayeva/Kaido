const node = document.getElementById('fleet-map');

const TONES = {
  bad: { color: '#cc0000', fillColor: '#dd8888' },
  warn: { color: '#996600', fillColor: '#ccaa66' },
  ok: { color: '#006600', fillColor: '#66aa66' },
};

const stateLine = (truck) => {
  const parts = [];
  if (truck.moving) parts.push('Moving ' + (truck.speed || 0) + ' mph');
  else if (truck.engine === 'Idle') parts.push('Idling' + (truck.idle ? ' ' + truck.idle : ''));
  else parts.push('Parked' + (truck.parked ? ' ' + truck.parked : ''));
  if (truck.fuel !== null && truck.fuel !== undefined) parts.push('fuel ' + Math.round(truck.fuel) + '%');
  return parts.join(' · ');
};

const tipFor = (truck) => {
  const T = window.KaidoMap.text;
  const box = document.createElement('div');
  box.className = 'map-popup';
  box.append(T('div', truck.unit, 'map-popup-unit'));
  box.append(T('div', truck.driver || 'No driver assigned', 'map-popup-driver'));
  box.append(T('div', stateLine(truck)));
  if (truck.where) box.append(T('div', truck.where, 'subtle'));
  if (truck.when) box.append(T('div', 'Updated ' + truck.when, 'subtle'));
  if (truck.duty) box.append(T('div', truck.duty + (truck.drive_left ? ' · ' + truck.drive_left + ' drive left' : ''), 'subtle'));
  const flags = [];
  if (truck.breakdowns) flags.push(truck.breakdowns + ' open breakdown' + (truck.breakdowns > 1 ? 's' : ''));
  if (truck.faults) flags.push(truck.faults + ' active fault' + (truck.faults > 1 ? 's' : ''));
  for (const w of truck.weather || []) flags.push(w.event + (w.area ? ', ' + w.area : ''));
  if (flags.length) box.append(T('div', flags.join(' · '), 'map-popup-flags'));
  return box;
};

const weatherPopup = (alerts) => {
  const T = window.KaidoMap.text;
  const box = document.createElement('div');
  box.className = 'map-popup weather-popup';
  for (const w of alerts) {
    box.append(T('div', w.event + (w.area ? ', ' + w.area : ''), 'map-popup-unit'));
    if (w.expires) box.append(T('div', 'Until ' + new Date(w.expires).toLocaleString(), 'subtle'));
    box.append(T('p', w.headline || ''));
    if (w.text) box.append(T('p', w.text.slice(0, 600), 'subtle'));
  }
  return box;
};

if (node && typeof L !== 'undefined' && window.KaidoMap) {
  let trucks = [];
  try { trucks = JSON.parse(node.dataset.trucks || '[]'); } catch (err) { trucks = []; }
  const map = L.map(node, { scrollWheelZoom: true, wheelPxPerZoomLevel: 90 });
  const memory = window.KaidoMap.attach(map, { trafficKey: node.dataset.trafficKey, store: node.dataset.store || 'dashboard' });
  const truckLayer = L.layerGroup().addTo(map);
  let show = memory.read().trucks === 'running' ? 'running' : 'all';

  const draw = () => {
    truckLayer.clearLayers();
    const bounds = [];
    for (const truck of trucks) {
      if (show === 'running' && !truck.running) continue;
      const marker = L.circleMarker([truck.lat, truck.lon], {
        pane: 'trucks', radius: 7, weight: 2, fillOpacity: 0.85, ...(TONES[truck.tone] || TONES.ok),
      });
      marker.bindTooltip(tipFor(truck), { direction: 'top', offset: [0, -6] });
      marker.on('click', () => { window.location.href = '/trucks/' + truck.id; });
      truckLayer.addLayer(marker);
      if (truck.weather && truck.weather.length) {
        const badge = L.marker([truck.lat, truck.lon], {
          pane: 'trucks', icon: L.divIcon({ className: 'weather-badge' + (truck.weather[0].severe ? ' severe' : ''), html: '', iconSize: [18, 18], iconAnchor: [-4, 22] }),
          title: truck.weather[0].event,
        });
        badge.bindPopup(weatherPopup(truck.weather));
        truckLayer.addLayer(badge);
      }
      bounds.push([truck.lat, truck.lon]);
    }
    return bounds;
  };

  const Filter = L.Control.extend({
    onAdd() {
      const box = L.DomUtil.create('div', 'leaflet-bar map-filter');
      const select = L.DomUtil.create('select', '', box);
      select.setAttribute('aria-label', 'Which trucks');
      for (const [value, label] of [['all', 'All trucks'], ['running', 'Running only']]) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        option.selected = value === show;
        select.append(option);
      }
      L.DomEvent.disableClickPropagation(box);
      select.addEventListener('change', () => { show = select.value; memory.write({ trucks: show }); draw(); });
      return box;
    },
  });
  new Filter({ position: 'topleft' }).addTo(map);

  const bounds = draw();
  if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 9 });
  else map.setView([39.5, -98.35], 4);
}
