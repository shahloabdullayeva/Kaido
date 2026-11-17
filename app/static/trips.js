for (const form of document.querySelectorAll('form[data-planning]')) {
  form.addEventListener('submit', () => {
    const button = form.querySelector('[data-planning-button]');
    const note = form.querySelector('.trip-planning');
    if (button) {
      setTimeout(() => { button.disabled = true; button.textContent = 'Planning...'; }, 0);
    }
    if (note) note.hidden = false;
  });
}

const tripNode = document.getElementById('trip-map');

if (tripNode && typeof L !== 'undefined') {
  let trip = {};
  try { trip = JSON.parse(tripNode.dataset.trip || '{}'); } catch (err) { trip = {}; }
  const map = L.map(tripNode, { scrollWheelZoom: false });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    referrerPolicy: 'strict-origin-when-cross-origin',
  }).addTo(map);
  const popup = (title, lines) => {
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
    return box;
  };
  const label = (text, kind) => L.divIcon({
    className: 'trip-pin trip-pin-' + kind,
    html: '<span>' + text + '</span>',
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
  const bounds = [];
  if (trip.route && trip.route.length) {
    const line = L.polyline(trip.route, { color: '#2a78d6', weight: 4, opacity: 0.85 }).addTo(map);
    bounds.push(...line.getLatLngs().map((p) => [p.lat, p.lng]));
  }
  if (trip.start) {
    L.marker(trip.start, { icon: label('T', 'start') }).addTo(map)
      .bindPopup(popup('Truck now', ['Where Samsara last saw it']));
    bounds.push(trip.start);
  }
  (trip.stops || []).forEach((stop) => {
    const word = stop.kind === 'pickup' ? 'Pickup' : 'Delivery';
    L.marker([stop.lat, stop.lon], { icon: label(stop.kind === 'pickup' ? 'P' : 'D', 'stop') }).addTo(map)
      .bindPopup(popup(word + ': ' + stop.name, [stop.address]));
    bounds.push([stop.lat, stop.lon]);
  });
  (trip.fuel || []).forEach((stop, index) => {
    L.marker([stop.lat, stop.lon], { icon: label(String(index + 1), 'fuel') }).addTo(map)
      .bindTooltip('Fuel ' + (index + 1) + ': ' + stop.name)
      .bindPopup(popup('Fuel ' + (index + 1) + ': ' + stop.name, [
        'Mile ' + Math.round(stop.mile).toLocaleString(),
        'Buy ' + Math.round(stop.gallons) + ' gal at $' + stop.price.toFixed(3) + (stop.estimated ? ' est.' : ''),
      ]));
  });
  (trip.rests || []).forEach((rest) => {
    L.marker([rest.lat, rest.lon], { icon: label('R', 'rest') }).addTo(map)
      .bindTooltip(rest.kind + ' around mile ' + Math.round(rest.mile).toLocaleString())
      .bindPopup(popup(rest.kind, ['Around mile ' + Math.round(rest.mile).toLocaleString(), rest.where]));
  });
  if (bounds.length) map.fitBounds(bounds, { padding: [24, 24] });
  else map.setView([39.5, -98.35], 4);
}
