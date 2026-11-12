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
    <div class="db-head">
      <div>
        <h1 class="db-title">Coffre à mots de passe</h1>
        <div class="db-subtitle">${_pwFiles.length} fichier${_pwFiles.length !== 1 ? 's' : ''} · ${fmtSize(totalSize)} · chiffrés AES-256-GCM</div>
      </div>
      ${isAdmin() ? `<div class="db-actions"><button class="btn btn-primary" onclick="openUploadPwModal()">+ Charger un fichier</button></div>` : ''}
    </div>

    <div class="cr-note is-info" style="margin-bottom:16px">
      <b>Chiffré sur le serveur.</b> Les fichiers sont déchiffrés uniquement au moment de l’aperçu ou du téléchargement.
      Pense à supprimer les copies téléchargées après usage.
    </div>

    <section class="card pf-table-card">
      <div class="table-wrap">
        <table class="data-table pf-table">
          <thead><tr>
            <th class="left">Fichier</th>
            <th>Taille</th>
            <th>Ajouté le</th>
            <th><span class="sr-only">Actions</span></th>
          </tr></thead>
          <tbody id="pwFilesBody">${renderPwFileRows()}</tbody>
        </table>
      </div>
    </section>

    <section id="csvViewerArea" class="card pf-table-card" style="display:none">
      <div class="pf-toolbar">
        <div class="db-card-title" style="margin:0" id="csvViewerTitle">Aperçu CSV</div>
        <input type="search" class="form-input pf-search" id="csvSearch" placeholder="Filtrer les lignes" aria-label="Filtrer les lignes" oninput="filterCsvRows(this.value)">
        <button class="btn btn-secondary" onclick="closeCsvViewer()">Fermer l’aperçu</button>
      </div>
      <div class="csv-table-wrap" id="csvViewerContent"></div>
    </section>

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
            <button type="submit" class="btn btn-primary">Chiffrer et enregistrer</button>
          </div>
        </form>
      </div>
    </div>`;
}

function renderPwFileRows() {
  if (!_pwFiles.length) return `<tr><td colspan="4"><div class="empty-state"><div class="empty-text">Aucun fichier stocké</div><div class="empty-sub">Chargez des fichiers de mots de passe chiffrés</div></div></td></tr>`;

  return _pwFiles.map(f => {
    const ext = f.filename.split('.').pop().toLowerCase();
    const canPreview = ext === 'csv';
    return `
      <tr class="no-cursor position-row">
        <td class="left" data-label="">
          <div class="asset-name-cell">
            <span class="pf-badge">${escHtml(ext.toUpperCase().slice(0, 4))}</span>
            <div style="min-width:0">
              <div class="asset-name">${escHtml(f.filename)}</div>
              <div class="asset-sub" title="Empreinte SHA-256">${f.sha256 ? 'SHA-256 ' + f.sha256.substring(0, 12) + '…' : '—'}</div>
            </div>
          </div>
        </td>
        <td data-label="Taille">${fmtSize(f.size_bytes)}</td>
        <td data-label="Ajouté le">${fmtDate(f.created_at)}</td>
        <td class="pf-actions rs-actions">
          ${canPreview ? `<button class="btn btn-secondary btn-sm btn-preview-csv" data-id="${f.id}" data-filename="${escHtml(f.filename)}">Aperçu</button>` : ''}
          <button class="btn btn-secondary btn-sm btn-dl-pwfile" data-id="${f.id}" data-filename="${escHtml(f.filename)}">Télécharger</button>
          ${isAdmin() ? `<button type="button" class="pf-menu-btn row-menu-btn" aria-haspopup="menu" aria-label="Autres actions"
            onclick="openRowMenu(this, [['Supprimer', () => deletePwFileConfirm(${f.id}, _pwFiles.find(x => x.id === ${f.id})?.filename || ''), true]])">⋯</button>` : ''}
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
    const search = document.getElementById('csvSearch');
    if (search) search.value = '';
    document.getElementById('csvViewerArea').style.display = 'block';
    document.getElementById('csvViewerArea').scrollIntoView({ behavior: 'smooth' });
  } catch (err) { showToast('Erreur aperçu: ' + err.message, 'error'); }
}

function closeCsvViewer() {
  document.getElementById('csvViewerArea').style.display = 'none';
  document.getElementById('csvViewerContent').innerHTML = '';   // ne garde pas le contenu déchiffré dans la page
}

// Filtre côté navigateur des lignes affichées dans l'aperçu
function filterCsvRows(q) {
  const needle = q.trim().toLowerCase();
  document.querySelectorAll('#csvViewerContent tbody tr').forEach(tr => {
    tr.hidden = needle && !tr.textContent.toLowerCase().includes(needle);
  });
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
