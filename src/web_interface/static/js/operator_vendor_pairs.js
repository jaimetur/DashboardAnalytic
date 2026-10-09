// Operator_Vendor and Vendor_Operator hold the same values written the other way round
// ("VF_UK_Ericsson" and "Ericsson_VF_UK"; "EE - All" in both), so their filters stay in sync.
(function () {
  // The value of `candidates` that is `value` the other way round, or null.
  function pairedValue(value, candidates) {
    const text = String(value);
    for (let index = text.indexOf('_'); index > 0; index = text.indexOf('_', index + 1)) {
      const swapped = `${text.slice(index + 1)}_${text.slice(0, index)}`;
      if (candidates.has(swapped)) return swapped;
    }
    return candidates.has(text) ? text : null;
  }

  // The values of `targetValues` whose pair is one of `selected`.
  function mirrorValues(selected, targetValues) {
    const chosen = new Set([...selected].map(String));
    return [...targetValues].map(String).filter((value) => pairedValue(value, chosen) !== null);
  }

  // The Vendor of an Operator_Vendor value ("VF_UK_Ericsson" is Ericsson; "EE - All" is itself), or null.
  function vendorOf(value, vendors) {
    const text = String(value);
    let found = vendors.has(text) ? text : null;
    for (const vendor of vendors) {
      if (text.endsWith(`_${vendor}`) && (!found || vendor.length > found.length)) found = vendor;
    }
    return found;
  }

  globalThis.operatorVendorPairs = {pairedValue, mirrorValues, vendorOf};

  // Native multi-selects marked with data-operator-vendor-pair="operator_vendor" or "vendor_operator"
  // mirror their selection into the other one of the nearest container that holds both. A Vendor
  // select marked data-operator-vendor-pair="vendor" stays in sync with them too: choosing Vendors
  // chooses their Operator_Vendor values, and choosing Operator_Vendor values chooses their Vendors.
  let mirroring = false;
  const nearest = (source, kind) => {
    for (let scope = source.parentElement; scope; scope = scope.parentElement) {
      const found = scope.querySelector(`select[data-operator-vendor-pair="${kind}"]`);
      if (found) return found;
    }
    return null;
  };
  const values = (select) => [...select.options].map((option) => option.value);
  const selectedValues = (select) => [...select.selectedOptions].filter((option) => option.value).map((option) => option.value);
  // Selects `wanted` in `target`, following the "All values" state of `source`; true when it changed.
  const apply = (target, wanted, source) => {
    const unchanged = [...target.options].every((option) => option.selected === wanted.has(option.value))
      && target.dataset.multiselectDynamicAllSelected === source.dataset.multiselectDynamicAllSelected;
    if (unchanged) return false;
    [...target.options].forEach((option) => { option.selected = wanted.has(option.value); });
    if (source.dataset.multiselectDynamicAllSelected === 'true') target.dataset.multiselectDynamicAllSelected = 'true';
    else delete target.dataset.multiselectDynamicAllSelected;
    return true;
  };
  const notify = (targets) => {
    mirroring = true;
    try {
      targets.forEach((target) => {
        target.dispatchEvent(new Event('change', {bubbles: true}));
        target.dispatchEvent(new Event('input', {bubbles: true}));
      });
    } finally {
      mirroring = false;
    }
  };
  document.addEventListener('change', (event) => {
    const source = event.target;
    if (mirroring || !(source instanceof HTMLSelectElement) || !source.dataset.operatorVendorPair) return;
    const kind = source.dataset.operatorVendorPair;
    const operatorVendor = kind === 'operator_vendor' ? source : nearest(source, 'operator_vendor');
    const vendorOperator = kind === 'vendor_operator' ? source : nearest(source, 'vendor_operator');
    const vendor = kind === 'vendor' ? source : nearest(source, 'vendor');
    const changed = [];
    // The Operator_Vendor values now chosen.
    let chosenPairs = null;
    if (kind === 'vendor') {
      if (operatorVendor) {
        const vendors = new Set(selectedValues(source));
        const known = new Set(values(source));
        chosenPairs = values(operatorVendor).filter((value) => vendors.has(vendorOf(value, known)));
        if (apply(operatorVendor, new Set(chosenPairs), source)) changed.push(operatorVendor);
      }
    } else {
      const partner = kind === 'operator_vendor' ? vendorOperator : operatorVendor;
      if (partner && apply(partner, new Set(mirrorValues(selectedValues(source), values(partner))), source)) changed.push(partner);
      if (operatorVendor) chosenPairs = selectedValues(operatorVendor);
      if (vendor && chosenPairs) {
        const known = new Set(values(vendor));
        if (apply(vendor, new Set(chosenPairs.map((value) => vendorOf(value, known)).filter(Boolean)), source)) changed.push(vendor);
      }
    }
    if (kind === 'vendor' && vendorOperator && chosenPairs) {
      if (apply(vendorOperator, new Set(mirrorValues(chosenPairs, values(vendorOperator))), source)) changed.push(vendorOperator);
    }
    if (changed.length) notify(changed);
  });
}());
