/* ═══════════════════════════════════════════════
   ADMIN — User and coffre management
   ═══════════════════════════════════════════════ */
'use strict';

let _adminUsers = [];
let _adminCoffres = [];

async function loadAdmin() {
  if (!isAdmin()) { navigate('dashboard'); return; }
  try {
    [_adminUsers, _adminCoffres] = await Promise.all([
      apiGet('/api/admin/users'),
      apiGet('/api/admin/coffres'),
    ]);
    renderAdminPage();
  } catch (err) {
    showToast('Erreur admin: ' + err.message, 'error');
  }
}

function renderAdminPage() {
  const page = document.getElementById('page-admin');
  if (!page) return;

  page.innerHTML = `
    <div class="page-title">⚙️ Administration</div>

    <div class="tabs" id="adminTabs">
      <button class="tab-btn active" onclick="switchAdminTab('users')">Utilisateurs</button>
      <button class="tab-btn" onclick="switchAdminTab('coffres')">Coffres</button>
      <button class="tab-btn" onclick="switchAdminTab('logs')">Logs d'audit</button>
    </div>

    <!-- Users -->
    <div id="admin-tab-users">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px">
        <button class="btn btn-primary btn-sm" onclick="openAddUserModal()">+ Utilisateur</button>
      </div>
      <div class="card" style="padding:0;overflow:hidden">
        <table class="data-table">
          <thead><tr>
            <th class="left" style="padding-left:24px">Nom</th>
            <th class="left">Email</th>
            <th>Rôle</th><th>Statut</th><th>2FA</th><th>Créé le</th><th>Actions</th>
          </tr></thead>
          <tbody>${renderUserRows()}</tbody>
        </table>
      </div>
    </div>

    <!-- Coffres -->
    <div id="admin-tab-coffres" style="display:none">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px">
        <button class="btn btn-primary btn-sm" onclick="openAddCoffreModal()">+ Coffre</button>
      </div>
      <div class="card" style="padding:0;overflow:hidden">
        <table class="data-table">
          <thead><tr>
            <th class="left" style="padding-left:24px">Nom</th>
            <th class="left">Description</th><th>Statut</th><th>Créé le</th><th>Actions</th>
          </tr></thead>
          <tbody>${renderCoffreRows()}</tbody>
        </table>
      </div>
    </div>

    <!-- Logs -->
    <div id="admin-tab-logs" style="display:none">
      <div class="card" style="padding:0;overflow:hidden" id="logsContainer">
        <div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">Cliquez sur l'onglet pour charger</div></div>
      </div>
    </div>

    <!-- Modals -->
    <div id="adminModals">${buildAdminModals()}</div>`;
}

function switchAdminTab(tab) {
  ['users', 'coffres', 'logs'].forEach(t => {
    const el = document.getElementById(`admin-tab-${t}`);
    if (el) el.style.display = t === tab ? '' : 'none';
  });
  document.querySelectorAll('#page-admin .tab-btn').forEach((b, i) => {
    b.classList.toggle('active', ['users', 'coffres', 'logs'][i] === tab);
  });
  if (tab === 'logs') loadAuditLogs();
}

function renderUserRows() {
  if (!_adminUsers.length) return `<tr><td colspan="7"><div class="empty-state"><div class="empty-icon">👥</div><div class="empty-text">Aucun utilisateur</div></div></td></tr>`;
  const me = currentUser();
  return _adminUsers.map(u => `
    <tr class="no-cursor">
      <td class="left" style="padding-left:24px;font-weight:500">${escHtml(u.name)}</td>
      <td class="left" style="font-family:var(--font-display);font-size:12px">${escHtml(u.email)}</td>
      <td><span class="badge badge-${u.role.toLowerCase()}">${u.role}</span></td>
      <td><span class="badge badge-${u.is_active ? 'success' : 'inactive'}">${u.is_active ? 'Actif' : 'Inactif'}</span></td>
      <td><span style="color:${u.two_factor_enabled ? 'var(--accent-green)' : 'var(--text-muted)'}">${u.two_factor_enabled ? '🔐 Oui' : '—'}</span></td>
      <td style="color:var(--text-secondary)">${fmtDate(u.created_at)}</td>
      <td>
        <div style="display:flex;justify-content:flex-end;gap:4px">
          ${u.id !== me?.id ? `
          <button class="btn btn-ghost" onclick="toggleUserActive(${u.id},${u.is_active})" title="${u.is_active ? 'Désactiver' : 'Activer'}">${u.is_active ? '⏸' : '▶'}</button>
          <button class="btn btn-ghost" onclick="openResetPasswordModal(${u.id},'${escHtml(u.name).replace(/'/g,"\\'")}')">🔑</button>
          <button class="btn btn-ghost danger" onclick="deleteUserConfirm(${u.id},'${escHtml(u.name).replace(/'/g,"\\'")}')">🗑</button>` : `<span style="font-size:11px;color:var(--text-muted)">Vous</span>`}
        </div>
      </td>
    </tr>`).join('');
}

function renderCoffreRows() {
  if (!_adminCoffres.length) return `<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">🏦</div><div class="empty-text">Aucun coffre</div></div></td></tr>`;
  return _adminCoffres.map(c => `
    <tr class="no-cursor">
      <td class="left" style="padding-left:24px;font-weight:500">${escHtml(c.name)}</td>
      <td class="left" style="color:var(--text-secondary)">${escHtml(c.description || '—')}</td>
      <td><span class="badge badge-${c.is_active ? 'success' : 'inactive'}">${c.is_active ? 'Actif' : 'Inactif'}</span></td>
      <td style="color:var(--text-secondary)">${fmtDate(c.created_at)}</td>
      <td>
        <div style="display:flex;justify-content:flex-end;gap:4px">
          <button class="btn btn-ghost" onclick="toggleAdminFavorite(${c.id})" title="${c.is_favorite ? 'Retirer des favoris' : 'Définir comme favori'}"
            style="opacity:${c.is_favorite ? '1' : '0.35'}">⭐</button>
          <button class="btn btn-ghost" onclick="openEditCoffreModal(${c.id})">✏️</button>
          <button class="btn btn-ghost danger" onclick="deleteCoffreConfirm(${c.id},'${escHtml(c.name).replace(/'/g,"\\'")}')">🗑</button>
        </div>
      </td>
    </tr>`).join('');
}

async function loadAuditLogs() {
  try {
    const logs = await apiGet('/api/admin/logs?limit=100');
    const userMap = Object.fromEntries(_adminUsers.map(u => [u.id, u.name]));
    document.getElementById('logsContainer').innerHTML = `
      <table class="data-table" style="font-size:12px">
        <thead><tr><th class="left" style="padding-left:24px">Date</th><th class="left">Utilisateur</th><th class="left">Action</th><th class="left">Description</th><th class="left">IP</th></tr></thead>
        <tbody>${logs.map(l => `<tr class="no-cursor">
          <td class="left" style="padding-left:24px;color:var(--text-secondary)">${fmtDateTime(l.created_at)}</td>
          <td class="left">${escHtml(userMap[l.user_id] || `#${l.user_id}`)}</td>
          <td class="left"><span style="font-family:var(--font-display);font-size:11px;color:var(--accent-blue)">${escHtml(l.action)}</span></td>
          <td class="left" style="color:var(--text-secondary)">${escHtml(l.description || '—')}</td>
          <td class="left" style="font-family:var(--font-display);color:var(--text-muted)">${escHtml(l.ip_address || '—')}</td>
        </tr>`).join('')}</tbody>
      </table>`;
  } catch (err) { showToast(err.message, 'error'); }
}

// ── User actions ──────────────────────────────────────────

function openAddUserModal() {
  document.getElementById('userModalTitle').textContent = 'Créer un utilisateur';
  document.getElementById('userModalId').value = '';
  document.getElementById('newUserName').value = '';
  document.getElementById('newUserEmail').value = '';
  document.getElementById('newUserPassword').value = '';
  document.getElementById('newUserRole').value = 'USER';
  document.getElementById('userPasswordGroup').style.display = '';
  openModal('adminUserModal');
}

async function submitUserModal(e) {
  e.preventDefault();
  const id = document.getElementById('userModalId').value;
  const body = {
    name: document.getElementById('newUserName').value,
    email: document.getElementById('newUserEmail').value,
    password: document.getElementById('newUserPassword').value,
    role: document.getElementById('newUserRole').value,
  };
  try {
    if (id) { await apiPut(`/api/admin/users/${id}`, { name: body.name, role: body.role }); showToast('Utilisateur mis à jour', 'success'); }
    else { await apiPost('/api/admin/users', body); showToast('Utilisateur créé', 'success'); }
    closeModal('adminUserModal');
    await loadAdmin();
  } catch (err) { showToast(err.message, 'error'); }
}

async function toggleUserActive(userId, isActive) {
  try {
    await apiPut(`/api/admin/users/${userId}`, { is_active: !isActive });
    showToast(isActive ? 'Utilisateur désactivé' : 'Utilisateur activé', 'success');
    await loadAdmin();
  } catch (err) { showToast(err.message, 'error'); }
}

function openResetPasswordModal(userId, name) {
  document.getElementById('resetPwUserId').value = userId;
  document.getElementById('resetPwTitle').textContent = `Réinitialiser le mot de passe — ${name}`;
  document.getElementById('resetPwValue').value = '';
  openModal('resetPwModal');
}

async function submitResetPassword(e) {
  e.preventDefault();
  const userId = document.getElementById('resetPwUserId').value;
  try {
    await apiPost(`/api/admin/users/${userId}/reset-password`, { password: document.getElementById('resetPwValue').value });
    showToast('Mot de passe réinitialisé', 'success');
    closeModal('resetPwModal');
  } catch (err) { showToast(err.message, 'error'); }
}

function deleteUserConfirm(userId, name) {
  confirm('Supprimer l\'utilisateur', `Supprimer "${name}" définitivement ?`, async () => {
    try { await apiDelete(`/api/admin/users/${userId}`); showToast('Utilisateur supprimé', 'success'); await loadAdmin(); }
    catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Coffre actions ────────────────────────────────────────

async function toggleAdminFavorite(coffreId) {
  try {
    await apiPut(`/api/coffres/${coffreId}/favorite`, {});
    const wasFav = _adminCoffres.find(c => c.id === coffreId)?.is_favorite;
    _adminCoffres.forEach(c => { c.is_favorite = false; });
    const target = _adminCoffres.find(c => c.id === coffreId);
    if (target) target.is_favorite = !wasFav;
    document.getElementById('admin-tab-coffres').querySelector('tbody').innerHTML = renderCoffreRows();
    showToast(target?.is_favorite ? `⭐ ${target.name} défini comme favori` : 'Favori retiré', 'success');
  } catch (err) {
    showToast('Erreur : ' + err.message, 'error');
  }
}

function openAddCoffreModal() {
  document.getElementById('coffreModalTitle').textContent = 'Créer un coffre';
  document.getElementById('coffreModalId').value = '';
  document.getElementById('coffreName').value = '';
  document.getElementById('coffreDesc').value = '';
  document.getElementById('coffreCombination').value = '';
  document.getElementById('coffreHint').value = '';
  document.getElementById('coffreComboStatus').textContent = '';
  openModal('adminCoffreModal');
}

function openEditCoffreModal(coffreId) {
  const c = _adminCoffres.find(x => x.id === coffreId);
  if (!c) return;
  document.getElementById('coffreModalTitle').textContent = 'Modifier le coffre';
  document.getElementById('coffreModalId').value = coffreId;
  document.getElementById('coffreName').value = c.name;
  document.getElementById('coffreDesc').value = c.description || '';
  document.getElementById('coffreCombination').value = '';
  document.getElementById('coffreHint').value = c.combination_hint || '';
  document.getElementById('coffreComboStatus').innerHTML = c.has_combination
    ? `<span style="color:var(--accent-green)">✓ Code enregistré${c.combination_hint ? ` — indice : "${escHtml(c.combination_hint)}"` : ''}</span>`
    : `<span style="color:var(--text-muted)">Aucun code enregistré</span>`;
  openModal('adminCoffreModal');
}

async function submitCoffreModal(e) {
  e.preventDefault();
  const id = document.getElementById('coffreModalId').value;
  const body = { name: document.getElementById('coffreName').value, description: document.getElementById('coffreDesc').value || null };
  const combination = document.getElementById('coffreCombination').value.trim();
  const hint = document.getElementById('coffreHint').value.trim();
  try {
    let coffreId = id;
    if (id) {
      await apiPut(`/api/admin/coffres/${id}`, body);
    } else {
      const res = await apiPost('/api/admin/coffres', body);
      coffreId = res.id;
    }
    // Si un code est saisi, l'enregistrer via l'endpoint dédié (chiffré AES-256)
    if (combination && coffreId) {
      await apiPut(`/api/coffres/${coffreId}/combination`, { combination, hint: hint || null });
    }
    showToast(id ? 'Coffre mis à jour' : 'Coffre créé', 'success');
    closeModal('adminCoffreModal');
    await loadAdmin();
  } catch (err) { showToast(err.message, 'error'); }
}

function deleteCoffreConfirm(id, name) {
  confirm('Supprimer le coffre', `Supprimer "${name}" ? Le solde doit être à zéro.`, async () => {
    try { await apiDelete(`/api/admin/coffres/${id}`); showToast('Coffre supprimé', 'success'); await loadAdmin(); }
    catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Modal HTML ────────────────────────────────────────────

function buildAdminModals() {
  return `
    <div class="modal-overlay" id="adminUserModal">
      <div class="modal">
        <div class="modal-header"><span class="modal-title" id="userModalTitle">Créer un utilisateur</span><button class="modal-close" onclick="closeModal('adminUserModal')">✕</button></div>
        <form onsubmit="submitUserModal(event)" class="form-grid">
          <div class="form-group"><label class="form-label">Nom</label><input type="text" class="form-input" id="newUserName" required/></div>
          <div class="form-group"><label class="form-label">Email</label><input type="email" class="form-input" id="newUserEmail" required/></div>
          <div class="form-group" id="userPasswordGroup"><label class="form-label">Mot de passe</label><input type="password" class="form-input" id="newUserPassword" minlength="8"/></div>
          <div class="form-group"><label class="form-label">Rôle</label>
            <select class="form-select" id="newUserRole"><option value="USER">Utilisateur (lecture seule)</option><option value="ADMIN">Administrateur</option></select>
          </div>
          <input type="hidden" id="userModalId"/>
          <div class="form-actions"><button type="button" class="btn btn-secondary" onclick="closeModal('adminUserModal')">Annuler</button><button type="submit" class="btn btn-primary">Enregistrer</button></div>
        </form>
      </div>
    </div>
    <div class="modal-overlay" id="resetPwModal">
      <div class="modal" style="max-width:380px">
        <div class="modal-header"><span class="modal-title" id="resetPwTitle">Réinitialiser</span><button class="modal-close" onclick="closeModal('resetPwModal')">✕</button></div>
        <form onsubmit="submitResetPassword(event)">
          <div class="form-group" style="margin-bottom:20px"><label class="form-label">Nouveau mot de passe</label><input type="password" class="form-input" id="resetPwValue" minlength="8" required/></div>
          <input type="hidden" id="resetPwUserId"/>
          <div class="form-actions"><button type="button" class="btn btn-secondary" onclick="closeModal('resetPwModal')">Annuler</button><button type="submit" class="btn btn-danger">Réinitialiser</button></div>
        </form>
      </div>
    </div>
    <div class="modal-overlay" id="adminCoffreModal">
      <div class="modal">
        <div class="modal-header"><span class="modal-title" id="coffreModalTitle">Créer un coffre</span><button class="modal-close" onclick="closeModal('adminCoffreModal')">✕</button></div>
        <form onsubmit="submitCoffreModal(event)" class="form-grid">
          <div class="form-group full"><label class="form-label">Nom</label><input type="text" class="form-input" id="coffreName" required/></div>
          <div class="form-group full"><label class="form-label">Description</label><textarea class="form-textarea" id="coffreDesc" rows="2"></textarea></div>
          <div class="form-group full" style="border-top:1px solid var(--border);padding-top:14px;margin-top:4px">
            <div style="font-size:11px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">🔑 Code d'accès (chiffré AES-256)</div>
            <div id="coffreComboStatus" style="font-size:12px;color:var(--text-muted);margin-bottom:8px"></div>
          </div>
          <div class="form-group full"><label class="form-label">Code / Combinaison <span style="color:var(--text-muted);font-weight:400">(laisser vide pour ne pas modifier)</span></label><input type="text" class="form-input" id="coffreCombination" placeholder="ex: A-23-B-07" autocomplete="off"/></div>
          <div class="form-group full"><label class="form-label">Indice mémo <span style="color:var(--text-muted);font-weight:400">(stocké en clair)</span></label><input type="text" class="form-input" id="coffreHint" placeholder="ex: Date d'anniversaire"/></div>
          <input type="hidden" id="coffreModalId"/>
          <div class="form-actions"><button type="button" class="btn btn-secondary" onclick="closeModal('adminCoffreModal')">Annuler</button><button type="submit" class="btn btn-primary">Enregistrer</button></div>
        </form>
      </div>
    </div>`;
}
