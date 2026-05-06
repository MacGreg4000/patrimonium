/* ═══════════════════════════════════════════════
   PASSWORDS — Encrypted file vault module
   ═══════════════════════════════════════════════ */
'use strict';

let _pwFiles = [];

async function loadPasswords() {
  try {
    _pwFiles = await apiGet('/api/password-files');
    renderPasswordsPage();
  } catch (err) {
    showToast('Erreur coffre: ' + err.message, 'error');
  }
}

function renderPasswordsPage() {
  const page = document.getElementById('page-passwords');
  if (!page) return;

  const totalSize = _pwFiles.reduce((s, f) => s + f.size_bytes, 0);

  page.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div>
        <div class="page-title">🔐 Coffre à mots de passe</div>
        <div class="page-subtitle">Fichiers chiffrés AES-256-GCM — ${_pwFiles.length} fichier${_pwFiles.length !== 1 ? 's' : ''} · ${fmtSize(totalSize)}</div>
      </div>
      ${isAdmin() ? `<button class="btn btn-primary btn-sm" onclick="openUploadPwModal()">📎 Charger un fichier</button>` : ''}
    </div>

    <div class="card" style="padding:0;overflow:hidden">
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th class="left" style="padding-left:24px">Fichier</th>
            <th class="left">Type</th>
            <th>Taille</th>
            <th class="col-hide-mobile">SHA-256</th>
            <th>Date</th>
            <th>Actions</th>
          </tr></thead>
          <tbody id="pwFilesBody">${renderPwFileRows()}</tbody>
        </table>
      </div>
    </div>

    <!-- CSV viewer area -->
    <div id="csvViewerArea" style="margin-top:20px;display:none">
      <div class="card" style="padding:0;overflow:hidden">
        <div class="section-header">
          <div class="section-title" id="csvViewerTitle">Aperçu CSV</div>
          <button class="btn btn-secondary btn-sm" onclick="closeCsvViewer()">Fermer</button>
        </div>
        <div class="csv-table-wrap" id="csvViewerContent"></div>
      </div>
    </div>

    <!-- Upload modal -->
    <div class="modal-overlay" id="pwUploadModal">
      <div class="modal">
        <div class="modal-header"><span class="modal-title">Chiffrer et stocker un fichier</span><button class="modal-close" onclick="closeModal('pwUploadModal')">✕</button></div>
        <div style="color:var(--text-secondary);font-size:12px;margin-bottom:16px">Formats acceptés: CSV, JSON, ZIP, TXT — Max 50 MB</div>
        <form id="pwUploadForm" onsubmit="submitPwUpload(event)">
          <div class="form-group" style="margin-bottom:20px">
            <label class="form-label">Fichier</label>
            <input type="file" class="form-input" id="pwFile" required accept=".csv,.json,.zip,.txt,.text"/>
          </div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal('pwUploadModal')">Annuler</button>
            <button type="submit" class="btn btn-primary">🔒 Chiffrer et enregistrer</button>
          </div>
        </form>
      </div>
    </div>`;
}

function renderPwFileRows() {
  if (!_pwFiles.length) return `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">🔐</div><div class="empty-text">Aucun fichier stocké</div><div class="empty-sub">Chargez des fichiers de mots de passe chiffrés</div></div></td></tr>`;

  return _pwFiles.map(f => {
    const ext = f.filename.split('.').pop().toLowerCase();
    const icon = { csv: '📊', json: '📋', zip: '📦', txt: '📝', text: '📝' }[ext] || '📄';
    const sha = f.sha256 ? f.sha256.substring(0, 12) + '…' : '—';
    const canPreview = ext === 'csv';

    return `
      <tr class="no-cursor">
        <td class="left" style="padding-left:24px">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:20px">${icon}</span>
            <div>
              <div style="font-weight:500">${escHtml(f.filename)}</div>
              <div style="font-size:11px;color:var(--text-muted);font-family:var(--font-display)">${f.sha256 ? f.sha256.substring(0, 16) + '…' : '—'}</div>
            </div>
          </div>
        </td>
        <td class="left"><span class="badge">${ext.toUpperCase()}</span></td>
        <td>${fmtSize(f.size_bytes)}</td>
        <td class="col-hide-mobile" style="font-family:var(--font-display);font-size:11px;color:var(--text-muted)">${sha}</td>
        <td>${fmtDate(f.created_at)}</td>
        <td>
          <div style="display:flex;justify-content:flex-end;gap:4px">
            ${canPreview ? `<button class="btn btn-ghost primary btn-sm btn-preview-csv" data-id="${f.id}" data-filename="${escHtml(f.filename)}">👁 Aperçu</button>` : ''}
            <button class="btn btn-ghost btn-sm btn-dl-pwfile" data-id="${f.id}" data-filename="${escHtml(f.filename)}">⬇ Télécharger</button>
            ${isAdmin() ? `<button class="btn btn-ghost danger btn-sm btn-del-pwfile" data-id="${f.id}" data-filename="${escHtml(f.filename)}">🗑</button>` : ''}
          </div>
        </td>
      </tr>`;
  }).join('');
}

function openUploadPwModal() {
  document.getElementById('pwUploadForm').reset();
  openModal('pwUploadModal');
}

async function submitPwUpload(e) {
  e.preventDefault();
  const file = document.getElementById('pwFile').files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    await apiFetch('/api/password-files', { method: 'POST', body: fd });
    showToast('Fichier chiffré et stocké', 'success');
    closeModal('pwUploadModal');
    await loadPasswords();
  } catch (err) { showToast(err.message, 'error'); }
}

function deletePwFileConfirm(id, name) {
  confirm('Supprimer le fichier', `Supprimer "${name}" définitivement ?`, async () => {
    try { await apiDelete(`/api/password-files/${id}`); showToast('Fichier supprimé', 'success'); await loadPasswords(); }
    catch (err) { showToast(err.message, 'error'); }
  });
}

async function previewCsv(fileId, filename) {
  try {
    const res = await apiFetchRaw(`/api/password-files/${fileId}/download`);
    if (!res.ok) { showToast('Erreur téléchargement', 'error'); return; }
    const text = await res.text();
    const rows = text.trim().split('\n').map(r => r.split(','));
    const headers = rows[0] || [];
    const body = rows.slice(1);

    document.getElementById('csvViewerTitle').textContent = `Aperçu — ${filename}`;
    document.getElementById('csvViewerContent').innerHTML = `
      <table class="csv-table">
        <thead><tr>${headers.map(h => `<th>${escHtml(h.trim())}</th>`).join('')}</tr></thead>
        <tbody>${body.slice(0, 200).map(row =>
          `<tr>${row.map(cell => `<td>${escHtml(cell?.trim() || '')}</td>`).join('')}</tr>`
        ).join('')}</tbody>
      </table>
      ${body.length > 200 ? `<div style="padding:8px;color:var(--text-secondary);font-size:12px">… ${body.length - 200} lignes supplémentaires non affichées</div>` : ''}`;
    document.getElementById('csvViewerArea').style.display = 'block';
    document.getElementById('csvViewerArea').scrollIntoView({ behavior: 'smooth' });
  } catch (err) { showToast('Erreur aperçu: ' + err.message, 'error'); }
}

function closeCsvViewer() {
  document.getElementById('csvViewerArea').style.display = 'none';
}

async function downloadPwFile(fileId, filename) {
  try {
    const res = await apiFetchRaw(`/api/password-files/${fileId}/download`);
    if (!res.ok) { showToast('Erreur téléchargement', 'error'); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename || 'fichier';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (err) { showToast(err.message, 'error'); }
}

document.addEventListener('click', e => {
  const dlBtn = e.target.closest('.btn-dl-pwfile');
  if (dlBtn) { downloadPwFile(parseInt(dlBtn.dataset.id), dlBtn.dataset.filename); return; }
  const previewBtn = e.target.closest('.btn-preview-csv');
  if (previewBtn) { previewCsv(parseInt(previewBtn.dataset.id), previewBtn.dataset.filename); return; }
  const delBtn = e.target.closest('.btn-del-pwfile');
  if (delBtn) deletePwFileConfirm(parseInt(delBtn.dataset.id), delBtn.dataset.filename);
});
