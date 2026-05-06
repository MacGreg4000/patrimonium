/* ═══════════════════════════════════════════════
   AUTH — Login, 2FA, profile, password change
   ═══════════════════════════════════════════════ */
'use strict';

let _pendingEmail = '';
let _pendingPassword = '';
let _currentUser = null;

// ── Boot ──────────────────────────────────────────────────

async function bootAuth() {
  try {
    _currentUser = await apiGet('/api/auth/me');
    await refreshCsrf();
    showApp();
  } catch (_) {
    showLogin();
  }
}

function showLogin() {
  document.getElementById('authScreen').style.display = 'flex';
  document.getElementById('appShell').style.display = 'none';
  showAuthStep('login');
}

function showApp() {
  document.getElementById('authScreen').style.display = 'none';
  document.getElementById('appShell').style.display = 'flex';
  applyUserRole();
  updateHeaderUser();
  initApp();
}

function showAuthStep(step) {
  document.querySelectorAll('.auth-step').forEach(s => s.classList.remove('active'));
  document.getElementById(step === 'login' ? 'authStepLogin' : 'authStep2FA').classList.add('active');
}

// ── Login ─────────────────────────────────────────────────

async function submitLogin(e) {
  e.preventDefault();
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  const btn = document.getElementById('loginBtn');
  btn.disabled = true;
  btn.textContent = 'Connexion…';

  try {
    const res = await apiPost('/api/auth/login', { email, password, totp_code: '' });
    if (res.requires_2fa) {
      _pendingEmail = email;
      _pendingPassword = password;
      showAuthStep('2fa');
      setTimeout(() => document.getElementById('totpCode')?.focus(), 100);
    } else if (res.ok) {
      _currentUser = res.user;
      await refreshCsrf();
      showApp();
    }
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Se connecter';
  }
}

async function submit2FA(e) {
  e.preventDefault();
  const code = document.getElementById('totpCode').value.trim();
  try {
    const res = await apiPost('/api/auth/login', {
      email: _pendingEmail,
      password: _pendingPassword,
      totp_code: code,
    });
    if (res.ok) {
      _currentUser = res.user;
      await refreshCsrf();
      showApp();
    }
  } catch (err) {
    showToast(err.message, 'error');
    document.getElementById('totpCode').value = '';
    document.getElementById('totpCode').focus();
  }
}

// ── Logout ────────────────────────────────────────────────

async function logout() {
  closeUserMenu();
  try { await apiPost('/api/auth/logout', {}); } catch (_) {}
  _currentUser = null;
  showLogin();
}

// ── User helpers ──────────────────────────────────────────

function currentUser() { return _currentUser; }
function isAdmin() { return _currentUser?.role === 'ADMIN'; }

function applyUserRole() {
  const adminEls = document.querySelectorAll('.admin-only');
  adminEls.forEach(el => {
    el.style.display = isAdmin() ? '' : 'none';
  });
}

function updateHeaderUser() {
  if (!_currentUser) return;
  document.getElementById('userNameHeader').textContent = _currentUser.name;
  document.getElementById('ddUserName').textContent = _currentUser.name;
  document.getElementById('ddUserEmail').textContent = _currentUser.email;
}

// ── User menu ─────────────────────────────────────────────

function toggleUserMenu() {
  const dd = document.getElementById('userDropdown');
  if (!dd) return;
  dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
}

function closeUserMenu() {
  const dd = document.getElementById('userDropdown');
  if (dd) dd.style.display = 'none';
}

document.addEventListener('click', e => {
  const btn = document.getElementById('userMenuBtn');
  const dd = document.getElementById('userDropdown');
  if (dd && btn && !btn.contains(e.target) && !dd.contains(e.target)) {
    dd.style.display = 'none';
  }
});

// ── Profile modal ─────────────────────────────────────────

function openProfileModal() {
  closeUserMenu();
  renderProfileInfo();
  renderTwoFAPanel();
  openModal('profileModal');
}

function renderProfileInfo() {
  const u = _currentUser;
  if (!u) return;
  document.getElementById('profileInfo').innerHTML = `
    <div style="display:grid;gap:12px">
      <div><span style="color:var(--text-secondary);font-size:11px;text-transform:uppercase;letter-spacing:.08em">Nom</span>
        <div style="font-size:15px;font-weight:500;margin-top:4px">${escHtml(u.name)}</div></div>
      <div><span style="color:var(--text-secondary);font-size:11px;text-transform:uppercase;letter-spacing:.08em">Email</span>
        <div style="font-size:14px;margin-top:4px;font-family:var(--font-display)">${escHtml(u.email)}</div></div>
      <div><span style="color:var(--text-secondary);font-size:11px;text-transform:uppercase;letter-spacing:.08em">Rôle</span>
        <div style="margin-top:4px"><span class="badge badge-${u.role.toLowerCase()}">${u.role}</span></div></div>
    </div>`;
}

async function renderTwoFAPanel() {
  const panel = document.getElementById('twoFAPanel');
  if (!_currentUser) return;
  if (_currentUser.two_factor_enabled) {
    panel.innerHTML = `
      <div style="text-align:center;margin-bottom:20px">
        <div style="font-size:32px;margin-bottom:8px">🔐</div>
        <div style="font-size:14px;font-weight:500;color:var(--accent-green)">2FA activé</div>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:4px">Votre compte est protégé.</div>
      </div>
      <form onsubmit="disable2FA(event)" class="form-grid" style="grid-template-columns:1fr">
        <div class="form-group"><label class="form-label">Mot de passe</label><input type="password" class="form-input" id="disablePw" required/></div>
        <div class="form-group"><label class="form-label">Code TOTP actuel</label><input type="text" class="form-input" id="disableCode" placeholder="000000" maxlength="6"/></div>
        <div class="form-actions" style="border-top:none;padding-top:0;margin-top:8px">
          <button type="submit" class="btn btn-danger">Désactiver le 2FA</button>
        </div>
      </form>`;
  } else {
    panel.innerHTML = `
      <div style="text-align:center;margin-bottom:20px">
        <div style="font-size:32px;margin-bottom:8px">🔓</div>
        <div style="font-size:14px;color:var(--text-secondary)">2FA non activé</div>
      </div>
      <button class="btn btn-primary" style="width:100%;justify-content:center" onclick="setup2FA()">Activer la 2FA</button>`;
  }
}

async function setup2FA() {
  try {
    const data = await apiGet('/api/auth/2fa/setup');
    document.getElementById('twoFAPanel').innerHTML = `
      <div class="qr-container">
        <img src="data:image/png;base64,${data.qr_png_b64}" alt="QR Code 2FA"/>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:8px">Scannez avec Google Authenticator ou Authy</div>
        <div style="font-family:var(--font-display);font-size:11px;color:var(--text-muted);margin-top:4px;word-break:break-all">${data.secret}</div>
      </div>
      <form onsubmit="confirm2FA(event,'${data.secret}')" class="form-grid" style="grid-template-columns:1fr;margin-top:16px">
        <div class="form-group"><label class="form-label">Code de vérification</label>
          <input type="text" class="form-input" id="confirmTOTPCode" placeholder="000000" maxlength="6" required style="text-align:center;font-family:var(--font-display);font-size:20px;letter-spacing:.3em"/></div>
        <div class="form-actions" style="border-top:none;padding-top:0;margin-top:8px">
          <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center">Confirmer et activer</button>
        </div>
      </form>`;
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function confirm2FA(e, secret) {
  e.preventDefault();
  const code = document.getElementById('confirmTOTPCode').value.trim();
  try {
    const res = await apiPost('/api/auth/2fa/confirm', { secret, code });
    _currentUser.two_factor_enabled = true;
    // Show backup codes
    document.getElementById('twoFAPanel').innerHTML = `
      <div style="color:var(--accent-green);font-size:14px;font-weight:500;margin-bottom:12px">✓ 2FA activé avec succès !</div>
      <div style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">Conservez ces codes de secours en lieu sûr :</div>
      <div class="backup-codes-grid">
        ${res.backup_codes.map(c => `<div class="backup-code">${c}</div>`).join('')}
      </div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:8px">Chaque code ne peut être utilisé qu'une seule fois.</div>`;
    showToast('2FA activé', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function disable2FA(e) {
  e.preventDefault();
  try {
    await apiPost('/api/auth/2fa/disable', {
      password: document.getElementById('disablePw').value,
      code: document.getElementById('disableCode').value,
    });
    _currentUser.two_factor_enabled = false;
    renderTwoFAPanel();
    showToast('2FA désactivé', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function submitChangePassword(e) {
  e.preventDefault();
  try {
    await apiPost('/api/auth/change-password', {
      old_password: document.getElementById('oldPassword').value,
      new_password: document.getElementById('newPassword').value,
    });
    document.getElementById('oldPassword').value = '';
    document.getElementById('newPassword').value = '';
    showToast('Mot de passe modifié', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}
