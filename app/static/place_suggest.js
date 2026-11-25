window.placeSuggest = (input, onPick) => {
  if (!input || input.dataset.suggest) return;
  input.dataset.suggest = '1';
  input.setAttribute('autocomplete', 'off');
  const wrap = document.createElement('div');
  wrap.className = 'suggest-wrap';
  input.parentNode.insertBefore(wrap, input);
  wrap.append(input);
  const list = document.createElement('ul');
  list.className = 'suggest-list';
  list.hidden = true;
  wrap.append(list);
  let items = [];
  let active = -1;
  let timer = null;
  let run = 0;

  const close = () => { list.hidden = true; active = -1; };
  const choose = (item) => {
    input.value = item.label + (item.detail && item.detail !== 'state' ? ', ' + item.detail : '');
    close();
    onPick({ lat: item.lat, lon: item.lon, where: input.value });
  };
  const draw = () => {
    list.textContent = '';
    items.forEach((item, index) => {
      const li = document.createElement('li');
      li.className = index === active ? 'on' : '';
      const strong = document.createElement('strong');
      strong.textContent = item.label;
      li.append(strong);
      if (item.detail) {
        const small = document.createElement('span');
        small.textContent = ' ' + item.detail;
        li.append(small);
      }
      li.addEventListener('mousedown', (event) => { event.preventDefault(); choose(item); });
      list.append(li);
    });
    list.hidden = !items.length;
  };
  const fetchNow = async () => {
    const text = input.value.trim();
    const mine = ++run;
    if (text.length < 2) { items = []; draw(); return; }
    try {
      const response = await fetch('/maintenance/places?q=' + encodeURIComponent(text), {
        headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin',
      });
      if (!response.ok || mine !== run) return;
      items = (await response.json()).places || [];
      active = -1;
      draw();
    } catch (err) { items = []; draw(); }
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(fetchNow, 250); });
  input.addEventListener('keydown', (event) => {
    if (list.hidden || !items.length) return;
    if (event.key === 'ArrowDown') { event.preventDefault(); active = (active + 1) % items.length; draw(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); active = (active - 1 + items.length) % items.length; draw(); }
    else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); event.stopImmediatePropagation(); choose(items[active]); }
    else if (event.key === 'Escape') close();
  }, true);
  input.addEventListener('blur', () => setTimeout(close, 150));
};
