const workOrder = document.querySelector('form.work-order');

if (workOrder) {
  const table = workOrder.querySelector('#parts-table tbody');
  const template = table.querySelector('tr[data-template]');
  const addPart = workOrder.querySelector('#add-part');
  const labor = workOrder.querySelector('input[name=labor_cost]');
  const tax = workOrder.querySelector('input[name=tax]');
  const total = workOrder.querySelector('input[name=cost]');
  const trucks = workOrder.querySelector('select[name=truck_id]');
  const drivers = workOrder.querySelector('select[name=driver_id]');
  const contact = workOrder.querySelector('input[name=driver_contact]');
  const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
  const number = (input) => {
    const value = parseFloat(input && input.value);
    return Number.isFinite(value) ? value : null;
  };

  const recalc = () => {
    let sum = 0;
    let itemized = false;
    for (const row of table.querySelectorAll('tr[data-part]:not([hidden])')) {
      const qty = number(row.querySelector('input[name=part_qty]'));
      const price = number(row.querySelector('input[name=part_price]'));
      const cell = row.querySelector('[data-amount]');
      if (price === null) {
        cell.textContent = '';
        continue;
      }
      itemized = true;
      const amount = (qty && qty > 0 ? qty : 1) * price;
      sum += amount;
      cell.textContent = money.format(amount);
    }
    if (number(labor) !== null || number(tax) !== null) itemized = true;
    if (itemized) {
      total.value = (sum + (number(labor) || 0) + (number(tax) || 0)).toFixed(2);
      total.readOnly = true;
    } else {
      total.readOnly = false;
    }
  };

  const wireRow = (row) => {
    row.querySelector('[data-remove-part]').addEventListener('click', () => {
      if (table.querySelectorAll('tr[data-part]:not([hidden])').length === 1) {
        for (const input of row.querySelectorAll('input')) input.value = input.name === 'part_qty' ? '1' : '';
      } else {
        row.remove();
      }
      recalc();
    });
  };

  for (const row of table.querySelectorAll('tr[data-part]')) wireRow(row);
  addPart.addEventListener('click', () => {
    const row = template.cloneNode(true);
    row.hidden = false;
    row.removeAttribute('data-template');
    for (const input of row.querySelectorAll('input')) {
      input.disabled = false;
      input.value = input.name === 'part_qty' ? '1' : '';
    }
    table.append(row);
    wireRow(row);
    row.querySelector('input[name=part_name]').focus();
  });
  workOrder.addEventListener('input', (event) => {
    if (event.target.closest('#parts-table') || event.target === labor || event.target === tax) recalc();
  });

  let contactTouched = Boolean(contact && contact.value);
  if (contact) contact.addEventListener('input', () => { contactTouched = Boolean(contact.value); });
  const fillContact = () => {
    if (!contact || !drivers || contactTouched) return;
    const option = drivers.selectedOptions[0];
    contact.value = (option && option.dataset.phone) || '';
  };
  if (drivers) drivers.addEventListener('change', fillContact);
  if (trucks) trucks.addEventListener('change', fillContact);

  const fileInput = workOrder.querySelector('input[name=invoice_files]');
  for (const link of document.querySelectorAll('[data-upload-invoice]')) {
    link.addEventListener('click', (event) => {
      if (!fileInput) return;
      event.preventDefault();
      fileInput.scrollIntoView({ block: 'center' });
      fileInput.click();
    });
  }
  if (fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length && workOrder.querySelector('[name=description]').value.trim()) {
        workOrder.querySelector('.form-actions .btn').textContent = 'Save and upload ' + fileInput.files.length + ' file' + (fileInput.files.length > 1 ? 's' : '');
      }
    });
  }

  recalc();
}
