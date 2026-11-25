(() => {
  const form = document.querySelector('[data-global-search]');
  if (!form) return;
  const input = form.querySelector('input');
  const drop = form.querySelector('.search-drop');
  let links = [];
  let active = -1;
  let timer = null;
  let run = 0;

  const close = () => { drop.hidden = true; active = -1; };
  const mark = () => links.forEach((a, i) => a.classList.toggle('on', i === active));
  const draw = (groups) => {
    drop.textContent = '';
    links = [];
    for (const group of groups) {
      const head = document.createElement('div');
      head.className = 'search-head';
      head.textContent = group.title;
      drop.append(head);
      for (const item of group.items) {
        const a = document.createElement('a');
        a.href = item.href;
        if (item.external) { a.target = '_blank'; a.rel = 'noopener'; }
        const strong = document.createElement('strong');
        strong.textContent = item.label;
        const small = document.createElement('span');
        small.textContent = item.detail || '';
        a.append(strong, small);
        drop.append(a);
        links.push(a);
      }
    }
    if (!groups.length) {
      const none = document.createElement('div');
      none.className = 'search-head';
      none.textContent = 'Nothing found';
      drop.append(none);
    }
    active = links.length ? 0 : -1;
    mark();
    drop.hidden = false;
  };
  const lookup = async () => {
    const text = input.value.trim();
    const mine = ++run;
    if (text.length < 2) { close(); return; }
    try {
      const response = await fetch('/search?q=' + encodeURIComponent(text), {
        headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin',
      });
      if (!response.ok || mine !== run) return;
      draw((await response.json()).groups || []);
    } catch (err) { close(); }
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(lookup, 180); });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' && links.length) { event.preventDefault(); active = (active + 1) % links.length; mark(); }
    else if (event.key === 'ArrowUp' && links.length) { event.preventDefault(); active = (active - 1 + links.length) % links.length; mark(); }
    else if (event.key === 'Enter' && !drop.hidden && active >= 0) { event.preventDefault(); links[active].click(); }
    else if (event.key === 'Escape') { close(); input.blur(); }
  });
  input.addEventListener('blur', () => setTimeout(close, 200));
  input.addEventListener('focus', () => { if (input.value.trim().length >= 2) lookup(); });
  document.addEventListener('keydown', (event) => {
    const typing = event.target.closest && event.target.closest('input, textarea, select, [contenteditable]');
    if ((event.key === 'k' && (event.ctrlKey || event.metaKey)) || (event.key === '/' && !typing)) {
      event.preventDefault();
      input.focus();
      input.select();
    }
  });
})();
