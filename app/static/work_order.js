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
  const invoiceStatus = workOrder.querySelector('[data-invoice-status]');
  const setIfEmpty = (name, value) => {
    const input = workOrder.querySelector(`[name=${name}]`);
    if (!input || value === null || value === undefined || value === '' || value === 0) return;
    if (input.value && input.value !== '') return;
    input.value = value;
  };
  const filledParts = () => [...table.querySelectorAll('tr[data-part]:not([hidden])')]
    .filter((row) => row.querySelector('input[name=part_name]').value.trim());
  const fillParts = (parts) => {
    if (!parts.length || filledParts().length) return;
    for (const row of table.querySelectorAll('tr[data-part]:not([hidden])')) if (!row.hasAttribute('data-template')) row.remove();
    const blank = table.querySelector('tr[data-template]');
    parts.forEach((part, index) => {
      let row = blank;
      if (index > 0 || blank.hidden) {
        row = template.cloneNode(true);
        row.removeAttribute('data-template');
        table.append(row);
        wireRow(row);
      }
      row.hidden = false;
      for (const input of row.querySelectorAll('input')) input.disabled = false;
      row.querySelector('input[name=part_name]').value = part.name;
      row.querySelector('input[name=part_number]').value = part.part_number || '';
      row.querySelector('input[name=part_qty]').value = part.quantity || 1;
      row.querySelector('input[name=part_price]').value = part.unit_price;
    });
  };
  const readInvoice = async () => {
    const files = [...fileInput.files].filter((f) => f.type === 'application/pdf' || f.type.startsWith('image/') || /\.pdf$/i.test(f.name));
    if (!invoiceStatus || !files.length) return;
    const body = new FormData();
    body.append('csrf', workOrder.querySelector('input[name=csrf]').value);
    for (const file of files.slice(0, 3)) body.append('invoice_files', file);
    invoiceStatus.hidden = false;
    invoiceStatus.textContent = 'Reading the invoice...';
    try {
      const response = await fetch('/maintenance/invoice/read', { method: 'POST', body, credentials: 'same-origin' });
      const data = await response.json();
      if (!data.ok) {
        invoiceStatus.textContent = data.message;
        return;
      }
      const inv = data.invoice;
      fillParts(inv.parts || []);
      setIfEmpty('labor_cost', inv.labor ? inv.labor.toFixed(2) : null);
      setIfEmpty('tax', inv.tax_and_fees ? inv.tax_and_fees.toFixed(2) : null);
      setIfEmpty('invoice_no', inv.invoice_number);
      setIfEmpty('paid_with', inv.paid_with);
      setIfEmpty('next_due_on', inv.next_due_date);
      setIfEmpty('next_due_odometer', inv.next_due_odometer);
      recalc();
      if (inv.total && !total.readOnly) total.value = inv.total.toFixed(2);
      const off = inv.total && Math.abs(parseFloat(total.value || 0) - inv.total) > 0.01;
      invoiceStatus.textContent = off
        ? `Filled from the invoice. Its total is ${money.format(inv.total)}, check the lines.`
        : 'Filled from the invoice. Check it, then save.';
    } catch (error) {
      invoiceStatus.textContent = 'Could not read the invoice. Fill it in by hand.';
    }
  };
  if (fileInput) {
    fileInput.addEventListener('change', readInvoice);
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length && workOrder.querySelector('[name=description]').value.trim()) {
        workOrder.querySelector('.form-actions .btn').textContent = 'Save and upload ' + fileInput.files.length + ' file' + (fileInput.files.length > 1 ? 's' : '');
      }
    });
  }

  recalc();
}

for (const attach of document.querySelectorAll('.attach')) {
  const input = attach.querySelector('input[type=file]');
  const name = attach.querySelector('[data-attach-name]');
  input.addEventListener('change', () => { name.textContent = input.files.length ? input.files[0].name : 'Attach'; });
}
