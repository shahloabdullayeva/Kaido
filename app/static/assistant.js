const box = document.querySelector('[data-assistant]');

if (box) {
  const log = box.querySelector('[data-chat-log]');
  const form = box.querySelector('[data-chat-form]');
  const field = form.querySelector('textarea[name=question]');
  const button = form.querySelector('button[type=submit]');
  const status = box.querySelector('[data-chat-status]');
  const truckSelect = document.querySelector('select[name=truck_id]');
  let truckId = box.dataset.truckId;
  let busy = false;

  const bubble = (role, text) => {
    const item = document.createElement('div');
    item.className = 'chat-msg ' + role;
    const who = document.createElement('div');
    who.className = 'chat-who';
    who.textContent = role === 'user' ? 'You' : 'Claude';
    const body = document.createElement('div');
    body.className = 'chat-text';
    body.textContent = text;
    item.append(who, body);
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

  const usable = () => truckId && /^\d+$/.test(truckId);

  const refresh = async () => {
    log.textContent = '';
    box.hidden = !usable();
    if (!usable()) return;
    try {
      const response = await fetch('/assistant/' + truckId, { credentials: 'same-origin' });
      const data = await response.json();
      for (const message of data.messages || []) bubble(message.role, message.content);
      if (data.available === false) setStatus('The assistant is off: no Anthropic key is set.');
    } catch (err) {
      setStatus('Could not load the conversation.');
    }
  };

  const ask = async (question) => {
    if (busy || !usable() || !question.trim()) return;
    busy = true;
    button.disabled = true;
    setStatus('Claude is thinking…');
    bubble('user', question);
    field.value = '';
    const payload = new FormData();
    payload.append('csrf', box.dataset.csrf);
    payload.append('question', question);
    try {
      const response = await fetch('/assistant/' + truckId, { method: 'POST', body: payload, credentials: 'same-origin' });
      const data = await response.json();
      if (data.answer) {
        bubble('assistant', data.answer);
        setStatus('');
      } else {
        log.lastElementChild.remove();
        field.value = question;
        setStatus(data.error || 'No answer came back.');
      }
    } catch (err) {
      log.lastElementChild.remove();
      field.value = question;
      setStatus('Could not reach the server. Try again.');
    }
    busy = false;
    button.disabled = false;
  };

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    ask(field.value);
  });
  field.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      ask(field.value);
    }
  });
  for (const starter of box.querySelectorAll('[data-chat-ask]')) {
    starter.addEventListener('click', () => ask(starter.dataset.chatAsk));
  }
  box.querySelector('[data-chat-clear]').addEventListener('click', async () => {
    if (!usable()) return;
    const payload = new FormData();
    payload.append('csrf', box.dataset.csrf);
    await fetch('/assistant/' + truckId + '/clear', { method: 'POST', body: payload, credentials: 'same-origin' });
    log.textContent = '';
    setStatus('Started over.');
  });
  if (truckSelect) {
    truckSelect.addEventListener('change', () => {
      truckId = truckSelect.value;
      refresh();
    });
    if (!truckId) truckId = truckSelect.value;
  }
  refresh();
}
