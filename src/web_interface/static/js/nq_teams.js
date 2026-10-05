/* Workspace Config: Non-Qualified Calls teams and their members. */
(() => {
  'use strict';

  const host = document.querySelector('[data-nq-teams]');
  if (!host) return;
  const status = document.querySelector('[data-nq-teams-status]');
  const actions = document.querySelector('[data-nq-teams-actions]');
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const say = (message, tone = '') => { status.textContent = message || ''; status.dataset.tone = tone; };
  let users = [];
  let canEdit = false;

  // A filterable checklist of the workspace users; getValue() returns the members.
  const membersPicker = (selected) => {
    const picker = node('details', undefined, 'nq-members');
    const summary = node('summary');
    const caption = node('span');
    summary.append(caption);
    const menu = node('div', undefined, 'nq-members-menu');
    const search = node('input');
    search.type = 'search'; search.placeholder = 'Filter users…'; search.setAttribute('aria-label', 'Filter users');
    menu.append(search);
    const chosen = new Set(selected.map((name) => name.toLocaleLowerCase()));
    const boxes = users.map((name) => {
      const row = node('label', undefined, 'nq-members-option');
      const box = node('input'); box.type = 'checkbox'; box.value = name; box.checked = chosen.has(name.toLocaleLowerCase()); box.disabled = !canEdit;
      row.append(box, node('span', name));
      menu.append(row);
      return box;
    });
    if (!users.length) menu.append(node('p', 'No users can open this workspace.', 'form-note'));
    const refresh = () => {
      const names = boxes.filter((box) => box.checked).map((box) => box.value);
      caption.textContent = names.length ? `${names.length} member${names.length === 1 ? '' : 's'}: ${names.join(', ')}` : 'No members (every user)';
      summary.title = caption.textContent;
    };
    menu.addEventListener('change', refresh);
    search.addEventListener('input', () => {
      const query = search.value.trim().toLocaleLowerCase();
      boxes.forEach((box) => { box.parentElement.hidden = Boolean(query) && !box.value.toLocaleLowerCase().includes(query); });
    });
    picker.addEventListener('toggle', () => {
      if (!picker.open) return;
      host.querySelectorAll('details.nq-members[open]').forEach((other) => { if (other !== picker) other.open = false; });
      search.focus();
    });
    picker.append(summary, menu);
    refresh();
    picker.getValue = () => boxes.filter((box) => box.checked).map((box) => box.value);
    return picker;
  };

  const teamRow = (team = {name: '', color: '#0f6f7d', members: []}) => {
    const row = node('div', undefined, 'nq-team-row');
    row.dataset.previous = team.name || '';
    const color = node('input'); color.type = 'color'; color.value = team.color || '#0f6f7d'; color.disabled = !canEdit;
    color.setAttribute('aria-label', 'Team colour');
    const name = node('input'); name.type = 'text'; name.value = team.name || ''; name.maxLength = 60; name.placeholder = 'Team name';
    name.disabled = !canEdit; name.setAttribute('aria-label', 'Team name');
    const members = membersPicker(team.members || []);
    row.append(color, name, members);
    if (canEdit) {
      const move = (offset) => {
        const sibling = offset < 0 ? row.previousElementSibling : row.nextElementSibling;
        if (sibling) (offset < 0 ? sibling.before(row) : sibling.after(row));
      };
      [['↑', 'Move up', () => move(-1)], ['↓', 'Move down', () => move(1)], ['×', 'Remove team', () => row.remove()]].forEach(([label, title, action]) => {
        const button = node('button', label, 'nq-icon-action');
        button.type = 'button'; button.title = title; button.setAttribute('aria-label', title);
        button.addEventListener('click', action);
        row.append(button);
      });
    }
    row.getValue = () => ({name: name.value.trim(), color: color.value, previous: row.dataset.previous, members: members.getValue()});
    return row;
  };

  const render = (teams) => {
    host.replaceChildren(...teams.map(teamRow));
    if (!teams.length) host.append(node('p', 'No teams yet.', 'form-note'));
    actions.hidden = !canEdit;
  };

  const load = async () => {
    try {
      const response = await fetch('/api/non-qualified-calls/teams', {credentials: 'same-origin'});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to load the teams.');
      users = payload.users || [];
      canEdit = Boolean(payload.can_edit);
      render(payload.teams || []);
      say(canEdit ? '' : 'The user-viewer role can read the teams but cannot change them.');
    } catch (error) {
      host.replaceChildren();
      say(error.message, 'error');
    }
  };

  document.querySelector('[data-nq-teams-add]')?.addEventListener('click', () => {
    host.querySelector('.form-note')?.remove();
    const row = teamRow();
    host.append(row);
    row.querySelector('input[type="text"]').focus();
  });
  document.querySelector('[data-nq-teams-save]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    say('Saving teams…');
    try {
      const response = await fetch('/api/non-qualified-calls/teams', {
        method: 'PUT', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({teams: [...host.querySelectorAll('.nq-team-row')].map((row) => row.getValue())}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Unable to save the teams.');
      render(payload.teams || []);
      say('Teams saved.', 'done');
    } catch (error) {
      say(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  });
  document.addEventListener('click', (event) => {
    host.querySelectorAll('details.nq-members[open]').forEach((picker) => { if (!picker.contains(event.target)) picker.open = false; });
  });
  load();
})();
