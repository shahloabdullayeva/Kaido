(() => {
  const root = document.querySelector('[data-walk]');
  const T = {
    en: { start: 'Start walkaround', upload: 'Upload from gallery', pre: 'Pre-trip', post: 'Post-trip', who: 'Driver',
      someone: 'Someone else', name: 'Your name', step: 'Step', of: 'of', looking: 'Looking…', got: 'Got it',
      skip: 'Skip', wrong: 'Anything wrong?', wrongHint: 'Something the camera can\'t see, like an air leak?',
      hold: 'Hold to record a voice note', recording: 'Recording… let go to stop', allGood: 'No, all good',
      send: 'Send voice note', again: 'Record again', done: 'Done', doneHint: 'Your PTI is saved. Thank you.',
      sending: 'Sending in the background', sent: 'Everything is sent.', keepOpen: 'Keep this page open until it says everything is sent. If you close it, it carries on the next time you open the link.',
      noCamera: 'The camera did not open. Allow the camera, or upload photos or a video from your gallery instead.',
      telegram: 'The camera may not work inside Telegram. Tap the menu (⋮ or ...) and choose Open in browser.',
      pick: 'Pick photos or one video of the truck', working: 'Preparing your files…', noFiles: 'Pick at least one photo or video.',
      oldForm: 'Use the old form', redo: 'Your last inspection was rejected:', speakOn: 'Voice on', speakOff: 'Voice off',
      possible: 'Possible problem:', heard: 'Heard:' },
    ru: { start: 'Начать осмотр', upload: 'Загрузить из галереи', pre: 'Перед рейсом', post: 'После рейса', who: 'Водитель',
      someone: 'Другой', name: 'Ваше имя', step: 'Шаг', of: 'из', looking: 'Ищу…', got: 'Готово',
      skip: 'Пропустить', wrong: 'Есть проблема?', wrongHint: 'То, что камера не видит, например утечка воздуха?',
      hold: 'Удерживайте, чтобы записать голос', recording: 'Запись… отпустите, чтобы остановить', allGood: 'Нет, всё в порядке',
      send: 'Отправить голосовую заметку', again: 'Записать заново', done: 'Готово', doneHint: 'Ваш осмотр сохранён. Спасибо.',
      sending: 'Отправка в фоне', sent: 'Всё отправлено.', keepOpen: 'Не закрывайте страницу, пока не появится «Всё отправлено». Если закроете, отправка продолжится при следующем открытии ссылки.',
      noCamera: 'Камера не открылась. Разрешите доступ к камере или загрузите фото или видео из галереи.',
      telegram: 'В Telegram камера может не работать. Нажмите меню (⋮ или ...) и выберите «Открыть в браузере».',
      pick: 'Выберите фото или одно видео грузовика', working: 'Подготовка файлов…', noFiles: 'Выберите хотя бы одно фото или видео.',
      oldForm: 'Старая форма', redo: 'Ваш прошлый осмотр отклонён:', speakOn: 'Голос вкл.', speakOff: 'Голос выкл.',
      possible: 'Возможная проблема:', heard: 'Распознано:' },
    uz: { start: "Ko'rikni boshlash", upload: 'Galereyadan yuklash', pre: 'Reysdan oldin', post: 'Reysdan keyin', who: 'Haydovchi',
      someone: 'Boshqa', name: 'Ismingiz', step: 'Qadam', of: '/', looking: 'Qidirilmoqda…', got: 'Tayyor',
      skip: "O'tkazib yuborish", wrong: 'Muammo bormi?', wrongHint: "Kamera ko'rmaydigan narsa, masalan havo oqishi?",
      hold: 'Ovozli xabar yozish uchun bosib turing', recording: "Yozilmoqda… to'xtatish uchun qo'yib yuboring", allGood: "Yo'q, hammasi joyida",
      send: 'Ovozli xabarni yuborish', again: 'Qayta yozish', done: 'Tayyor', doneHint: "Ko'rigingiz saqlandi. Rahmat.",
      sending: 'Fonda yuborilmoqda', sent: 'Hammasi yuborildi.', keepOpen: "«Hammasi yuborildi» chiqmaguncha sahifani yopmang. Yopsangiz, havolani keyingi ochganingizda yuborish davom etadi.",
      noCamera: "Kamera ochilmadi. Kameraga ruxsat bering yoki galereyadan rasm yoki video yuklang.",
      telegram: "Telegram ichida kamera ishlamasligi mumkin. Menyuni (⋮ yoki ...) bosing va «Brauzerda ochish»ni tanlang.",
      pick: 'Mashinaning rasmlarini yoki bitta videosini tanlang', working: 'Fayllar tayyorlanmoqda…', noFiles: 'Kamida bitta rasm yoki video tanlang.',
      oldForm: 'Eski shakl', redo: "Oldingi ko'rigingiz rad etildi:", speakOn: 'Ovoz yoqilgan', speakOff: "Ovoz o'chirilgan",
      possible: 'Ehtimoliy muammo:', heard: 'Eshitildi:' },
  };
  const VOICES = { en: 'en-US', ru: 'ru-RU', uz: 'uz-UZ' };
  const QUEUE_DB = 'kaido-walk';

  const openDb = () => new Promise((resolve, reject) => {
    const req = indexedDB.open(QUEUE_DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore('queue', { keyPath: 'id', autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  const memoryQueue = [];
  let dbPromise = null;
  const db = () => {
    if (!dbPromise) dbPromise = openDb().catch(() => null);
    return dbPromise;
  };
  const tx = async (mode, fn) => {
    const handle = await db();
    if (!handle) return fn(null);
    return new Promise((resolve, reject) => {
      const t = handle.transaction('queue', mode);
      const store = t.objectStore('queue');
      let out;
      Promise.resolve(fn(store)).then((v) => { out = v; });
      t.oncomplete = () => resolve(out);
      t.onerror = () => reject(t.error);
    });
  };
  const reqP = (r) => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });

  const enqueue = async (url, fields, files) => {
    const item = { url, fields, files: files || {}, tries: 0 };
    try {
      await tx('readwrite', (store) => (store ? reqP(store.add(item)) : memoryQueue.push(item)));
    } catch (e) {
      memoryQueue.push(item);
    }
    pump();
  };
  const nextItem = async () => {
    if (memoryQueue.length) return { item: memoryQueue[0], memory: true };
    try {
      const item = await tx('readonly', (store) => (store ? new Promise((resolve) => {
        const c = store.openCursor();
        c.onsuccess = () => resolve(c.result ? c.result.value : null);
        c.onerror = () => resolve(null);
      }) : null));
      return item ? { item, memory: false } : null;
    } catch (e) {
      return null;
    }
  };
  const dropItem = async (entry) => {
    if (entry.memory) { memoryQueue.shift(); return; }
    try { await tx('readwrite', (store) => store && reqP(store.delete(entry.item.id))); } catch (e) { }
  };
  const countItems = async () => {
    try {
      const n = await tx('readonly', (store) => (store ? reqP(store.count()) : 0));
      return n + memoryQueue.length;
    } catch (e) {
      return memoryQueue.length;
    }
  };

  let pumping = false;
  let wait = 2000;
  const onQueue = [];
  const pump = async () => {
    if (pumping) return;
    pumping = true;
    try {
      for (;;) {
        const left = await countItems();
        onQueue.forEach((fn) => fn(left));
        const entry = await nextItem();
        if (!entry) break;
        const form = new FormData();
        Object.entries(entry.item.fields).forEach(([k, v]) => form.append(k, v == null ? '' : String(v)));
        Object.entries(entry.item.files).forEach(([k, blob]) => form.append(k, blob, k + (blob.type.includes('audio') ? '.webm' : '.jpg')));
        let status = 0;
        try {
          const ctrl = new AbortController();
          const timer = setTimeout(() => ctrl.abort(), 60000);
          const res = await fetch(entry.item.url, { method: 'POST', body: form, signal: ctrl.signal, credentials: 'same-origin' });
          clearTimeout(timer);
          status = res.status;
        } catch (e) {
          status = 0;
        }
        if (status >= 200 && status < 300 || (status >= 400 && status < 500 && status !== 408 && status !== 429 && status !== 409)) {
          await dropItem(entry);
          wait = 2000;
          continue;
        }
        if (status === 409 && (entry.item.tries || 0) > 20) { await dropItem(entry); continue; }
        entry.item.tries = (entry.item.tries || 0) + 1;
        await new Promise((r) => setTimeout(r, wait));
        wait = Math.min(wait * 2, 60000);
      }
    } finally {
      pumping = false;
    }
  };
  window.addEventListener('online', () => { wait = 2000; pump(); });
  pump();

  if (!root) return;

  const steps = JSON.parse(document.getElementById('walk-steps').textContent);
  const token = root.dataset.token;
  const base = `/pti/${token}/walk`;
  const aiOn = root.dataset.ai === '1';
  const $ = (sel) => root.querySelector(sel);
  const screens = {};
  root.querySelectorAll('[data-screen]').forEach((el) => { screens[el.dataset.screen] = el; });
  const show = (name) => Object.entries(screens).forEach(([k, el]) => { el.hidden = k !== name; });

  const pickLang = () => {
    try { const saved = localStorage.getItem('kaido-walk-lang'); if (saved && T[saved]) return saved; } catch (e) { }
    const nav = (navigator.language || 'en').slice(0, 2).toLowerCase();
    return T[nav] ? nav : 'en';
  };
  let lang = pickLang();
  let speakOn = true;
  const t = (k) => (T[lang] && T[lang][k]) || T.en[k];
  const paint = () => {
    root.querySelectorAll('[data-t]').forEach((el) => { el.textContent = t(el.dataset.t); });
    root.querySelectorAll('[data-lang]').forEach((el) => el.classList.toggle('on', el.dataset.lang === lang));
    document.documentElement.lang = lang;
    const nameBox = root.querySelector('[data-driver-name]');
    if (nameBox) nameBox.placeholder = t('name');
  };
  root.querySelectorAll('[data-lang]').forEach((el) => el.addEventListener('click', () => {
    lang = el.dataset.lang;
    try { localStorage.setItem('kaido-walk-lang', lang); } catch (e) { }
    paint();
  }));
  paint();

  if (/Telegram/i.test(navigator.userAgent) || window.TelegramWebview || window.TelegramWebviewProxy) {
    const warn = $('[data-telegram]');
    if (warn) warn.hidden = false;
  }

  const kind = 'pre_trip';
  const driverName = $('[data-driver-name]');

  const newKey = () => {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  };
  let key = null;
  const sessionFields = () => ({ key, kind, lang, driver_name: driverName.value.trim() });

  const speak = (text) => {
    if (!speakOn || !('speechSynthesis' in window)) return;
    try {
      speechSynthesis.cancel();
      const voices = speechSynthesis.getVoices();
      const want = VOICES[lang].slice(0, 2);
      if (voices.length && !voices.some((v) => (v.lang || '').toLowerCase().startsWith(want))) return;
      const u = new SpeechSynthesisUtterance(text);
      u.lang = VOICES[lang];
      speechSynthesis.speak(u);
    } catch (e) { }
  };
  const speakBtn = $('[data-speak]');
  if (speakBtn) speakBtn.addEventListener('click', () => {
    speakOn = !speakOn;
    speakBtn.dataset.t = speakOn ? 'speakOn' : 'speakOff';
    speakBtn.textContent = t(speakBtn.dataset.t);
    if (!speakOn && 'speechSynthesis' in window) speechSynthesis.cancel();
  });

  const getPosition = () => new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    const timer = setTimeout(() => resolve(null), 7000);
    navigator.geolocation.getCurrentPosition(
      (p) => { clearTimeout(timer); resolve(p.coords); },
      () => { clearTimeout(timer); resolve(null); },
      { enableHighAccuracy: true, timeout: 7000, maximumAge: 60000 },
    );
  });

  const toBlob = (canvas, quality) => new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
  const grab = (source, edge, quality) => {
    const w = source.videoWidth || source.naturalWidth || source.width;
    const h = source.videoHeight || source.naturalHeight || source.height;
    if (!w || !h) return Promise.resolve(null);
    const scale = Math.min(1, edge / Math.max(w, h));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
    return toBlob(canvas, quality);
  };

  const video = $('[data-video]');
  let stream = null;
  let current = 0;
  let stepTimer = null;
  let stepToken = 0;
  let coords = null;

  const stopCamera = () => {
    if (stream) stream.getTracks().forEach((tr) => tr.stop());
    stream = null;
  };

  const check = async (blob, stepKey) => {
    const form = new FormData();
    form.append('key', key);
    form.append('step', stepKey);
    form.append('image', blob, 'check.jpg');
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 9000);
      const res = await fetch(`${base}/check`, { method: 'POST', body: form, signal: ctrl.signal, credentials: 'same-origin' });
      clearTimeout(timer);
      if (res.status === 409) return { in_frame: 'pending' };
      return res.ok ? await res.json() : { in_frame: 'unknown' };
    } catch (e) {
      return { in_frame: 'unknown' };
    }
  };

  const saveFrame = async (stepKey, result) => {
    const blob = await grab(video, 1280, 0.82);
    if (!blob) return;
    await enqueue(`${base}/frame`, {
      key, step: stepKey, client_id: newKey(), taken_at: new Date().toISOString(),
      lat: coords ? coords.latitude : '', lon: coords ? coords.longitude : '',
      check: result ? JSON.stringify(result) : '',
    }, { image: blob });
  };

  const ARROW = { up: '↑', left: '←', right: '→', down: '↓', none: '' };
  const runStep = async () => {
    clearTimeout(stepTimer);
    const mine = ++stepToken;
    if (current >= steps.length) { stopCamera(); return voiceStep(); }
    const step = steps[current];
    $('[data-step-count]').textContent = `${t('step')} ${current + 1} ${t('of')} ${steps.length}`;
    $('[data-step-title]').textContent = step.title[lang] || step.title.en;
    $('[data-step-say]').textContent = step.say[lang] || step.say.en;
    $('[data-arrow]').textContent = ARROW[step.arrow] || '';
    $('[data-arrow]').dataset.dir = step.arrow;
    $('[data-progress]').style.width = `${(current / steps.length) * 100}%`;
    const status = $('[data-status]');
    const problem = $('[data-problem]');
    status.textContent = t('looking');
    status.className = 'walk-status';
    problem.hidden = true;
    speak(step.say[lang] || step.say.en);
    const started = Date.now();
    const limit = aiOn ? 9000 : 5000;
    let last = null;
    let tries = 0;
    await new Promise((r) => setTimeout(r, 1800));
    while (mine === stepToken && Date.now() - started < limit) {
      if (aiOn && tries < 4) {
        const blob = await grab(video, 768, 0.7);
        if (blob) {
          tries += 1;
          const result = await check(blob, step.key);
          if (mine !== stepToken) return;
          if (result.in_frame !== 'unknown' && result.in_frame !== 'pending') last = result;
          if (result.problem) { problem.textContent = `${t('possible')} ${result.problem}`; problem.hidden = false; }
          if (result.in_frame === 'yes') break;
        }
      } else {
        await new Promise((r) => setTimeout(r, 600));
      }
    }
    if (mine !== stepToken) return;
    status.textContent = t('got');
    status.className = 'walk-status ok';
    if (navigator.vibrate) navigator.vibrate(60);
    await saveFrame(step.key, last);
    stepTimer = setTimeout(() => { if (mine === stepToken) { current += 1; runStep(); } }, 700);
  };


  const startLive = async () => {
    key = newKey();
    show('camera');
    const geo = getPosition();
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false,
      });
    } catch (e) {
      show('intro');
      $('[data-intro-error]').textContent = t('noCamera');
      $('[data-intro-error]').hidden = false;
      return;
    }
    video.srcObject = stream;
    try { await video.play(); } catch (e) { }
    coords = await geo;
    await enqueue(`${base}/start`, {
      ...sessionFields(), mode: 'live', started_at: new Date().toISOString(),
      lat: coords ? coords.latitude : '', lon: coords ? coords.longitude : '', acc: coords ? Math.round(coords.accuracy) : '',
      meta: JSON.stringify({ ua: navigator.userAgent.slice(0, 200) }),
    });
    current = 0;
    runStep();
  };
  const needName = () => {
    if (driverName.value.trim()) return false;
    $('[data-intro-error]').textContent = t('name');
    $('[data-intro-error]').hidden = false;
    driverName.focus();
    return true;
  };
  $('[data-start]').addEventListener('click', () => {
    if (needName()) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      $('[data-intro-error]').textContent = t('noCamera');
      $('[data-intro-error]').hidden = false;
      return;
    }
    startLive();
  });

  let recorder = null;
  let chunks = [];
  let audioBlob = null;
  let heard = '';
  let recognition = null;
  const voiceStep = () => {
    show('voice');
    speak(`${t('wrong')} ${t('wrongHint')}`);
  };
  const holdBtn = $('[data-hold]');
  const beginRecord = async (ev) => {
    ev.preventDefault();
    if (recorder) return;
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      recorder = new MediaRecorder(mic);
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = () => {
        mic.getTracks().forEach((tr) => tr.stop());
        audioBlob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        recorder = null;
        $('[data-voice-actions]').hidden = false;
      };
      recorder.start();
      holdBtn.classList.add('on');
      holdBtn.textContent = t('recording');
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SR) {
        recognition = new SR();
        recognition.lang = VOICES[lang];
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.onresult = (e) => {
          heard = Array.from(e.results).map((r) => r[0].transcript).join(' ').trim();
          const out = $('[data-heard]');
          out.textContent = `${t('heard')} ${heard}`;
          out.hidden = !heard;
        };
        try { recognition.start(); } catch (e) { }
      }
      setTimeout(() => { if (recorder) endRecord(); }, 60000);
    } catch (e) {
      holdBtn.textContent = t('hold');
    }
  };
  const endRecord = () => {
    if (!recorder) return;
    try { recorder.stop(); } catch (e) { }
    if (recognition) { try { recognition.stop(); } catch (e) { } }
    holdBtn.classList.remove('on');
    holdBtn.textContent = t('hold');
  };
  holdBtn.addEventListener('pointerdown', beginRecord);
  holdBtn.addEventListener('pointerup', endRecord);
  holdBtn.addEventListener('pointerleave', endRecord);
  holdBtn.addEventListener('contextmenu', (e) => e.preventDefault());

  const finish = async () => {
    await enqueue(`${base}/finish`, { key });
    show('done');
    speak(t('done'));
  };
  $('[data-all-good]').addEventListener('click', finish);
  $('[data-send-voice]').addEventListener('click', async () => {
    await enqueue(`${base}/voice`, { key, text: heard }, audioBlob ? { audio: audioBlob } : {});
    finish();
  });
  $('[data-again]').addEventListener('click', () => {
    audioBlob = null;
    heard = '';
    $('[data-heard]').hidden = true;
    $('[data-voice-actions]').hidden = true;
  });

  onQueue.push((left) => {
    const box = $('[data-queue]');
    if (!box) return;
    box.textContent = left ? `${t('sending')}: ${left}` : t('sent');
    box.classList.toggle('ok', !left);
  });

  const exifOf = async (file) => {
    const buf = await file.slice(0, 256 * 1024).arrayBuffer();
    const v = new DataView(buf);
    if (v.byteLength < 4 || v.getUint16(0) !== 0xFFD8) return {};
    let off = 2;
    while (off + 4 < v.byteLength) {
      const marker = v.getUint16(off);
      const size = v.getUint16(off + 2);
      if (marker === 0xFFE1 && v.getUint32(off + 4) === 0x45786966) return readTiff(v, off + 10);
      if ((marker & 0xFF00) !== 0xFF00) break;
      off += 2 + size;
    }
    return {};
  };
  const readTiff = (v, start) => {
    const little = v.getUint16(start) === 0x4949;
    const u16 = (o) => v.getUint16(start + o, little);
    const u32 = (o) => v.getUint32(start + o, little);
    const ascii = (o, n) => { let s = ''; for (let i = 0; i < n - 1 && start + o + i < v.byteLength; i += 1) s += String.fromCharCode(v.getUint8(start + o + i)); return s; };
    const ifd = (o) => {
      const tags = {};
      if (start + o + 2 > v.byteLength) return tags;
      const n = u16(o);
      for (let i = 0; i < n; i += 1) {
        const e = o + 2 + i * 12;
        if (start + e + 12 > v.byteLength) break;
        tags[u16(e)] = { type: u16(e + 2), count: u32(e + 4), at: e + 8, value: u32(e + 8) };
      }
      return tags;
    };
    const str = (tag) => (tag ? (tag.count <= 4 ? ascii(tag.at, tag.count) : ascii(tag.value, tag.count)) : null);
    const rationals = (tag) => {
      if (!tag) return null;
      const out = [];
      for (let i = 0; i < tag.count; i += 1) out.push(u32(tag.value + i * 8) / (u32(tag.value + i * 8 + 4) || 1));
      return out;
    };
    try {
      const zero = ifd(u32(4));
      const out = {};
      if (zero[0x8769]) {
        const exif = ifd(zero[0x8769].value);
        const when = str(exif[0x9003]) || str(zero[0x0132]);
        const zone = str(exif[0x9011]);
        if (when) {
          const m = when.match(/(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})/);
          if (m) {
            const iso = `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}`;
            const d = zone ? new Date(iso + zone) : new Date(iso);
            if (!Number.isNaN(d.getTime())) out.taken = d;
          }
        }
      }
      if (zero[0x8825]) {
        const gps = ifd(zero[0x8825].value);
        const lat = rationals(gps[2]);
        const lon = rationals(gps[4]);
        if (lat && lon && lat.length === 3 && lon.length === 3) {
          let la = lat[0] + lat[1] / 60 + lat[2] / 3600;
          let lo = lon[0] + lon[1] / 60 + lon[2] / 3600;
          if (str(gps[1]) === 'S') la = -la;
          if (str(gps[3]) === 'W') lo = -lo;
          if (la || lo) { out.lat = la; out.lon = lo; }
        }
      }
      return out;
    } catch (e) {
      return {};
    }
  };
  const findBytes = (bytes, pattern) => {
    outer: for (let i = 0; i <= bytes.length - pattern.length; i += 1) {
      for (let j = 0; j < pattern.length; j += 1) if (bytes[i + j] !== pattern[j]) continue outer;
      return i;
    }
    return -1;
  };
  const mp4Of = async (file) => {
    const size = 4 * 1024 * 1024;
    const parts = [await file.slice(0, size).arrayBuffer()];
    if (file.size > size) parts.push(await file.slice(Math.max(size, file.size - size)).arrayBuffer());
    const out = {};
    for (const part of parts) {
      const bytes = new Uint8Array(part);
      const v = new DataView(part);
      const at = findBytes(bytes, [0x6d, 0x76, 0x68, 0x64]);
      if (at >= 0 && !out.taken && at + 16 < bytes.length) {
        const version = bytes[at + 4];
        const secs = version === 1 ? Number(v.getBigUint64(at + 8)) : v.getUint32(at + 8);
        if (secs > 2082844800) {
          const d = new Date((secs - 2082844800) * 1000);
          if (d.getFullYear() > 2005) out.taken = d;
        }
      }
      const xyz = findBytes(bytes, [0xa9, 0x78, 0x79, 0x7a]);
      if (xyz >= 0 && out.lat == null) {
        let s = '';
        for (let i = xyz + 8; i < Math.min(bytes.length, xyz + 60); i += 1) s += String.fromCharCode(bytes[i]);
        const m = s.match(/([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)/);
        if (m) { out.lat = parseFloat(m[1]); out.lon = parseFloat(m[2]); }
      }
    }
    return out;
  };
  const videoFrames = (file, count) => new Promise((resolve) => {
    const el = document.createElement('video');
    el.muted = true;
    el.playsInline = true;
    el.preload = 'auto';
    const url = URL.createObjectURL(file);
    el.src = url;
    const frames = [];
    const fail = () => { URL.revokeObjectURL(url); resolve(frames); };
    el.onerror = fail;
    el.onloadeddata = async () => {
      const duration = el.duration && Number.isFinite(el.duration) ? el.duration : 0;
      if (!duration) return fail();
      for (let i = 0; i < count; i += 1) {
        const at = duration * (i + 0.5) / count;
        await new Promise((r) => { el.onseeked = r; el.currentTime = at; setTimeout(r, 4000); });
        const blob = await grab(el, 1280, 0.82);
        if (blob) frames.push({ blob, offset: at });
      }
      URL.revokeObjectURL(url);
      resolve(frames);
    };
  });
  const imageBlob = (file) => new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = async () => { const b = await grab(img, 1280, 0.82); URL.revokeObjectURL(url); resolve(b); };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
    img.src = url;
  });

  const gallery = $('[data-gallery]');
  $('[data-upload]').addEventListener('click', () => { if (!needName()) gallery.click(); });
  gallery.addEventListener('change', async () => {
    const files = Array.from(gallery.files || []);
    if (!files.length) return;
    key = newKey();
    show('working');
    const items = [];
    const meta = { files: [] };
    const videos = files.filter((f) => f.type.startsWith('video/'));
    const photos = files.filter((f) => !f.type.startsWith('video/')).slice(0, 24);
    for (const file of videos.slice(0, 2)) {
      const info = await mp4Of(file).catch(() => ({}));
      meta.files.push({ name: file.name.slice(0, 80), type: file.type, size: file.size, modified: file.lastModified ? new Date(file.lastModified).toISOString() : null, taken: info.taken ? info.taken.toISOString() : null, gps: info.lat != null });
      const frames = await videoFrames(file, Math.max(steps.length + 2, 10));
      frames.forEach((f) => items.push({
        blob: f.blob, taken: info.taken ? new Date(info.taken.getTime() + f.offset * 1000) : null, lat: info.lat, lon: info.lon,
      }));
    }
    for (const file of photos) {
      const info = await exifOf(file).catch(() => ({}));
      meta.files.push({ name: file.name.slice(0, 80), type: file.type, size: file.size, modified: file.lastModified ? new Date(file.lastModified).toISOString() : null, taken: info.taken ? info.taken.toISOString() : null, gps: info.lat != null });
      const blob = await imageBlob(file);
      if (blob) items.push({ blob, taken: info.taken || null, lat: info.lat, lon: info.lon });
    }
    if (!items.length) {
      show('intro');
      $('[data-intro-error]').textContent = t('noFiles');
      $('[data-intro-error]').hidden = false;
      return;
    }
    await enqueue(`${base}/start`, { ...sessionFields(), mode: 'upload', started_at: new Date().toISOString(), meta: JSON.stringify(meta) });
    for (const item of items.slice(0, 36)) {
      await enqueue(`${base}/frame`, {
        key, step: '', client_id: newKey(), taken_at: item.taken ? item.taken.toISOString() : '',
        lat: item.lat != null ? item.lat : '', lon: item.lon != null ? item.lon : '',
      }, { image: item.blob });
    }
    gallery.value = '';
    voiceStep();
  });

  show('intro');
})();
