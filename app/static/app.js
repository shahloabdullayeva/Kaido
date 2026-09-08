document.addEventListener('submit', (event) => {
  const form = event.target;
  const message = form.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
    return;
  }
  const button = form.querySelector('button[type=submit], button:not([type])');
  if (button && !form.dataset.noBusy) {
    setTimeout(() => { button.disabled = true; button.textContent = button.dataset.busy || 'Working…'; }, 0);
  }
});

const code = document.querySelector('input[name=code]');
if (code) {
  code.focus();
  code.addEventListener('input', () => {
    code.value = code.value.replace(/\D/g, '').slice(0, 6);
    if (code.value.length === 6) code.form.requestSubmit();
  });
}

for (const input of document.querySelectorAll('input[data-filter]')) {
  input.addEventListener('input', () => {
    const term = input.value.trim().toLowerCase();
    const table = document.querySelector(input.dataset.filter);
    if (!table) return;
    for (const row of table.querySelectorAll('tbody tr')) {
      row.hidden = term.length > 0 && !row.textContent.toLowerCase().includes(term);
    }
  });
}

for (const form of document.querySelectorAll('form[data-autosubmit]')) {
  for (const control of form.querySelectorAll('select')) {
    control.addEventListener('change', () => form.requestSubmit());
  }
}
