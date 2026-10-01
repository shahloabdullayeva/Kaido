const ptiForm = document.querySelector('form[data-pti]');
if (ptiForm) {
  const syncItem = (item) => {
    const picked = item.querySelector('input[type=radio]:checked');
    const box = item.querySelector('[data-defect]');
    const isDefect = picked && picked.value === 'defect';
    item.classList.toggle('is-defect', isDefect);
    box.hidden = !isDefect;
    const note = box.querySelector('input[name^=note_]');
    if (note) note.required = isDefect;
  };
  const syncSafe = () => {
    const any = ptiForm.querySelector('[data-item] input[value=defect]:checked');
    const safe = ptiForm.querySelector('[data-safe]');
    safe.hidden = !any;
    for (const radio of safe.querySelectorAll('input')) radio.required = Boolean(any);
  };
  for (const item of ptiForm.querySelectorAll('[data-item]')) {
    syncItem(item);
    item.addEventListener('change', () => { syncItem(item); syncSafe(); });
  }
  syncSafe();

  const pick = ptiForm.querySelector('[data-driver-pick]');
  const typed = ptiForm.querySelector('[data-driver-typed]');
  const syncDriver = () => {
    typed.hidden = Boolean(pick.value);
    typed.querySelector('input').required = !pick.value;
  };
  pick.addEventListener('change', syncDriver);
  syncDriver();

  const shrink = (file) => new Promise((resolve) => {
    if (!file.type.startsWith('image/') || file.size < 400000) return resolve(file);
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => resolve(blob ? new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' }) : file), 'image/jpeg', 0.82);
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });

  for (const input of ptiForm.querySelectorAll('input[type=file]')) {
    input.addEventListener('change', async () => {
      if (typeof DataTransfer === 'undefined') return;
      const label = input.closest('label');
      const out = new DataTransfer();
      for (const file of input.files) out.items.add(await shrink(file));
      input.files = out.files;
      if (label) label.dataset.count = input.files.length ? `${input.files.length} added` : '';
    });
  }
}
