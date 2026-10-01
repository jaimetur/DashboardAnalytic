from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORING_TEMPLATE = PROJECT_ROOT / 'src/web_interface/templates/scoring.html'
SCORING_SCRIPT = PROJECT_ROOT / 'src/web_interface/static/js/scoring.js'


def test_scoring_selection_loads_from_server_before_enabling_controls():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert "root.dataset.selectionUrl || '/api/scoring/selection'" in script
    assert 'data-selection-url="/api/scoring/selection"' in template
    assert "const body = await requestJson(selectionUrl);" in script
    assert 'applySavedCalculationSelection(body.selection);' in script
    assert 'selectionPersisted = body.persisted !== false;' in script
    assert 'if (!selectionPersisted) {' in script
    assert 'await persistCalculationSelection({force: true});' in script
    assert "calculationPanel.inert = true;" in script
    assert "calculationPanel.inert = false;" in script
    assert 'loadCalculationSelection();' in script
    assert 'localStorage' not in script


def test_scoring_selection_roundtrips_explicit_empty_filters_and_methodology():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')
    template = SCORING_TEMPLATE.read_text(encoding='utf-8')

    assert "const selectionFieldOrder = ['Region', 'City', 'Operator', 'Vendor', 'Campaign'];" in script
    assert "context_filters: Object.fromEntries(selectionFieldOrder.map(key => [key, filters[key] || []]))" in script
    assert "scoring_profile_id: String(scoringProfileSelect?.value || activeProfileId)" in script
    assert "const requested = filters[key] ?? filters[key.toLowerCase()] ?? [];" in script
    assert "option.selected = !option.disabled && selected.has(option.value.toLocaleLowerCase())" in script
    assert '.scoring-note[data-kind="warning"]' in template


def test_scoring_selection_saves_are_debounced_serialized_and_flushed_on_navigation():
    script = SCORING_SCRIPT.read_text(encoding='utf-8')

    assert 'function scheduleSelectionSave()' in script
    assert '}, 250);' in script
    assert 'selectionSaveChain = selectionSaveChain.catch(() => null).then(async () =>' in script
    assert 'if (!force && key === lastQueuedSelectionKey) return selectionSaveChain;' in script
    assert 'if (key === lastSavedSelectionKey || key === lastQueuedSelectionKey)' not in script
    assert 'client_id: selectionClientId, client_revision: clientRevision' in script
    assert "window.addEventListener('pagehide', flushSelectionSaveOnPageHide);" in script
    assert 'keepalive: true,' in script
    assert 'if (selectionPersisted && key === lastSavedSelectionKey && key === lastQueuedSelectionKey) return;' in script
    assert 'if (!selectionLoaded || restoringSelection || !selectionDirty) return;' in script
