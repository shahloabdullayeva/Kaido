(function () {
  const notif = document.getElementById('notif');
  if (!notif) return;
  const button = notif.querySelector('.notif-button');
  const panel = notif.querySelector('.notif-panel');
  const list = notif.querySelector('.notif-list');
  const count = notif.querySelector('.notif-count');
  const seen = new Set();
  let first = true;

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
    count.textContent = total;
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
      if (!list.children.length) setTimeout(function () { setOpen(false); }, 600);
    });
    box.append(hi, text, ok);
    return box;
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

  button.addEventListener('click', function () { setOpen(panel.hidden); });
  window.addEventListener('resize', function () { if (!panel.hidden) place(); });
  document.addEventListener('click', function (event) {
    if (!notif.contains(event.target)) setOpen(false);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') setOpen(false);
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) check();
  });

  check();
  setInterval(function () { if (!document.hidden) check(); }, 15000);
})();
