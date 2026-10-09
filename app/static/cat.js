(function () {
  const notif = document.getElementById('notif');
  if (!notif) return;
  const button = notif.querySelector('.notif-button');
  const panel = notif.querySelector('.notif-panel');
  const list = notif.querySelector('.notif-list');
  const count = notif.querySelector('.notif-count');
  const historyBox = notif.querySelector('.notif-history');
  const historyList = historyBox.querySelector('ul');
  const markAll = notif.querySelector('.notif-all');
  const more = notif.querySelector('.notif-more');
  const SHOWN = 5;
  let expanded = false;
  const seen = new Set();
  let first = true;
  let dirty = false;

  document.addEventListener('input', function (event) {
    if (event.target.closest && event.target.closest('form')) dirty = true;
  });
  document.addEventListener('submit', function () { dirty = false; });

  function stamp(iso) {
    return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }

  function showHistory(items) {
    historyList.textContent = '';
    for (const note of items) {
      const row = document.createElement('li');
      const when = document.createElement('span');
      when.className = 'notif-when';
      when.textContent = stamp(note.when) + (note.sender ? ' \u00b7 from ' + note.sender : '') + (note.kind === 'reminder' ? ' \u00b7 reminder' : '');
      const text = document.createElement('p');
      text.className = 'notif-old';
      text.textContent = note.message;
      row.append(when, text);
      historyList.append(row);
    }
    const extra = Math.max(historyList.children.length - SHOWN, 0);
    [...historyList.children].forEach(function (row, index) { row.hidden = !expanded && index >= SHOWN; });
    more.hidden = expanded || extra === 0;
    more.textContent = 'Show ' + extra + ' older';
    historyBox.hidden = items.length === 0;
    panel.classList.toggle('past', items.length > 0);
  }

  function place() {
    if (window.innerWidth > 640) {
      panel.style.top = '';
      return;
    }
    const box = button.getBoundingClientRect();
    panel.style.top = (box.bottom + 8) + 'px';
    panel.style.setProperty('--notif-arrow', Math.max(box.left - 12 + 8, 8) + 'px');
  }

  function setOpen(open) {
    if (open) place();
    panel.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function refreshState() {
    const total = list.children.length;
    notif.classList.toggle('has', total > 0);
    panel.classList.toggle('full', total > 0);
    count.hidden = total === 0;
    count.textContent = total > 9 ? '9+' : total;
    markAll.hidden = total < 2;
  }

  function item(note, name) {
    const box = document.createElement('div');
    box.className = 'notif-item';
    box.dataset.id = note.id;
    const hi = document.createElement('p');
    hi.className = 'notif-hi';
    hi.textContent = 'Hi ' + name + '!';
    const text = document.createElement('p');
    text.className = 'notif-text';
    text.textContent = note.message;
    const ok = document.createElement('button');
    ok.type = 'button';
    ok.className = 'btn';
    ok.textContent = note.kind === 'reminder' ? 'Got it' : 'Okay ♥';
    ok.addEventListener('click', function () {
      const payload = new FormData();
      payload.append('csrf', notif.dataset.csrf);
      fetch('/cat/' + note.id + '/done', { method: 'POST', body: payload, credentials: 'same-origin' });
      box.remove();
      refreshState();
      setTimeout(check, 400);
      if (!list.children.length) setTimeout(function () { setOpen(false); }, 600);
    });
    box.append(hi, text, ok);
    return box;
  }

  function updated() {
    if (document.getElementById('kaido-updated')) return;
    const bar = document.createElement('div');
    bar.id = 'kaido-updated';
    bar.className = 'updated-bar';
    const text = document.createElement('span');
    text.textContent = 'Kaido was updated. Save what you are typing, then refresh this page.';
    const go = document.createElement('button');
    go.type = 'button';
    go.textContent = 'Refresh now';
    go.addEventListener('click', function () { window.location.reload(); });
    bar.append(text, go);
    document.body.prepend(bar);
  }

  function arrive() {
    notif.classList.remove('arrive');
    void notif.offsetWidth;
    notif.classList.add('arrive');
  }

  function check() {
    fetch('/cat/pending', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) return;
        if (data.version && notif.dataset.version && data.version !== notif.dataset.version) {
          if (!dirty) {
            window.location.reload();
            return;
          }
          updated();
        }
        showHistory(data.history || []);
        let fresh = false;
        for (const note of data.notes) {
          if (seen.has(note.id)) continue;
          seen.add(note.id);
          list.append(item(note, data.name));
          fresh = true;
        }
        refreshState();
        if (fresh) {
          arrive();
          setTimeout(function () { setOpen(true); }, first ? 900 : 300);
        }
        first = false;
      })
      .catch(function () {});
  }

  function unread() { return list.children.length > 0; }

  more.addEventListener('click', function () {
    expanded = true;
    for (const row of historyList.children) row.hidden = false;
    more.hidden = true;
  });

  markAll.addEventListener('click', function () {
    const payload = new FormData();
    payload.append('csrf', notif.dataset.csrf);
    fetch('/cat/done-all', { method: 'POST', body: payload, credentials: 'same-origin' })
      .then(function () { list.textContent = ''; refreshState(); check(); });
  });

  button.addEventListener('click', function () { if (panel.hidden || !unread()) setOpen(panel.hidden); });
  window.addEventListener('resize', function () { if (!panel.hidden) place(); });
  document.addEventListener('click', function (event) {
    if (!notif.contains(event.target) && !unread()) setOpen(false);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !unread()) setOpen(false);
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) check();
  });

  check();
  setInterval(function () { if (!document.hidden) check(); }, 15000);
})();
