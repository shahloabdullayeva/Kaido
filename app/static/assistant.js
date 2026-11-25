const box = document.querySelector('[data-assistant]');

if (box) {
  const log = box.querySelector('[data-chat-log]');
  const body = box.querySelector('[data-chat-body]');
  const list = box.querySelector('[data-chat-list]');
  const starters = box.querySelector('[data-chat-starters]');
  const titleEl = box.querySelector('[data-chat-title]');
  const historyBtn = box.querySelector('[data-chat-history]');
  const form = box.querySelector('[data-chat-form]');
  const field = form.querySelector('textarea[name=question]');
  const button = form.querySelector('button[type=submit]');
  const status = box.querySelector('[data-chat-status]');
  const picker = box.querySelector('[data-chat-files]');
  const chips = box.querySelector('[data-chat-chips]');
  const memoryKey = 'kaido-chat-' + box.dataset.company;
  const pageTruck = () => { const el = document.querySelector('[data-page-truck]'); return el ? el.dataset.pageTruck : ''; };
  const remember = (id) => { try { if (id) localStorage.setItem(memoryKey, String(id)); else localStorage.removeItem(memoryKey); } catch (err) { } };
  const recall = () => { try { return localStorage.getItem(memoryKey) || ''; } catch (err) { return ''; } };
  let conversationId = recall();
  let busy = false;
  let loaded = false;
  let pending = [];

  const bubble = (role, text, files) => {
    const item = document.createElement('div');
    item.className = 'chat-msg ' + role;
    const who = document.createElement('div');
    who.className = 'chat-who';
    who.textContent = role === 'user' ? 'You' : 'Claude';
    const body = document.createElement('div');
    body.className = 'chat-text';
    body.textContent = text;
    item.append(who, body);
    if (files && files.length) {
      const strip = document.createElement('div');
      strip.className = 'chat-files';
      for (const f of files) {
        const a = document.createElement('a');
        a.target = '_blank'; a.rel = 'noopener';
        a.href = f.id ? '/assistant/files/' + f.id : (f.url || '#');
        if (f.type && f.type.startsWith('image/')) {
          const img = document.createElement('img');
          img.src = a.href; img.alt = f.name; img.loading = 'lazy';
          a.append(img);
        } else {
          a.className = 'chat-file-pdf'; a.textContent = f.name;
        }
        strip.append(a);
      }
      item.append(strip);
    }
    if (role === 'assistant') {
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'btn ghost small';
      copy.textContent = 'Copy';
      copy.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(text);
          copy.textContent = 'Copied';
        } catch (err) {
          const range = document.createRange();
          range.selectNodeContents(body);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          copy.textContent = 'Selected, press Ctrl+C';
        }
      });
      item.append(copy);
    }
    log.append(item);
    log.scrollTop = log.scrollHeight;
  };

  const setStatus = (text) => { status.textContent = text || ''; };
  const syncStarters = () => { starters.hidden = log.children.length > 0; };

  const drawChips = () => {
    chips.textContent = '';
    chips.hidden = !pending.length;
    pending.forEach((file, index) => {
      const chip = document.createElement('span');
      chip.className = 'chat-chip';
      chip.textContent = file.name;
      const x = document.createElement('button');
      x.type = 'button'; x.textContent = '×'; x.setAttribute('aria-label', 'Remove ' + file.name);
      x.addEventListener('click', () => { pending.splice(index, 1); drawChips(); });
      chip.append(x);
      chips.append(chip);
    });
  };
  picker.addEventListener('change', () => {
    pending = pending.concat(Array.from(picker.files)).slice(0, 5);
    picker.value = '';
    drawChips();
  });

  const showChat = () => { list.hidden = true; body.hidden = false; historyBtn.setAttribute('aria-expanded', 'false'); };

  const openConversation = async (id) => {
    log.textContent = '';
    conversationId = id ? String(id) : '';
    remember(conversationId);
    titleEl.textContent = 'Claude';
    showChat();
    if (!conversationId) { syncStarters(); return; }
    try {
      const response = await fetch('/assistant/c/' + conversationId, { credentials: 'same-origin' });
      if (!response.ok) { conversationId = ''; remember(''); syncStarters(); return; }
      const data = await response.json();
      titleEl.textContent = data.title || 'Claude';
      for (const m of data.messages || []) bubble(m.role, m.content, m.files);
    } catch (err) {
      setStatus('Could not load the conversation.');
    }
    syncStarters();
  };

  const showHistory = async () => {
    body.hidden = true; list.hidden = false; historyBtn.setAttribute('aria-expanded', 'true');
    list.textContent = 'Loading…';
    try {
      const response = await fetch('/assistant/conversations', { credentials: 'same-origin' });
      const data = await response.json();
      list.textContent = '';
      if (!(data.conversations || []).length) { const p = document.createElement('p'); p.className = 'subtle'; p.textContent = 'No chats yet.'; list.append(p); }
      for (const c of data.conversations || []) {
        const row = document.createElement('div');
        row.className = 'chat-history-row' + (String(c.id) === conversationId ? ' on' : '');
        const open = document.createElement('button');
        open.type = 'button'; open.className = 'chat-history-open';
        const t = document.createElement('span'); t.textContent = c.title;
        const w = document.createElement('small'); w.textContent = c.when;
        open.append(t, w);
        open.addEventListener('click', () => openConversation(c.id));
        const del = document.createElement('button');
        del.type = 'button'; del.className = 'chat-history-del'; del.textContent = 'Delete'; del.setAttribute('aria-label', 'Delete chat ' + c.title);
        del.addEventListener('click', async () => {
          if (!window.confirm('Delete this chat and its attachments?')) return;
          const payload = new FormData();
          payload.append('csrf', box.dataset.csrf);
          await fetch('/assistant/c/' + c.id + '/delete', { method: 'POST', body: payload, credentials: 'same-origin' });
          if (String(c.id) === conversationId) { conversationId = ''; remember(''); log.textContent = ''; titleEl.textContent = 'Claude'; }
          row.remove();
        });
        row.append(open, del);
        list.append(row);
      }
    } catch (err) {
      list.textContent = 'Could not load your chats.';
    }
  };

  const ask = async (question) => {
    if (busy || (!question.trim() && !pending.length)) return;
    busy = true;
    button.disabled = true;
    showChat();
    setStatus('Claude is thinking…');
    const sending = pending;
    bubble('user', question || 'Take a look at what I attached.', sending.map((f) => ({ name: f.name, type: f.type, url: URL.createObjectURL(f) })));
    syncStarters();
    field.value = '';
    pending = []; drawChips();
    const payload = new FormData();
    payload.append('csrf', box.dataset.csrf);
    payload.append('question', question);
    payload.append('page_truck_id', pageTruck());
    payload.append('conversation_id', conversationId);
    for (const f of sending) payload.append('files', f);
    const undo = () => { log.lastElementChild.remove(); field.value = question; pending = sending; drawChips(); syncStarters(); };
    try {
      const response = await fetch('/assistant', { method: 'POST', body: payload, credentials: 'same-origin' });
      const data = await response.json();
      if (data.answer) {
        conversationId = String(data.conversation_id); remember(conversationId);
        titleEl.textContent = data.title || 'Claude';
        bubble('assistant', data.answer);
        setStatus('');
      } else {
        undo();
        setStatus(data.error || 'No answer came back.');
      }
    } catch (err) {
      undo();
      setStatus('Could not reach the server. Try again.');
    }
    busy = false;
    button.disabled = false;
  };

  form.addEventListener('submit', (event) => { event.preventDefault(); ask(field.value); });
  field.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); ask(field.value); }
  });
  for (const starter of box.querySelectorAll('[data-chat-ask]')) starter.addEventListener('click', () => ask(starter.dataset.chatAsk));
  box.querySelector('[data-chat-new]').addEventListener('click', () => { openConversation(''); field.focus(); });
  historyBtn.addEventListener('click', () => (list.hidden ? showHistory() : showChat()));

  const opener = document.querySelector('[data-assistant-open]');
  const open = () => {
    box.hidden = false;
    if (opener) opener.setAttribute('aria-expanded', 'true');
    if (!loaded) { loaded = true; openConversation(conversationId); }
    field.focus();
  };
  const close = () => {
    box.hidden = true;
    if (opener) { opener.setAttribute('aria-expanded', 'false'); opener.focus(); }
  };
  for (const b of document.querySelectorAll('[data-assistant-open]')) b.addEventListener('click', () => (box.hidden ? open() : close()));
  box.querySelector('[data-assistant-close]').addEventListener('click', close);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !box.hidden) close(); });
}
