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
  const map = L.map(tripNode, { scrollWheelZoom: true, wheelPxPerZoomLevel: 90 });
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
    L.marker(trip.start, { icon: label('S', 'start') }).addTo(map)
      .bindPopup(popup('Start', []));
    bounds.push(trip.start);
  }
  const words = { pickup: 'Pickup', delivery: 'Delivery', place: 'Arrive' };
  const letters = { pickup: 'P', delivery: 'D', place: 'A' };
  (trip.stops || []).forEach((stop) => {
    const word = words[stop.kind] || 'Stop';
    L.marker([stop.lat, stop.lon], { icon: label(letters[stop.kind] || 'A', 'stop') }).addTo(map)
      .bindTooltip(word + (stop.when ? ' ' + stop.when : ''))
      .bindPopup(popup(word + ': ' + stop.name, [stop.address, stop.when, stop.late ? 'Late ' + Math.round(stop.late) + ' h' : '']));
    bounds.push([stop.lat, stop.lon]);
  });
  (trip.fuel || []).forEach((stop, index) => {
    L.marker([stop.lat, stop.lon], { icon: label(String(index + 1), 'fuel') }).addTo(map)
      .bindTooltip('Fuel ' + (index + 1) + (stop.when ? ' · ' + stop.when : ''))
      .bindPopup(popup('Fuel ' + (index + 1) + ': ' + stop.name, [
        stop.when,
        'Buy ' + Math.round(stop.gallons) + ' gal at $' + stop.price.toFixed(2) + (stop.estimated ? ' est.' : ''),
      ]));
  });
  (trip.rests || []).forEach((rest) => {
    L.marker([rest.lat, rest.lon], { icon: label('R', 'rest') }).addTo(map)
      .bindTooltip(rest.kind + (rest.when ? ' · ' + rest.when : ''))
      .bindPopup(popup(rest.kind, [rest.when, rest.where]));
  });
  if (bounds.length) map.fitBounds(bounds, { padding: [24, 24] });
  else map.setView([39.5, -98.35], 4);

  let truck = null;
  const nowBox = document.querySelector('[data-live-now]');
  const refresh = () => {
    if (!trip.live) return;
    fetch(trip.live, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : {}))
      .then((now) => {
        if (!now || now.lat === undefined) return;
        const lines = [now.ago, now.tank !== null ? 'Tank ' + Math.round(now.tank) + '%' : '',
          now.off_route ? 'Off route' : now.left.toLocaleString() + ' mi to go'];
        if (!truck) {
          truck = L.marker([now.lat, now.lon], { icon: label('T', 'live'), zIndexOffset: 1000 }).addTo(map);
        } else {
          truck.setLatLng([now.lat, now.lon]);
        }
        truck.bindPopup(popup('Truck now', lines));
        if (nowBox) nowBox.textContent = lines.filter(Boolean).join(' · ');
        document.querySelectorAll('[data-fuel-row]').forEach((row) => {
          row.classList.toggle('next', now.next_fuel !== null && Number(row.dataset.fuelRow) === now.next_fuel);
          row.classList.toggle('done', now.next_fuel === null || Number(row.dataset.fuelRow) < now.next_fuel);
        });
      })
      .catch(() => {});
  };
  refresh();
  setInterval(refresh, 60000);
}
