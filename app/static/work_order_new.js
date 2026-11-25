const woNew = document.querySelector('form[data-wo-new]');

if (woNew) {
  const radios = woNew.querySelectorAll('input[name=asset_type]');
  const truckPick = woNew.querySelector('[data-for=truck] select[name=truck_id]');
  const outside = woNew.querySelector('#outside-truck');
  const trailerPick = woNew.querySelector('select[name=trailer_id]');
  const where = woNew.querySelector('input[name=location]');
  const trailerTruck = woNew.querySelector('[data-for=trailer] select[name=truck_id]');

  const sync = () => {
    const asset = [...radios].find((r) => r.checked).value;
    for (const box of woNew.querySelectorAll('[data-for]')) {
      const on = box.dataset.for === asset;
      box.hidden = !on;
      for (const input of box.querySelectorAll('select, input')) input.disabled = !on;
    }
    outside.hidden = !(asset === 'truck' && truckPick.value === 'outside');
    for (const input of outside.querySelectorAll('input')) input.disabled = outside.hidden;
  };

  for (const radio of radios) radio.addEventListener('change', sync);
  truckPick.addEventListener('change', sync);
  trailerPick.addEventListener('change', () => {
    const option = trailerPick.selectedOptions[0];
    if (!option) return;
    if (trailerTruck && option.dataset.truck) trailerTruck.value = option.dataset.truck;
    if (where && !where.value && option.dataset.where) where.value = option.dataset.where;
  });
  sync();
}
