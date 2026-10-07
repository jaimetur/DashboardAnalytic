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

  globalThis.operatorVendorPairs = {pairedValue, mirrorValues};

  // Native multi-selects marked with data-operator-vendor-pair="operator_vendor" or "vendor_operator"
  // mirror their selection into the other one of the nearest container that holds both.
  let mirroring = false;
  document.addEventListener('change', (event) => {
    const source = event.target;
    if (mirroring || !(source instanceof HTMLSelectElement) || !source.dataset.operatorVendorPair) return;
    const partnerKind = source.dataset.operatorVendorPair === 'operator_vendor' ? 'vendor_operator' : 'operator_vendor';
    let partner = null;
    for (let scope = source.parentElement; scope && !partner; scope = scope.parentElement) {
      partner = scope.querySelector(`select[data-operator-vendor-pair="${partnerKind}"]`);
    }
    if (!partner) return;
    const selected = [...source.selectedOptions].filter((option) => option.value).map((option) => option.value);
    const wanted = new Set(mirrorValues(selected, [...partner.options].map((option) => option.value)));
    const unchanged = [...partner.options].every((option) => option.selected === wanted.has(option.value))
      && partner.dataset.multiselectDynamicAllSelected === source.dataset.multiselectDynamicAllSelected;
    if (unchanged) return;
    [...partner.options].forEach((option) => { option.selected = wanted.has(option.value); });
    if (source.dataset.multiselectDynamicAllSelected === 'true') partner.dataset.multiselectDynamicAllSelected = 'true';
    else delete partner.dataset.multiselectDynamicAllSelected;
    mirroring = true;
    try {
      partner.dispatchEvent(new Event('change', {bubbles: true}));
      partner.dispatchEvent(new Event('input', {bubbles: true}));
    } finally {
      mirroring = false;
    }
  });
}());
