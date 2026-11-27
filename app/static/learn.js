(() => {
  const KEY = 'kaido-learn-read';
  const LAST = 'kaido-learn-last';
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { return {}; } };
  const save = (v) => { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { } };
  let read = load();
  const paintMarks = () => document.querySelectorAll('[data-topic]').forEach((el) => el.classList.toggle('is-read', Boolean(read[el.dataset.topic])));
  paintMarks();

  const page = document.querySelector('[data-topic-page]');
  if (page) {
    const slug = page.dataset.topicPage;
    try { localStorage.setItem(LAST, JSON.stringify({ slug, title: page.dataset.title })); } catch (e) { }
    const buttons = document.querySelectorAll('[data-mark-read]');
    const paint = () => buttons.forEach((b) => { b.textContent = read[slug] ? 'Read ✓' : 'Mark as read'; b.classList.toggle('ghost', Boolean(read[slug])); });
    buttons.forEach((b) => b.addEventListener('click', () => {
      read = load();
      if (read[slug]) delete read[slug]; else read[slug] = Date.now();
      save(read); paint(); paintMarks();
    }));
    paint();
    const bar = document.querySelector('[data-readbar]');
    const links = Array.from(document.querySelectorAll('[data-toc] a'));
    const heads = links.map((a) => document.getElementById(decodeURIComponent(a.hash.slice(1)))).filter(Boolean);
    const onScroll = () => {
      const max = document.documentElement.scrollHeight - innerHeight;
      if (bar) bar.style.width = `${max > 0 ? Math.min(100, (scrollY / max) * 100) : 100}%`;
      let current = 0;
      heads.forEach((h, i) => { if (h.getBoundingClientRect().top < 120) current = i; });
      links.forEach((a, i) => a.classList.toggle('on', i === current && heads.length > 0));
    };
    addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  const home = document.querySelector('[data-learn-home]');
  if (home) {
    const total = document.querySelectorAll('.ln-shelf [data-topic], .ln-quick [data-topic]').length;
    const count = Object.keys(read).length;
    const box = home.querySelector('[data-progress-box]');
    let last = null;
    try { last = JSON.parse(localStorage.getItem(LAST) || 'null'); } catch (e) { }
    if (count || last) {
      box.hidden = false;
      home.querySelector('[data-read-count]').textContent = count;
      const all = parseInt(box.textContent.match(/of (\d+)/)[1], 10) || total || 1;
      home.querySelector('[data-read-bar]').style.width = `${Math.min(100, (count / all) * 100)}%`;
      if (last && last.slug) {
        const link = home.querySelector('[data-continue]');
        link.href = `/learn/${last.slug}`;
        link.querySelector('span').textContent = last.title;
        link.hidden = false;
      }
    }
  }
})();
