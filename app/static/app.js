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

for (const form of document.querySelectorAll('form[data-truck-fill]')) {
  const trucks = form.querySelector('select[name=truck_id]');
  const drivers = form.querySelector('select[name=driver_id]');
  const summary = form.querySelector('#truck-summary');
  const odometer = form.querySelector('input[name=odometer]');
  const outsideTruck = form.querySelector('#outside-truck');
  const outsideDriver = form.querySelector('#outside-driver');
  if (!trucks) continue;
  let driverTouched = false;
  if (drivers) drivers.addEventListener('change', () => { driverTouched = true; showOutside(); });
  const showOutside = () => {
    if (outsideTruck) {
      outsideTruck.hidden = trucks.value !== 'outside';
      const unit = outsideTruck.querySelector('input[name=outside_unit]');
      if (unit) unit.required = trucks.value === 'outside';
    }
    if (outsideDriver && drivers) {
      outsideDriver.hidden = drivers.value !== 'outside';
      const name = outsideDriver.querySelector('input[name=outside_driver_name]');
      if (name) name.required = drivers.value === 'outside';
    }
  };
  const fill = (touchOdometer) => {
    const option = trucks.selectedOptions[0];
    if (summary) {
      const label = option && option.dataset.truck;
      summary.textContent = trucks.value === 'outside'
        ? 'Fill in the outside truck below. It is saved so you can pick it next time.'
        : (label || 'Any truck, yours or not.');
    }
    if (drivers && !driverTouched && option && option.dataset.driverId !== undefined) {
      drivers.value = option.dataset.driverId || '';
    }
    if (touchOdometer && odometer && option && option.dataset.odometer && !odometer.value) {
      odometer.value = option.dataset.odometer;
    }
    showOutside();
  };
  trucks.addEventListener('change', () => fill(true));
  if (!drivers || !drivers.value) fill(false); else showOutside();
}

for (const form of document.querySelectorAll('form[data-autosubmit]')) {
  for (const control of form.querySelectorAll('select')) {
    control.addEventListener('change', () => form.requestSubmit());
  }
}
