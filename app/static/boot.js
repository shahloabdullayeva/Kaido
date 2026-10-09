(function () {
  const root = document.documentElement;
  let show = false;
  try {
    const nav = performance.getEntriesByType('navigation')[0];
    const from = document.referrer ? new URL(document.referrer) : null;
    const fromLogin = from && from.origin === location.origin && from.pathname.startsWith('/login');
    show = (nav && nav.type === 'reload') || fromLogin || (!from && !sessionStorage.getItem('kaido-seen'));
    sessionStorage.setItem('kaido-seen', '1');
  } catch (err) {
    show = false;
  }
  if (!show) return;
  root.classList.add('splash');
  const started = Date.now();
  document.addEventListener('DOMContentLoaded', function () {
    setTimeout(function () {
      root.classList.add('splash-out');
      setTimeout(function () { root.classList.remove('splash', 'splash-out'); }, 400);
    }, Math.max(900 - (Date.now() - started), 0));
  });
})();
