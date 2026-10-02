(function () {
  const cat = document.getElementById('cat');
  if (!cat) return;

  function leave() {
    cat.classList.remove('in');
    cat.classList.add('out');
    const payload = new FormData();
    payload.append('csrf', cat.dataset.csrf);
    fetch('/cat/' + cat.dataset.id + '/done', { method: 'POST', body: payload, credentials: 'same-origin' });
    setTimeout(function () { cat.remove(); }, 900);
  }

  cat.querySelector('.cat-ok').addEventListener('click', leave);
  cat.querySelector('.cat-close').addEventListener('click', leave);

  setTimeout(function () {
    cat.hidden = false;
    requestAnimationFrame(function () { cat.classList.add('in'); });
  }, 700);
})();
