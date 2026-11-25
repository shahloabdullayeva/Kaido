window.KaidoMap = (() => {
  const OSM = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const OSM_ATTR = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  const PLACE_STYLE = {
    shops: { color: '#1d4ed8', fillColor: '#60a5fa', label: 'Saved shops' },
    towing: { color: '#b45309', fillColor: '#fbbf24', label: 'Towing' },
    parking: { color: '#4b5563', fillColor: '#d1d5db', label: 'Truck parking' },
    showers: { color: '#0f766e', fillColor: '#5eead4', label: 'Showers' },
  };
  const read = (key) => { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (err) { return null; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch (err) { } };
  const text = (tag, value, cls) => { const el = document.createElement(tag); if (cls) el.className = cls; el.textContent = value || ''; return el; };

  const placeLayer = (map, kind) => {
    const group = L.layerGroup();
    let run = 0;
    const load = async () => {
      if (!map.hasLayer(group)) return;
      const mine = ++run;
      const b = map.getBounds();
      if (map.getZoom() < 6 && kind !== 'shops') { group.clearLayers(); return; }
      const q = new URLSearchParams({ kind, south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast(), zoom: map.getZoom() });
      try {
        const response = await fetch('/map/places?' + q, { credentials: 'same-origin' });
        if (!response.ok || mine !== run) return;
        const data = await response.json();
        group.clearLayers();
        const style = PLACE_STYLE[kind];
        for (const point of data.points || []) {
          const marker = L.circleMarker([point.lat, point.lon], { pane: 'places', radius: 5, weight: 1.5, fillOpacity: 0.9, color: style.color, fillColor: style.fillColor });
          const box = document.createElement('div');
          box.className = 'map-popup';
          box.append(text('div', point.name, 'map-popup-unit'), text('div', point.detail, 'subtle'));
          if (point.url) { const a = text('a', 'Google Maps'); a.href = point.url; a.target = '_blank'; a.rel = 'noopener'; box.append(a); }
          marker.bindTooltip(point.name).bindPopup(box);
          group.addLayer(marker);
        }
      } catch (err) { }
    };
    group.on('add', load);
    map.on('moveend', load);
    return group;
  };

  const weatherLayer = (map) => {
    if (!map.getPane('weather')) { map.createPane('weather'); map.getPane('weather').style.zIndex = 350; }
    const group = L.geoJSON(null, {
      pane: 'weather',
      style: (f) => ({ stroke: false, fillColor: f.properties.severe ? '#dc2626' : '#d97706', fillOpacity: 0.3 }),
      onEachFeature: (f, layer) => {
        const box = document.createElement('div');
        box.className = 'map-popup';
        box.append(text('div', f.properties.event, 'map-popup-unit'), text('div', f.properties.headline, 'subtle'),
          text('div', f.properties.until ? 'Until ' + new Date(f.properties.until).toLocaleString() : '', 'subtle'));
        layer.bindPopup(box);
      },
    });
    let loaded = false;
    group.on('add', async () => {
      if (loaded) return;
      loaded = true;
      try {
        const response = await fetch('/map/weather', { credentials: 'same-origin' });
        if (response.ok) group.addData(await response.json());
      } catch (err) { loaded = false; }
    });
    return group;
  };

  const attach = (map, options) => {
    map.createPane('trucks');
    map.getPane('trucks').style.zIndex = 650;
    map.createPane('places');
    map.getPane('places').style.zIndex = 450;
    const store = 'kaido-map-' + (options.store || 'default');
    const saved = read(store) || {};
    const base = {
      Dark: L.tileLayer(OSM, { maxZoom: 18, attribution: OSM_ATTR, className: 'tile-dark', referrerPolicy: 'strict-origin-when-cross-origin' }),
      Street: L.tileLayer(OSM, { maxZoom: 18, attribution: OSM_ATTR, referrerPolicy: 'strict-origin-when-cross-origin' }),
      Satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 18, attribution: 'Imagery © <a href="https://www.esri.com/">Esri</a>, Maxar, Earthstar Geographics, and the GIS User Community' }),
    };
    const overlays = {};
    if (options.trafficKey) {
      overlays.Traffic = L.tileLayer('https://api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png?key=' + encodeURIComponent(options.trafficKey), {
        maxZoom: 22, opacity: 0.85, attribution: 'Traffic © <a href="https://www.tomtom.com/">TomTom</a>' });
    }
    overlays['Weather radar'] = L.tileLayer.wms('https://opengeo.ncep.noaa.gov/geoserver/conus/conus_bref_qcd/ows', {
      layers: 'conus_bref_qcd', format: 'image/png', transparent: true, opacity: 0.6, attribution: 'Radar: NOAA / NWS' });
    overlays['Weather alerts'] = weatherLayer(map);
    for (const kind of Object.keys(PLACE_STYLE)) overlays[PLACE_STYLE[kind].label] = placeLayer(map, kind);
    const pick = base[saved.base] ? saved.base : 'Dark';
    base[pick].addTo(map);
    for (const name of saved.overlays || []) if (overlays[name]) overlays[name].addTo(map);
    L.control.layers(base, overlays, { collapsed: true, position: 'topright' }).addTo(map);
    const remember = () => {
      const on = Object.keys(overlays).filter((name) => map.hasLayer(overlays[name]));
      const baseOn = Object.keys(base).find((name) => map.hasLayer(base[name])) || 'Dark';
      write(store, Object.assign(read(store) || {}, { base: baseOn, overlays: on }));
    };
    map.on('baselayerchange overlayadd overlayremove', remember);
    return { read: () => read(store) || {}, write: (extra) => write(store, Object.assign(read(store) || {}, extra)) };
  };

  return { attach, text };
})();
