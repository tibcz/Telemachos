// static/js/profile.js
//
// The person using this copy of the app.
//
// Telemachos is single-user, so there is no sign-in. Before this, the sidebar
// showed a hardcoded "User", settings showed "Unknown", and the account panel
// offered a sign-out, a password change and two-factor setup, none of which
// could do anything without authentication behind them. That combination
// reads as broken software.
//
// Now the app knows a name (seeded from the macOS account on first run), shows
// it, lets you change it, and hides the controls that cannot work.

const byId = (id) => document.getElementById(id);

let current = null;

function paintAvatar(node, profile) {
  if (!node) return;
  node.textContent = profile.initials || '?';
  node.style.background = profile.color || 'var(--red)';
  node.style.color = '#fff';
  node.style.display = 'flex';
  node.style.alignItems = 'center';
  node.style.justifyContent = 'center';
  node.style.fontWeight = '600';
  node.style.borderRadius = '50%';
}

function paint(profile) {
  current = profile;

  const name = byId('user-bar-name');
  if (name) name.textContent = profile.display_name;
  paintAvatar(byId('user-bar-avatar'), profile);

  const field = byId('settings-profile-name');
  // Do not stamp over what someone is in the middle of typing.
  if (field && document.activeElement !== field) field.value = profile.display_name;
  paintAvatar(byId('settings-account-avatar'), profile);

  const role = byId('settings-account-role');
  if (role) {
    role.textContent = profile.auth_enabled
      ? 'Signed in'
      : 'This Mac. Your data stays on this machine.';
  }

  // Sign-out, password and two-factor need authentication to mean anything.
  const authOnly = [
    byId('settings-account-auth-actions'),
    byId('settings-password-card'),
    byId('settings-2fa-card'),
  ];
  authOnly.forEach((node) => {
    if (node) node.style.display = profile.auth_enabled ? '' : 'none';
  });
}

async function load() {
  try {
    const response = await fetch('/api/profile', { credentials: 'same-origin' });
    if (response.ok) paint(await response.json());
  } catch (_) {
    // Leave whatever the markup already shows.
  }
}

async function save() {
  const field = byId('settings-profile-name');
  const message = byId('settings-profile-msg');
  if (!field) return;

  const value = field.value.trim();
  if (!value) {
    if (message) message.textContent = 'A name cannot be empty.';
    return;
  }
  if (current && value === current.display_name) {
    if (message) message.textContent = '';
    return;
  }

  if (message) message.textContent = 'Saving...';
  try {
    const response = await fetch('/api/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ display_name: value }),
    });
    if (!response.ok) throw new Error('save failed');
    const saved = await response.json();
    paint({ ...saved, auth_enabled: current ? current.auth_enabled : false });
    if (message) message.textContent = 'Saved.';
    setTimeout(() => { if (message) message.textContent = ''; }, 2000);
  } catch (_) {
    if (message) message.textContent = 'Could not save that name.';
  }
}

let wired = false;

export function initProfile() {
  load();

  // The settings panel calls this again when the account tab opens, so that it
  // refreshes. Binding the handlers twice would save twice on every blur.
  if (wired) return;
  wired = true;

  const saveBtn = byId('settings-profile-save');
  if (saveBtn) saveBtn.addEventListener('click', save);

  const field = byId('settings-profile-name');
  if (field) {
    field.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); save(); }
    });
    field.addEventListener('blur', save);
  }
}

export default { initProfile };
