(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const STORE_KEY = 'zyvefit-nutrition-console-v2';
  const MAX_FILE_BYTES = 25 * 1024 * 1024;
  const TYPES = ['Text', 'Image', 'Audio', 'Video', 'Document', 'Location'];
  const TIERS = ['Foundation', 'Pro', 'Max', 'Ultra'];
  const SCOPES = ['Shared', ...TIERS, 'Member-specific'];
  const PHASES = ['P1', 'P2', 'P3'];
  let backendConnected = false;
  let backendWritesEnabled = false;
  let backendMigrationReady = false;
  let backendLiveSendingEnabled = false;
  let backendChecking = true;
  let dbRecordsData = null;
  let dbRecordsError = '';
  let activeDbTable = 'tiers';

  // Recipients and groups are loaded from PostgreSQL via /api/bootstrap.
  let demoMembers = [];
  let demoGroups = [];

  function loadStoredState() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return { templates: [], outbox: [], hostedAssets: [] };
      const parsed = JSON.parse(raw);
      return {
        templates: Array.isArray(parsed.templates) ? parsed.templates : [],
        outbox: Array.isArray(parsed.outbox) ? parsed.outbox : [],
        hostedAssets: Array.isArray(parsed.hostedAssets) ? parsed.hostedAssets : []
      };
    } catch (error) {
      console.warn('Unable to read locally stored outbox data:', error);
      return { templates: [], outbox: [], hostedAssets: [] };
    }
  }
  function structuredCloneSafe(value) { return JSON.parse(JSON.stringify(value)); }
  const saved = loadStoredState();
  const state = {
    page: 'overview',
    audienceMode: 'tier',
    attachedMediaId: '',
    editingOutboxId: '',
    assets: saved.hostedAssets.map(a => ({ ...a, storageMode: 'hosted', previewUrl: safeExternalUrl(a.url) ? a.url : '' })),
    templates: saved.templates,
    outbox: saved.outbox,
    dialogContext: null
  };
  const dialog = $('#appDialog');

  function esc(value = '') {
    return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }
  function icon(name, extraClass = '') {
    return `<svg class="icon ${extraClass}" aria-hidden="true"><use href="#i-${esc(name)}"></use></svg>`;
  }
  function uid(prefix = 'id') {
    return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  }
  function slugify(value) {
    return String(value || '').trim().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 90);
  }
  function dateStringIST(date) {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date);
    const p = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${p.year}-${p.month}-${p.day}`;
  }
  function todayIST() { return dateStringIST(new Date()); }
  function suggestedISTSchedule() {
    const date = new Date(Date.now() + 30 * 60 * 1000);
    const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(date);
    const p = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return { date: dateStringIST(date), time: `${p.hour}:${p.minute}` };
  }
  function istDateTime(date, time) {
    if (!date || !time) return null;
    const value = new Date(`${date}T${time}:00+05:30`);
    return Number.isNaN(value.getTime()) ? null : value;
  }
  function formatIST(dateValue, includeWeekday = true) {
    const date = dateValue instanceof Date ? dateValue : new Date(dateValue);
    if (Number.isNaN(date.getTime())) return 'Time not set';
    const weekdayOptions = includeWeekday ? { weekday: 'short', day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' };
    return new Intl.DateTimeFormat('en-IN', { ...weekdayOptions, timeZone: 'Asia/Kolkata' }).format(date);
  }
  function formatClock(dateValue) {
    const date = dateValue instanceof Date ? dateValue : new Date(dateValue);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' }).format(date);
  }
  function safeExternalUrl(value) {
    try {
      const url = new URL(String(value || ''));
      return url.protocol === 'https:' && !url.username && !url.password;
    } catch { return false; }
  }
  function formatSize(bytes) {
    if (!Number.isFinite(bytes)) return 'Size not available';
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  function fileKind(fileOrName, mime = '') {
    const name = typeof fileOrName === 'string' ? fileOrName.toLowerCase() : (fileOrName?.name || '').toLowerCase();
    const type = (typeof fileOrName === 'object' ? fileOrName?.type : mime) || '';
    if (type.startsWith('image/') || /\.(png|jpe?g|webp|gif|heic|avif)$/.test(name)) return 'Image';
    if (type.startsWith('audio/') || /\.(mp3|wav|m4a|aac|ogg|opus|flac)$/.test(name)) return 'Audio';
    if (type.startsWith('video/') || /\.(mp4|mov|webm|m4v|avi)$/.test(name)) return 'Video';
    if (/\.pdf(?:$|\?)/.test(name)) return 'PDF';
    if (/\.(txt|csv|doc|docx|xls|xlsx|ppt|pptx)$/.test(name)) return 'Document';
    return 'Document';
  }
  function assetIconName(type) {
    if (type === 'Image') return 'image';
    if (type === 'Audio') return 'audio';
    if (type === 'Video') return 'video';
    if (type === 'Location') return 'link';
    return 'file';
  }
  function templateTypeClass(type) {
    return `type-${String(type || 'document').toLowerCase()}`;
  }
  function findAsset(id) { return state.assets.find(asset => asset.id === id) || null; }
  function findTemplate(id) { return state.templates.find(template => template.id === id) || null; }
  function findMember(id) { return demoMembers.find(member => member.id === id) || null; }
  function findGroup(id) { return demoGroups.find(group => group.id === id) || null; }
  function mediaNameFor(id, fallback = '') { return findAsset(id)?.name || fallback || 'Media needs to be re-added'; }
  function persist() {
    const hostedAssets = state.assets.filter(asset => asset.storageMode === 'hosted' && safeExternalUrl(asset.url)).map(asset => ({
      id: asset.id, name: asset.name, filename: asset.filename, type: asset.type,
      scope: asset.scope, tier: asset.tier || '', memberId: asset.memberId || '',
      memberName: asset.memberName || '', size: asset.size || '', description: asset.description || '',
      url: asset.url, storageMode: 'hosted', createdAt: asset.createdAt, isExample: false
    }));
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ templates: state.templates, outbox: state.outbox, hostedAssets }));
    } catch (error) {
      console.warn('Unable to save local data:', error);
      notify('Browser storage is full or unavailable. Changes may not survive refresh.', 'error');
    }
  }
  function notify(message, type = '') {
    const toast = document.createElement('div');
    toast.className = `toast${type ? ` ${type}` : ''}`;
    toast.textContent = message;
    $('#toastRegion').append(toast);
    window.setTimeout(() => toast.remove(), 4300);
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(options.headers || {}) } });
    let payload = {};
    try { payload = await response.json(); } catch { payload = {}; }
    if (!response.ok) {
      const detail = payload?.detail;
      const message = typeof detail === 'string' ? detail : (detail?.message || JSON.stringify(detail) || `Request failed (${response.status})`);
      throw new Error(message);
    }
    return payload;
  }
  function setConnectionStatus(kind, label, title = '') {
    const badge = $('#connectionStatus');
    if (!badge) return;
    badge.className = `demo-pill status-${kind}`;
    badge.title = title || label;
    badge.innerHTML = `<span class="demo-dot"></span> ${esc(label)}`;
  }
  function setConnectionCopy(title, message, footer) {
    const titleEl = $('#connectionBannerTitle');
    const messageEl = $('#connectionBannerText');
    const footerEl = $('#appFooterStatus');
    if (titleEl) titleEl.textContent = title;
    if (messageEl) messageEl.textContent = message;
    if (footerEl) footerEl.textContent = footer;
  }
  function apiScopeForPayload(scope) {
    if (scope === 'Member-specific') return 'Member-specific';
    if (TIERS.includes(scope)) return scope;
    return 'Shared';
  }
  function templateApiPayload(item, media) {
    const scope = apiScopeForPayload(item.scope);
    return {
      code: item.code, name: item.name, type: item.type, language: item.language || 'en',
      content: item.content || '', scope, tier: TIERS.includes(scope) ? scope : null,
      member_id: scope === 'Member-specific' ? (item.memberId || '') : null,
      media_url: media?.url || item.mediaUrl || null,
      media_asset_id: media?.serverAssetId || null
    };
  }
  async function refreshDatabaseRecords(announce = false) {
    try {
      dbRecordsData = await apiRequest('/api/db/records');
      dbRecordsError = '';
      renderDatabaseExplorer();
      if (announce) notify('Database records refreshed from PostgreSQL.');
    } catch (error) {
      dbRecordsData = null;
      dbRecordsError = error.message || 'Unable to load database records.';
      renderDatabaseExplorer();
      if (announce) notify(dbRecordsError, 'error');
    }
  }

  function displayDbValue(value) {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function renderDatabaseExplorer() {
    const status = $('#dbPageStatus');
    if (!status) return;
    const details = $('#dbPageDetails');
    const summary = $('#dbSummaryCards');
    const select = $('#dbTableSelect');
    if (!dbRecordsData) {
      status.textContent = backendConnected ? 'Connected, but table preview is unavailable' : 'Database not connected';
      details.textContent = dbRecordsError || 'Open /api/health to test the database connection. Then refresh this page.';
      summary.innerHTML = '';
      select.innerHTML = '<option value="">No table data available</option>';
      $('#dbSelectedTableTitle').textContent = 'No database data loaded';
      $('#dbSelectedTableInfo').textContent = 'Use Refresh database to retry.';
      $('#dbRecordsMeta').textContent = dbRecordsError || 'No table metadata received.';
      $('#dbTableHead').innerHTML = '';
      $('#dbTableBody').innerHTML = '';
      $('#dbTableWrap').hidden = true;
      $('#dbEmptyState').hidden = false;
      $('#dbEmptyTitle').textContent = 'Database rows are not available';
      $('#dbEmptyMessage').textContent = dbRecordsError || 'The backend did not return table data.';
      return;
    }
    const data = dbRecordsData;
    const tables = Array.isArray(data.tables) ? data.tables : [];
    const existing = tables.filter(table => table.exists);
    const totalRows = existing.reduce((sum, table) => sum + Number(table.row_count || 0), 0);
    const notFound = tables.filter(table => !table.exists).length;
    const identity = data.database || {};
    status.textContent = `Connected to ${identity.database_name || 'PostgreSQL'} · read-only viewer`;
    details.textContent = `Database: ${identity.database_name || 'unknown'} · User: ${identity.database_user || 'unknown'} · Schema: ${data.schema || identity.current_schema || 'unknown'}. No records are modified by this page.`;
    summary.innerHTML = [
      { label: 'Tables found', value: existing.length, foot: `${notFound} expected tables missing` },
      { label: 'Rows counted', value: totalRows.toLocaleString('en-IN'), foot: 'Across the inspected tables' },
      { label: 'Templates', value: (tables.find(t => t.name === 'templates')?.row_count ?? '—'), foot: 'Existing reusable content' },
      { label: 'Members', value: (tables.find(t => t.name === 'members')?.row_count ?? '—'), foot: 'Rows, including inactive members' }
    ].map((item, index) => `<article class="stat-card"><div class="stat-label-row"><span class="stat-context">DATABASE</span></div><div class="stat-number">${esc(item.value)}</div><div class="stat-name">${esc(item.label)}</div><div class="stat-foot">${esc(item.foot)}</div></article>`).join('');
    const selectedExists = tables.some(table => table.name === activeDbTable);
    if (!selectedExists) activeDbTable = existing[0]?.name || (tables[0]?.name || 'tiers');
    select.innerHTML = tables.map(table => `<option value="${esc(table.name)}">${esc(table.label)} · ${table.exists ? Number(table.row_count || 0).toLocaleString('en-IN') + ' rows' : 'table missing'}</option>`).join('');
    select.value = activeDbTable;
    const selected = tables.find(table => table.name === activeDbTable);
    if (!selected) {
      $('#dbSelectedTableTitle').textContent = 'No table selected';
      $('#dbSelectedTableInfo').textContent = '';
      $('#dbRecordsMeta').textContent = 'No inspectable tables returned.';
      $('#dbTableHead').innerHTML = ''; $('#dbTableBody').innerHTML = '';
      $('#dbTableWrap').hidden = true; $('#dbEmptyState').hidden = false;
      $('#dbEmptyTitle').textContent = 'No tables available';
      $('#dbEmptyMessage').textContent = 'Check the database schema endpoint and confirm DATABASE_SCHEMA in .env.';
      return;
    }
    $('#dbSelectedTableTitle').textContent = selected.label;
    $('#dbSelectedTableInfo').textContent = selected.exists ? `${Number(selected.row_count || 0).toLocaleString('en-IN')} rows in ${data.schema || 'the selected schema'}.` : `The table ${data.schema || 'public'}.${selected.name} was not found.`;
    $('#dbRecordsMeta').textContent = selected.exists ? `Showing ${selected.displayed_rows || 0} of ${selected.row_count || 0} rows${selected.has_more ? ' · limited to the first 100 records' : ''}.` : 'This table does not exist in the selected schema.';
    if (!selected.exists || !selected.rows?.length) {
      $('#dbTableHead').innerHTML = ''; $('#dbTableBody').innerHTML = '';
      $('#dbTableWrap').hidden = true; $('#dbEmptyState').hidden = false;
      $('#dbEmptyTitle').textContent = !selected.exists ? 'Table not found' : 'This table contains no rows';
      $('#dbEmptyMessage').textContent = !selected.exists
        ? `The backend could not find ${data.schema || 'public'}.${selected.name}. Check the schema and table names.`
        : `PostgreSQL reports zero rows in ${data.schema || 'public'}.${selected.name}. This is an empty table, not a website loading error.`;
      return;
    }
    $('#dbEmptyState').hidden = true;
    $('#dbTableWrap').hidden = false;
    const columns = Array.isArray(selected.columns) ? selected.columns : [];
    $('#dbTableHead').innerHTML = `<tr>${columns.map(column => `<th scope="col">${esc(column.replaceAll('_', ' '))}</th>`).join('')}</tr>`;
    $('#dbTableBody').innerHTML = selected.rows.map(row => `<tr>${columns.map(column => {
      const value = displayDbValue(row[column]);
      const cellClass = column === 'message_content' || column === 'description' || column === 'internal_note' || column === 'media_url' ? ' class="db-long-cell"' : '';
      return `<td${cellClass} title="${esc(value)}">${esc(value)}</td>`;
    }).join('')}</tr>`).join('');
  }

  async function initializeBackend() {
    try {
      const data = await apiRequest('/api/bootstrap');
      backendConnected = true;
      backendChecking = false;
      backendWritesEnabled = Boolean(data.writes_enabled);
      backendMigrationReady = Boolean(data.database?.migration_ready);
      backendLiveSendingEnabled = Boolean(data.whatsapp_sending_enabled);
      if (Array.isArray(data.members)) demoMembers = data.members.map(m => ({ ...m, id: String(m.id), code: m.code || '', name: m.name || 'Unnamed member', tier: m.tier || 'Unassigned', phase: m.phase || '—' }));
      if (Array.isArray(data.groups)) demoGroups = data.groups.map(g => ({ ...g, id: String(g.id), name: g.name || 'Unnamed group', members: Array.isArray(g.members) ? g.members.map(String) : [] }));
      state.assets = (data.assets || []).map(a => ({ ...a, id: String(a.id), storageMode: 'hosted', serverManaged: Boolean(a.serverManaged), previewUrl: a.previewUrl || a.url || '' }));
      const assetByUrl = new Map(state.assets.filter(a => a.url).map(a => [a.url, a]));
      state.templates = (data.templates || []).map(t => {
        const matchingAsset = t.mediaUrl ? assetByUrl.get(t.mediaUrl) : null;
        return { ...t, id: String(t.id), mediaId: matchingAsset?.id || t.mediaId || '', mediaName: matchingAsset?.name || t.mediaName || '', isExample: false, serverManaged: true };
      });
      populateAudienceOptions();
      const dbTiers = (data.tiers || []).map(t => t.name).filter(Boolean);
      if (dbTiers.length) {
        $('#audienceTier').innerHTML = dbTiers.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('');
        $('#audienceTier').value = dbTiers.includes('Foundation') ? 'Foundation' : dbTiers[0];
      }
      const dbPhases = (data.phases || []).map(p => ({ id: p.id, name: p.name })).filter(p => p.name);
      if (dbPhases.length) $('#audiencePhase').innerHTML = `<option value="all">All phases</option>` + dbPhases.map(p => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
      if (backendLiveSendingEnabled) {
        setConnectionStatus('writing', 'LIVE SENDS ARMED', 'Manual WhatsApp sends are enabled only for allowlisted single recipients and always require confirmation. Scheduler behaviour is unchanged.');
        setConnectionCopy('Connected to the configured database', 'Manual sends are available only to allowlisted members/groups. Drafts and future schedules remain local previews; do not expose this app beyond localhost.', 'Local console · allowlisted manual sends enabled');
      } else if (backendWritesEnabled) {
        setConnectionStatus('writing', 'DATABASE · WRITES ON', 'Database writes are enabled. Live sending remains disabled until the explicit flag, adapter, allowlist, database check, and log schema are ready.');
        setConnectionCopy('Connected to the configured database', 'Media uploads and templates are saved to PostgreSQL. Drafts/schedules are still browser previews unless manual live-send readiness is enabled.', 'Local console · live-send gate is currently off');
      } else if (backendMigrationReady) {
        setConnectionStatus('readonly', 'POSTGRESQL · READ ONLY', 'Database connected, but database writes are disabled in .env.');
        setConnectionCopy('Your local PostgreSQL connection is working', 'Templates are loaded from PostgreSQL. Writes are disabled until we verify the schema and switch to a backed-up test database.', 'Local-only · database connected read-only');
      } else {
        setConnectionStatus('readonly', 'DB CONNECTED · MIGRATION NEEDED', 'Read-only database connection succeeded. Review the SQL migration on a test database before enabling writes.');
        setConnectionCopy('Database connected — read-only check first', 'Your existing templates and audience lists are being read. Media uploads/template saves are blocked until the reviewed migration is applied to a test copy.', 'Local-only · migration needed before writes');
      }
      await refreshDatabaseRecords(false);
      renderAll();
      renderDatabaseExplorer();
    } catch (error) {
      backendConnected = false;
      backendChecking = false;
      backendWritesEnabled = false;
      backendLiveSendingEnabled = false;
      setConnectionStatus('offline', 'BACKEND OFFLINE · PREVIEW', 'The API did not connect. The page is in local preview mode only; it is not connected to PostgreSQL.');
      setConnectionCopy('Backend not connected', 'Start the local API (uvicorn api:app --host 127.0.0.1 --port 8000) and refresh this page. The console is not connected to PostgreSQL.', 'Backend offline');
      dbRecordsError = error.message;
      renderDatabaseExplorer();
      console.warn('Zyvefit backend was not available:', error.message);
    }
  }
  function go(page) {
    const validPages = ['overview', 'media', 'templates', 'database', 'compose', 'outbox'];
    if (!validPages.includes(page)) page = 'overview';
    state.page = page;
    $$('.page').forEach(section => section.classList.toggle('active-page', section.id === `page-${page}`));
    $$('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.page === page));
    const labels = { overview: 'Overview', media: 'Media library', templates: 'Templates', database: 'Database records', compose: 'Compose message', outbox: 'Outbox & schedule' };
    $('#breadcrumbCurrent').textContent = labels[page];
    $('#sidebar').classList.remove('mobile-open');
    if (page === 'media') renderMedia();
    if (page === 'templates') renderTemplates();
    if (page === 'database') renderDatabaseExplorer();
    if (page === 'compose') { renderTemplateSelect(); updateComposer(); }
    if (page === 'outbox') renderOutbox();
    if (page === 'overview') renderOverview();
    window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }

  function openDialog(title, eyebrow, bodyHtml, footerHtml) {
    $('#dialogTitle').textContent = title;
    $('#dialogEyebrow').textContent = eyebrow;
    $('#dialogBody').innerHTML = bodyHtml;
    $('#dialogFooter').innerHTML = footerHtml;
    if (!dialog.open) dialog.showModal();
    const first = $('#dialogBody input:not([type="hidden"]), #dialogBody select, #dialogBody textarea, #dialogBody button');
    if (first) first.focus({ preventScroll: true });
  }
  function closeDialog() {
    if (dialog.open) dialog.close();
    state.dialogContext = null;
  }
  $('#closeDialog').addEventListener('click', closeDialog);
  dialog.addEventListener('click', event => { if (event.target === dialog) closeDialog(); });
  dialog.addEventListener('close', () => { state.dialogContext = null; });

  function showGuide() {
    openDialog('A safe message workflow', 'QUICK GUIDE', `
      <div class="dialog-help-list">
        <div class="dialog-help-item"><span class="dialog-help-num">1</span><div><strong>Scope the media first</strong><p>Use Shared for broadly appropriate content. Mark tier or member-specific material clearly. In database mode, this test backend saves the scope and checks it when templates reference a saved asset.</p></div></div>
        <div class="dialog-help-item"><span class="dialog-help-num">2</span><div><strong>Confirm the exact audience</strong><p>A tier may reach many members. A group may contain more than one member. Check the selected target before planning a message.</p></div></div>
        <div class="dialog-help-item"><span class="dialog-help-num">3</span><div><strong>Preview the final content</strong><p>Review links, attachments, placeholders, language, and the schedule. Tokens are not resolved in this frontend preview.</p></div></div>
        <div class="dialog-help-item"><span class="dialog-help-num">4</span><div><strong>Connect a protected backend</strong><p>Uploads, audience lookup, scheduling, duplicate-send protection, delivery logs, and Periskope calls belong on the server. Never expose API credentials in browser code.</p></div></div>
      </div>
      <div class="dialog-note warning" style="margin-top:16px">Media and templates are saved in PostgreSQL. Drafts and schedule previews stay in this browser. Only a confirmed member/group send reaches WhatsApp, and every attempt is logged in message_logs.</div>
    `, `<button class="button button-primary" id="guideClose">Got it</button>`);
    $('#guideClose').addEventListener('click', closeDialog);
  }
  $('#openGuide').addEventListener('click', showGuide);
  $('#topHelp').addEventListener('click', showGuide);
  $('#bannerDetails').addEventListener('click', showGuide);

  // Navigation and global actions.
  $$('.nav-item').forEach(button => button.addEventListener('click', () => go(button.dataset.page)));
  $('#dbTableSelect').addEventListener('change', event => { activeDbTable = event.target.value; renderDatabaseExplorer(); });
  $('#refreshDbRecords').addEventListener('click', async () => {
    const button = $('#refreshDbRecords');
    button.disabled = true;
    const old = button.innerHTML;
    button.textContent = 'Refreshing…';
    await initializeBackend();
    if (dbRecordsData) notify('Database connection and rows refreshed from PostgreSQL.');
    else notify(dbRecordsError || 'Could not refresh database records.', 'error');
    button.disabled = false;
    button.innerHTML = old;
  });
  $$('[data-go]').forEach(button => button.addEventListener('click', () => go(button.dataset.go)));
  $('#mobileMenu').addEventListener('click', () => $('#sidebar').classList.toggle('mobile-open'));
  document.addEventListener('click', event => {
    const actionButton = event.target.closest('[data-action]');
    if (!actionButton) return;
    const { action, id } = actionButton.dataset;
    if (action === 'asset-edit') openAssetEditor(id);
    else if (action === 'asset-use') {
      const asset = findAsset(String(id));
      if (!asset) { notify('This media item is no longer available. Refresh the Media Library and try again.', 'error'); return; }
      // “Use in message” acts on the specific card the user clicked; it should not
      // open a second picker and ask the user to find that same asset again.
      state.attachedMediaId = String(asset.id);
      go('compose');
      syncAttachedMediaUI();
      updateComposer();
      notify(`“${asset.name}” attached to the message composer. Choose the audience and review before saving a preview.`);
    }
    else if (action === 'asset-delete') deleteAsset(id);
    else if (action === 'template-edit') openTemplateEditor(id);
    else if (action === 'template-use') useTemplate(id);
    else if (action === 'template-delete') deleteTemplate(id);
    else if (action === 'outbox-edit') editOutboxItem(id);
    else if (action === 'outbox-duplicate') duplicateOutboxItem(id);
    else if (action === 'outbox-cancel') cancelOutboxItem(id);
    else if (action === 'outbox-delete') deleteOutboxItem(id);
  });

  // Media library: session-only local files + persistent hosted URL metadata.
  const fileInput = $('#fileInput');
  $('#uploadTopBtn').addEventListener('click', () => fileInput.click());
  $('#chooseFilesBtn').addEventListener('click', () => fileInput.click());
  $('#mediaEmptyAction').addEventListener('click', () => $('#addHostedUrl').click());
  const dropzone = $('#dropzone');
  dropzone.addEventListener('click', event => {
    if (event.target.closest('button')) return;
    fileInput.click();
  });
  ['dragenter', 'dragover'].forEach(type => dropzone.addEventListener(type, event => {
    event.preventDefault(); dropzone.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, event => {
    event.preventDefault(); dropzone.classList.remove('dragging');
  }));
  dropzone.addEventListener('drop', event => addLocalFiles(event.dataTransfer?.files));
  fileInput.addEventListener('change', () => { addLocalFiles(fileInput.files); fileInput.value = ''; });

  async function addLocalFiles(fileList) {
    const files = [...(fileList || [])];
    if (!files.length) return;
    let addedAssets = [];
    const rejected = [];
    for (const file of files) {
      if (file.size > MAX_FILE_BYTES) { rejected.push(`${file.name} is larger than 25 MB`); continue; }
      if (backendConnected) {
        if (!backendWritesEnabled) { rejected.push(`${file.name} not uploaded: database writes are disabled until the test database is prepared.`); continue; }
        const form = new FormData();
        form.append('file', file);
        form.append('name', file.name.replace(/\.[^.]+$/, '').slice(0, 140));
        form.append('scope', 'Shared');
        try {
          const result = await apiRequest('/api/media', { method: 'POST', body: form });
          const asset = { ...result.asset, id: String(result.asset.id), storageMode: 'hosted', serverManaged: true, previewUrl: result.asset.previewUrl || result.asset.url };
          const template = { ...result.template, id: String(result.template.id), serverManaged: true, isExample: false };
          state.assets = [asset, ...state.assets.filter(a => a.id !== asset.id)];
          state.templates = [template, ...state.templates.filter(t => t.id !== template.id)];
          addedAssets.push(asset);
        } catch (error) { rejected.push(`${file.name}: ${error.message}`); }
      } else {
        const type = fileKind(file);
        const url = URL.createObjectURL(file);
        const asset = {
          id: uid('asset'), name: file.name.replace(/\.[^.]+$/, ''), filename: file.name,
          type, scope: 'Shared', tier: '', memberId: '', memberName: '', description: '',
          size: formatSize(file.size), url, previewUrl: url, storageMode: 'local',
          createdAt: new Date().toISOString(), isExample: false
        };
        state.assets.unshift(asset);
        addedAssets.push(asset);
      }
    }
    persist(); renderAll();
    if (addedAssets.length) {
      if (backendConnected) notify(`${addedAssets.length} file${addedAssets.length === 1 ? '' : 's'} uploaded and saved as template record${addedAssets.length === 1 ? '' : 's'} in PostgreSQL.`);
      else notify(`${addedAssets.length} file${addedAssets.length === 1 ? '' : 's'} added as temporary previews. No server upload occurred.`);
    }
    if (rejected.length) notify(rejected.join(' · '), 'error');
    if (addedAssets.length === 1) openAssetEditor(addedAssets[0].id, { newlyAdded: true });
  }

  $('#addHostedUrl').addEventListener('click', () => openAssetEditor('', { hosted: true }));
  $('#mediaSearch').addEventListener('input', renderMedia);
  $('#mediaTypeFilter').addEventListener('change', renderMedia);
  $('#mediaScopeFilter').addEventListener('change', renderMedia);
  $('#clearMediaFilters').addEventListener('click', () => {
    $('#mediaSearch').value = ''; $('#mediaTypeFilter').value = 'all'; $('#mediaScopeFilter').value = 'all'; renderMedia();
  });

  function assetCardVisual(asset, compact = false) {
    const visualType = asset.type === 'PDF' ? 'pdf' : String(asset.type || 'document').toLowerCase();
    const fileIcon = `<span class="large-file-icon">${icon(assetIconName(asset.type))}</span>`;
    let preview = fileIcon;
    if (asset.previewUrl && /^(blob:|https?:\/\/|\/uploads\/)/i.test(asset.previewUrl)) {
      if (asset.type === 'Image') preview = `<img src="${esc(asset.previewUrl)}" alt="Preview of ${esc(asset.name)}" loading="lazy" onerror="this.remove()">`;
      else if (asset.type === 'Audio') preview = `<audio controls preload="none" src="${esc(asset.previewUrl)}" aria-label="Play ${esc(asset.name)}"></audio>`;
      else if (asset.type === 'Video') preview = `<video controls preload="metadata" src="${esc(asset.previewUrl)}" aria-label="Play ${esc(asset.name)}"></video>`;
    }
    return `<div class="media-visual ${esc(visualType)}">${preview}<span class="asset-type-tag">${esc(asset.type)}</span>${asset.storageMode === 'local' ? '<span class="preview-only-tag">SESSION ONLY</span>' : ''}</div>`;
  }
  function scopeLabel(asset) {
    if (asset.scope === 'Member-specific') {
      const member = findMember(asset.memberId);
      return `Member · ${asset.memberName || member?.name || 'Assigned member'}`;
    }
    return asset.scope || 'Shared';
  }
  function renderMedia() {
    const query = $('#mediaSearch').value.trim().toLowerCase();
    const type = $('#mediaTypeFilter').value;
    const scope = $('#mediaScopeFilter').value;
    const matches = state.assets.filter(asset => {
      const searchable = `${asset.name} ${asset.filename} ${asset.description || ''} ${scopeLabel(asset)}`.toLowerCase();
      return searchable.includes(query) && (type === 'all' || asset.type === type) && (scope === 'all' || asset.scope === scope);
    });
    $('#mediaGrid').innerHTML = matches.map(asset => `
      <article class="media-card" data-asset-id="${esc(asset.id)}">
        ${assetCardVisual(asset)}
        <div class="media-card-body">
          <div class="media-card-heading"><strong class="media-card-title">${esc(asset.name)}</strong><button class="media-more" type="button" data-action="asset-edit" data-id="${esc(asset.id)}" aria-label="Edit ${esc(asset.name)}" title="Edit details">•••</button></div>
          <div class="media-file-name" title="${esc(asset.filename || asset.url || '')}">${esc(asset.filename || asset.url || 'Hosted URL not set')}</div>
          <span class="scope-chip ${asset.scope === 'Member-specific' ? 'member-scope' : ''}"><i class="scope-point"></i>${esc(scopeLabel(asset))}</span>
          <div class="asset-card-footer"><span class="asset-meta">${esc(asset.size || (asset.storageMode === 'hosted' ? 'Hosted media' : 'Session preview'))}</span><button class="asset-action" type="button" data-action="asset-use" data-id="${esc(asset.id)}">Use in message ↗</button></div>
        </div>
      </article>`).join('');
    $('#mediaResultCount').textContent = String(matches.length);
    $('#mediaEmpty').hidden = matches.length > 0;
    $('#mediaGrid').hidden = matches.length === 0;
    renderNavigationCounts();
  }
  function scopeOptions(selected = 'Shared') {
    return SCOPES.map(scope => `<option value="${esc(scope)}" ${scope === selected ? 'selected' : ''}>${esc(scope)}</option>`).join('');
  }
  function tierOptions(selected = 'Foundation', includeShared = false) {
    const list = includeShared ? ['Shared', ...TIERS] : TIERS;
    return list.map(tier => `<option value="${esc(tier)}" ${tier === selected ? 'selected' : ''}>${esc(tier)}</option>`).join('');
  }
  function memberOptions(selected = '') {
    return `<option value="">Choose a member</option>` + demoMembers.map(member => `<option value="${esc(member.id)}" ${member.id === selected ? 'selected' : ''}>${esc(member.name)} · ${esc(member.code)} · ${esc(member.tier)}</option>`).join('');
  }
  function mediaOptions(selected = '') {
    return `<option value="">No media attached</option>` + state.assets.map(asset => `<option value="${esc(asset.id)}" ${asset.id === selected ? 'selected' : ''}>${esc(asset.name)} · ${esc(asset.type)} · ${esc(scopeLabel(asset))}${asset.storageMode === 'local' ? ' (session preview)' : ''}</option>`).join('');
  }
  function openAssetEditor(assetId = '', options = {}) {
    const existing = assetId ? findAsset(assetId) : null;
    const hosted = Boolean(options.hosted || (!existing && !assetId));
    const urlEditable = hosted || (existing?.storageMode === 'hosted' && !existing?.serverAssetId && !existing?.serverManaged);
    const title = existing ? 'Edit media details' : 'Add hosted media URL';
    const startName = existing?.name || '';
    const startUrl = existing?.url && existing.storageMode === 'hosted' ? existing.url : '';
    const currentScope = existing?.scope || 'Shared';
    const tier = existing?.tier || 'Foundation';
    const memberId = existing?.memberId || '';
    const type = existing?.type || 'Document';
    const description = existing?.description || '';
    state.dialogContext = { type: 'asset-editor', assetId: existing?.id || '', hosted };
    const body = `
      <form class="dialog-form" id="assetEditorForm" novalidate>
        ${existing && existing.storageMode === 'local' ? `<div class="dialog-note warning">This file is a temporary browser preview, not a server upload. To make it available after refresh or to send it in production, upload it through the backend and store the returned HTTPS URL.</div>` : ''}
        <div class="field"><label for="assetName">Display name <span class="required-mark">*</span></label><input id="assetName" name="assetName" maxlength="140" required value="${esc(startName)}" placeholder="e.g. Foundation weekly meal plan"></div>
        ${urlEditable ? `<div class="field"><label for="assetUrl">Hosted file URL <span class="required-mark">*</span></label><input id="assetUrl" name="assetUrl" type="url" required value="${esc(startUrl)}" placeholder="https://your-storage.example.com/meal-plan.pdf"><small>Use a direct, HTTPS URL that the recipient's WhatsApp client can access. Private signed URLs may expire.</small></div>` : `<div class="dialog-note">File: <strong>${esc(existing?.filename || '')}</strong> · ${esc(existing?.size || '')}</div>`}
        <div class="dialog-grid">
          <div class="field"><label for="assetType">Media type</label><select id="assetType" name="assetType">${TYPES.filter(t => t !== 'Text').map(t => `<option value="${esc(t)}" ${(type === t || (type === 'PDF' && t === 'Document')) ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div>
          <div class="field"><label for="assetScope">Audience scope <span class="required-mark">*</span></label><select id="assetScope" name="assetScope">${scopeOptions(currentScope)}</select></div>
        </div>
        <div class="field" id="assetTierWrap" ${TIERS.includes(currentScope) ? '' : 'hidden'}><label for="assetTier">Tier <span class="required-mark">*</span></label><select id="assetTier" name="assetTier">${tierOptions(tier)}</select></div>
        <div class="field" id="assetMemberWrap" ${currentScope === 'Member-specific' ? '' : 'hidden'}><label for="assetMember">Member <span class="required-mark">*</span></label><select id="assetMember" name="assetMember">${memberOptions(memberId)}</select></div>
        <div class="field"><label for="assetDescription">Internal note <span class="optional-label">Optional</span></label><textarea id="assetDescription" name="assetDescription" rows="2" maxlength="500" placeholder="What is this asset for?">${esc(description)}</textarea><small>Internal metadata only. Do not add sensitive health information unless the production system is approved for it.</small></div>
        <div class="dialog-note">Audience scope is saved by this local backend when the database migration is installed. Recipient eligibility must still be rechecked before any future WhatsApp sending.</div>
      </form>`;
    const footer = `${existing ? `<button class="button button-quiet danger-link" id="deleteAssetFromEditor" type="button">${icon('trash')} Delete</button>` : ''}<span style="flex:1"></span><button class="button button-secondary" id="cancelAssetEditor" type="button">Cancel</button><button class="button button-primary" type="submit" form="assetEditorForm">Save details</button>`;
    openDialog(title, 'MEDIA LIBRARY', body, footer);
    $('#cancelAssetEditor').addEventListener('click', closeDialog);
    const syncScope = () => {
      const scope = $('#assetScope').value;
      $('#assetTierWrap').hidden = !TIERS.includes(scope);
      $('#assetMemberWrap').hidden = scope !== 'Member-specific';
    };
    $('#assetScope').addEventListener('change', syncScope);
    $('#assetEditorForm').addEventListener('submit', async event => {
      event.preventDefault();
      const name = $('#assetName').value.trim();
      const scope = $('#assetScope').value;
      const assetType = $('#assetType').value;
      const assetTier = TIERS.includes(scope) ? $('#assetTier').value : '';
      const selectedMember = scope === 'Member-specific' ? findMember($('#assetMember').value) : null;
      const url = urlEditable ? $('#assetUrl').value.trim() : (existing?.url || '');
      if (!name) { notify('Enter a display name for this asset.', 'error'); $('#assetName').focus(); return; }
      if (urlEditable && !safeExternalUrl(url)) { notify('Enter a valid HTTPS URL without embedded credentials.', 'error'); $('#assetUrl').focus(); return; }
      if (scope === 'Member-specific' && !selectedMember) { notify('Choose the member this media belongs to.', 'error'); $('#assetMember').focus(); return; }
      const values = {
        name, type: assetType === 'Document' && existing?.type === 'PDF' ? 'PDF' : assetType,
        scope, tier: assetTier, memberId: selectedMember?.id || '', memberName: selectedMember?.name || '',
        description: $('#assetDescription').value.trim(),
        ...(urlEditable ? { filename: url.split('/').pop()?.split('?')[0] || name, url, previewUrl: url, storageMode: 'hosted', size: '' } : {})
      };
      if (backendConnected) {
        if (!backendWritesEnabled) { notify('Database writes are disabled. First finish the read-only check and use a backed-up test database.', 'error'); return; }
        try {
          if (existing?.serverAssetId) {
            const updated = await apiRequest(`/api/media/${encodeURIComponent(existing.serverAssetId)}`, { method: 'PUT', body: JSON.stringify({ name, scope, tier: assetTier || null, member_id: selectedMember?.id || null, description: values.description }) });
            Object.assign(existing, values, updated, { id: existing.id, serverAssetId: existing.serverAssetId, serverManaged: true, previewUrl: updated.previewUrl || updated.url });
            const sourceTemplate = state.templates.find(t => t.isMediaTemplate && t.mediaId === existing.id);
            if (sourceTemplate) { sourceTemplate.name = name; sourceTemplate.scope = scope; sourceTemplate.memberId = selectedMember?.id || ''; sourceTemplate.memberName = selectedMember?.name || ''; }
          } else if (!existing && urlEditable) {
            const result = await apiRequest('/api/media/link', { method: 'POST', body: JSON.stringify({ url, name, scope, tier: assetTier || null, member_id: selectedMember?.id || null, description: values.description }) });
            const asset = { ...result.asset, id: String(result.asset.id), storageMode: 'hosted', serverManaged: true, previewUrl: result.asset.previewUrl || result.asset.url };
            const template = { ...result.template, id: String(result.template.id), serverManaged: true, isExample: false };
            state.assets = [asset, ...state.assets.filter(a => a.id !== asset.id)];
            state.templates = [template, ...state.templates.filter(t => t.id !== template.id)];
          } else {
            notify('This older hosted URL does not have a media-library record yet. Keep it as a reference or create a new hosted media item.', 'error'); return;
          }
          persist(); closeDialog(); renderAll(); notify('Media details saved to PostgreSQL.');
        } catch (error) { notify(error.message, 'error'); }
        return;
      }
      if (existing) {
        Object.assign(existing, values, { isExample: false });
      } else {
        state.assets.unshift({ id: uid('asset'), ...values, createdAt: new Date().toISOString(), isExample: false });
      }
      persist(); closeDialog(); renderAll();
      notify(existing ? 'Media details updated in this browser.' : 'Hosted URL registered in this browser. The file itself was not uploaded.');
    });
    if (existing) $('#deleteAssetFromEditor').addEventListener('click', () => deleteAsset(existing.id, true));
    syncScope();
  }
  function assetUsedElsewhere(assetId) {
    const byTemplate = state.templates.some(template => template.mediaId === assetId && !template.isMediaTemplate);
    const byOutbox = state.outbox.some(item => item.mediaId === assetId && item.status !== 'Cancelled');
    return { byTemplate, byOutbox };
  }
  async function deleteAsset(id, fromDialog = false) {
    const asset = findAsset(id);
    if (!asset) return;
    const refs = assetUsedElsewhere(id);
    if (refs.byTemplate || refs.byOutbox) {
      notify('This media is referenced by a template or outbox item. Remove that reference first.', 'error');
      return;
    }
    if (!window.confirm(`Remove “${asset.name}” from this media library?`)) return;
    if (backendConnected) {
      if (!backendWritesEnabled) { notify('Database writes are disabled. No media was deleted.', 'error'); return; }
      if (!asset.serverAssetId) { notify('This is a legacy media URL without a media_assets record. It cannot be deleted from this screen yet.', 'error'); return; }
      try {
        await apiRequest(`/api/media/${encodeURIComponent(asset.serverAssetId)}`, { method: 'DELETE' });
        state.templates = state.templates.filter(t => !(t.isMediaTemplate && t.mediaId === id));
        state.assets = state.assets.filter(item => item.id !== id);
        if (state.attachedMediaId === id) state.attachedMediaId = '';
        if (fromDialog) closeDialog();
        persist(); renderAll(); notify('Media and its auto-created template record were deleted from the database.');
      } catch (error) { notify(error.message, 'error'); }
      return;
    }
    if (asset.storageMode === 'local' && asset.url?.startsWith('blob:')) URL.revokeObjectURL(asset.url);
    state.assets = state.assets.filter(item => item.id !== id);
    if (state.attachedMediaId === id) state.attachedMediaId = '';
    if (fromDialog) closeDialog();
    persist(); renderAll(); notify('Media removed from the local library.');
  }

  // Templates: all data stays in localStorage until an API is connected.
  $('#createTemplateBtn').addEventListener('click', () => openTemplateEditor(''));
  $('#templateEmptyAction').addEventListener('click', () => openTemplateEditor(''));
  $('#templateSearch').addEventListener('input', renderTemplates);
  $('#templateTierFilter').addEventListener('change', renderTemplates);
  $('#templateTypeFilter').addEventListener('change', renderTemplates);
  $('#clearTemplateFilters').addEventListener('click', () => {
    $('#templateSearch').value = ''; $('#templateTierFilter').value = 'all'; $('#templateTypeFilter').value = 'all'; renderTemplates();
  });
  $('#manageTemplatesFromComposer').addEventListener('click', () => go('templates'));
  function openTemplateEditor(templateId = '') {
    const existing = templateId ? findTemplate(templateId) : null;
    const initial = existing || { name: '', code: '', scope: 'Shared', memberId: '', type: 'Text', language: 'en', content: '', mediaId: '', mediaName: '' };
    const mediaExists = initial.mediaId && findAsset(initial.mediaId);
    const body = `
      <form class="dialog-form" id="templateEditorForm" novalidate>
        <div class="field"><label for="templateName">Template name <span class="required-mark">*</span></label><input id="templateName" maxlength="140" required value="${esc(initial.name)}" placeholder="e.g. Weekly meal plan delivery"></div>
        <div class="field"><label for="templateCode">Template code <span class="required-mark">*</span></label><input id="templateCode" maxlength="100" required value="${esc(initial.code || slugify(initial.name))}" placeholder="WEEKLY_MEAL_PLAN"><small>Stable identifier for backend mapping. Use uppercase letters, numbers, and underscores.</small></div>
        <div class="dialog-grid">
          <div class="field"><label for="templateScope">Audience scope</label><select id="templateScope">${scopeOptions(initial.scope)}</select></div>
          <div class="field"><label for="templateType">Message type</label><select id="templateType" ${initial.isMediaTemplate ? 'disabled' : ''}>${TYPES.map(type => `<option value="${esc(type)}" ${type === initial.type ? 'selected' : ''}>${esc(type)}</option>`).join('')}</select></div>
        </div>
        <div class="field" id="templateMemberWrap" ${initial.scope === 'Member-specific' ? '' : 'hidden'}><label for="templateMember">Assigned member <span class="required-mark">*</span></label><select id="templateMember">${memberOptions(initial.memberId)}</select></div>
        <div class="dialog-grid">
          <div class="field"><label for="templateLanguage">Language</label><select id="templateLanguage"><option value="en" ${initial.language === 'en' ? 'selected' : ''}>English (en)</option><option value="hi" ${initial.language === 'hi' ? 'selected' : ''}>Hindi (hi)</option></select></div>
          <div class="field"><label for="templateMedia">Attach media <span class="optional-label">Optional for text</span></label><select id="templateMedia" ${initial.isMediaTemplate ? 'disabled' : ''}>${mediaOptions(initial.mediaId || '')}</select></div>
        </div>
        <div class="field" id="templateUploadField" ${initial.isMediaTemplate ? 'hidden' : ''}>
          <label for="templateUploadFile">Upload media directly</label>
          <div class="dialog-grid">
            <input id="templateUploadFile" type="file" accept=".png,.jpg,.jpeg,.webp,.gif,.mp3,.wav,.m4a,.aac,.ogg,.opus,.mp4,.mov,.webm,.m4v,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv">
            <button class="button button-secondary" id="templateUploadBtn" type="button">Upload and attach</button>
          </div>
          <small>Uploads the file to the media library and selects it for this template without creating a second template record.</small>
        </div>
        <div class="field"><label for="templateContent">Message content / caption <span class="required-mark">*</span></label><textarea id="templateContent" maxlength="4096" rows="5" required placeholder="Write the message content…">${esc(initial.content)}</textarea><small>Template tokens are not resolved in this preview. The backend must validate and replace supported placeholders.</small></div>
        ${initial.mediaId && !mediaExists ? `<div class="dialog-note warning">The previously attached file “${esc(initial.mediaName || 'Unnamed media')}” is no longer present in this browser session. Re-add or choose another file before using the template.</div>` : ''}
        <div class="dialog-note">Maps conceptually to <code>templates.template_code</code>, <code>template_name</code>, <code>message_type</code>, <code>message_content</code>, <code>media_url</code>, and <code>language</code>. Template audience scope is stored in PostgreSQL after the local migration is applied. WhatsApp delivery remains disabled in this build.</div>
      </form>`;
    const footer = `${existing ? `<button class="button button-quiet danger-link" id="deleteTemplateFromEditor" type="button">${icon('trash')} Delete</button>` : ''}<span style="flex:1"></span><button class="button button-secondary" id="cancelTemplateEditor" type="button">Cancel</button><button class="button button-primary" type="submit" form="templateEditorForm">Save template</button>`;
    openDialog(existing ? 'Edit template' : 'Create a template', 'TEMPLATE EDITOR', body, footer);
    $('#cancelTemplateEditor').addEventListener('click', closeDialog);
    $('#templateName').addEventListener('input', () => {
      if (!existing || !$('#templateCode').dataset.touched) $('#templateCode').value = slugify($('#templateName').value);
    });
    $('#templateCode').addEventListener('input', () => { $('#templateCode').dataset.touched = 'true'; });
    $('#templateScope').addEventListener('change', () => { $('#templateMemberWrap').hidden = $('#templateScope').value !== 'Member-specific'; });
    if (!initial.isMediaTemplate) {
      $('#templateUploadBtn').addEventListener('click', async () => {
        const input = $('#templateUploadFile');
        const file = input.files?.[0];
        if (!file) { notify('Choose an image, audio, video, or document first.', 'error'); input.focus(); return; }
        if (file.size > MAX_FILE_BYTES) { notify('This file is larger than the 25 MB upload limit.', 'error'); return; }
        const scope = $('#templateScope').value;
        const selectedMemberId = scope === 'Member-specific' ? $('#templateMember').value : '';
        if (scope === 'Member-specific' && !selectedMemberId) { notify('Choose the assigned member before uploading member-specific media.', 'error'); return; }
        const button = $('#templateUploadBtn');
        button.disabled = true; button.textContent = 'Uploading…';
        try {
          let asset;
          if (backendConnected) {
            if (!backendWritesEnabled) throw new Error('Database writes are disabled. Point the backend at the test database and enable writes only there.');
            const form = new FormData();
            form.append('file', file);
            form.append('name', file.name.replace(/\.[^.]+$/, '').slice(0, 140));
            form.append('scope', scope);
            form.append('tier', TIERS.includes(scope) ? scope : '');
            form.append('member_id', selectedMemberId);
            form.append('description', 'Uploaded from the template editor');
            form.append('create_template', 'false');
            const result = await apiRequest('/api/media', { method: 'POST', body: form });
            asset = { ...result.asset, id: String(result.asset.id), storageMode: 'hosted', serverManaged: true, previewUrl: result.asset.previewUrl || result.asset.url };
            state.assets = [asset, ...state.assets.filter(existingAsset => existingAsset.id !== asset.id)];
          } else {
            const type = fileKind(file);
            const url = URL.createObjectURL(file);
            const member = selectedMemberId ? findMember(selectedMemberId) : null;
            asset = {
              id: uid('asset'), name: file.name.replace(/\.[^.]+$/, ''), filename: file.name, type,
              scope, tier: TIERS.includes(scope) ? scope : '', memberId: selectedMemberId, memberName: member?.name || '',
              description: 'Uploaded from the template editor', size: formatSize(file.size), url, previewUrl: url,
              storageMode: 'local', createdAt: new Date().toISOString(), isExample: false
            };
            state.assets.unshift(asset);
          }
          const mediaSelect = $('#templateMedia');
          mediaSelect.innerHTML = mediaOptions(String(asset.id));
          mediaSelect.value = String(asset.id);
          const inferredType = asset.type === 'PDF' ? 'Document' : asset.type;
          if (TYPES.includes(inferredType) && inferredType !== 'Location') $('#templateType').value = inferredType;
          persist();
          if (backendConnected) notify(`“${asset.name}” uploaded to PostgreSQL and attached. No extra media template was created.`);
          else notify(`“${asset.name}” attached as a temporary preview only; it will not survive a page refresh.`);
        } catch (error) {
          notify(error.message || 'Media upload failed.', 'error');
        } finally {
          button.disabled = false; button.textContent = 'Upload and attach';
          input.value = '';
        }
      });
    }
    $('#templateEditorForm').addEventListener('submit', async event => {
      event.preventDefault();
      const name = $('#templateName').value.trim();
      const code = $('#templateCode').value.trim().toUpperCase();
      const scope = $('#templateScope').value;
      const type = $('#templateType').value;
      const language = $('#templateLanguage').value;
      const content = $('#templateContent').value.trim();
      const mediaId = $('#templateMedia').value;
      const member = scope === 'Member-specific' ? findMember($('#templateMember').value) : null;
      if (!name || !code || !content) { notify('Add a name, code, and message content before saving.', 'error'); return; }
      if (!/^[A-Z0-9_]+$/.test(code)) { notify('Template code may contain only uppercase letters, numbers, and underscores.', 'error'); $('#templateCode').focus(); return; }
      const duplicateCode = state.templates.find(item => item.code.toUpperCase() === code && item.id !== existing?.id);
      if (duplicateCode) { notify(`The code ${code} is already used by another template.`, 'error'); $('#templateCode').focus(); return; }
      if (scope === 'Member-specific' && !member) { notify('Choose a member for this member-specific template.', 'error'); return; }
      if (mediaId && !findAsset(mediaId)) { notify('The selected media is no longer available. Choose another asset.', 'error'); return; }
      const media = mediaId ? findAsset(mediaId) : null;
      const item = {
        id: existing?.id || uid('tpl'), code, name, scope,
        memberId: member?.id || '', memberName: member?.name || '', type, language, content,
        mediaId: media?.id || '', mediaName: media?.name || '', mediaType: media?.type || '',
        mediaUrl: media?.storageMode === 'hosted' ? media.url : '', updatedAt: new Date().toISOString(), isExample: false
      };
      if (backendConnected) {
        if (!backendWritesEnabled) { notify('Database writes are disabled. First finish the read-only check and use a backed-up test database.', 'error'); return; }
        try {
          const payload = templateApiPayload(item, media);
          const savedTemplate = await apiRequest(existing?.serverManaged ? `/api/templates/${encodeURIComponent(existing.id)}` : '/api/templates', {
            method: existing?.serverManaged ? 'PUT' : 'POST', body: JSON.stringify(payload)
          });
          const normalized = { ...savedTemplate, id: String(savedTemplate.id), serverManaged: true, isExample: false,
            ...(media ? { mediaId: media.id, mediaName: media.name, mediaType: media.type, mediaUrl: media.url } : {}) };
          if (existing) state.templates = state.templates.map(t => t.id === existing.id ? normalized : t);
          else state.templates.unshift(normalized);
          if (normalized.isMediaTemplate && normalized.mediaId) {
            const sourceAsset = findAsset(normalized.mediaId);
            if (sourceAsset) Object.assign(sourceAsset, { name: normalized.name, scope: normalized.scope, tier: TIERS.includes(normalized.scope) ? normalized.scope : '', memberId: normalized.memberId || '', memberName: normalized.memberName || '' });
          }
          persist(); closeDialog(); renderAll(); notify('Template saved to PostgreSQL. No WhatsApp message was sent.');
        } catch (error) { notify(error.message, 'error'); }
        return;
      }
      if (existing) Object.assign(existing, item);
      else state.templates.unshift(item);
      persist(); closeDialog(); renderAll(); notify('Template saved to this browser preview.');
    });
    if (existing) $('#deleteTemplateFromEditor').addEventListener('click', () => deleteTemplate(existing.id, true));
  }
  function renderTemplates() {
    const q = $('#templateSearch').value.trim().toLowerCase();
    const scope = $('#templateTierFilter').value;
    const type = $('#templateTypeFilter').value;
    const matches = state.templates.filter(template => {
      const search = `${template.name} ${template.code} ${template.content} ${template.scope}`.toLowerCase();
      return search.includes(q) && (scope === 'all' || template.scope === scope) && (type === 'all' || template.type === type);
    });
    $('#templateGrid').innerHTML = matches.map(template => {
      const mediaName = template.mediaId ? mediaNameFor(template.mediaId, template.mediaName) : '';
      const unavailable = template.mediaId && !findAsset(template.mediaId);
      return `<article class="template-card">
        <div class="template-card-top"><span class="template-type-icon ${templateTypeClass(template.type)}">${icon(assetIconName(template.type))}</span><div class="template-title-block"><strong>${esc(template.name)}</strong><div class="template-code">${esc(template.code)}</div></div><div class="template-top-actions"><button type="button" class="icon-button-small" data-action="template-edit" data-id="${esc(template.id)}" aria-label="Edit ${esc(template.name)}" title="Edit">${icon('edit')}</button></div></div>
        <p class="template-content-preview">${esc(template.content)}</p>
        <div class="template-card-bottom"><div class="template-badges"><span class="template-type-badge">${esc(template.type)}</span><span class="scope-chip ${template.scope === 'Member-specific' ? 'member-scope' : ''}">${esc(template.scope === 'Member-specific' ? `Member · ${template.memberName || findMember(template.memberId)?.name || 'Assigned'}` : template.scope)}</span></div><button type="button" class="template-use-btn" data-action="template-use" data-id="${esc(template.id)}">Use in message ↗</button></div>
        ${template.mediaId ? `<div class="template-attachment" style="margin-top:10px">${icon('file')}<span title="${esc(mediaName)}">${esc(mediaName)}${unavailable ? ' · re-add file' : ''}</span></div>` : ''}
      </article>`;
    }).join('');
    $('#templateResultCount').textContent = String(matches.length);
    $('#templateGrid').hidden = matches.length === 0;
    $('#templateEmpty').hidden = matches.length > 0;
    renderTemplateSelect(); renderNavigationCounts();
  }
  async function deleteTemplate(id, fromDialog = false) {
    const template = findTemplate(id);
    if (!template) return;
    if (!window.confirm(`Delete template “${template.name}”? This cannot be undone.`)) return;
    if (backendConnected) {
      if (!backendWritesEnabled) { notify('Database writes are disabled. No template was deleted.', 'error'); return; }
      try {
        if (template.isMediaTemplate && template.mediaId) {
          const asset = findAsset(template.mediaId);
          if (!asset?.serverAssetId) { notify('The upload media record could not be found. Delete it from the Media Library instead.', 'error'); return; }
          await apiRequest(`/api/media/${encodeURIComponent(asset.serverAssetId)}`, { method: 'DELETE' });
          state.assets = state.assets.filter(a => a.id !== asset.id);
        } else {
          await apiRequest(`/api/templates/${encodeURIComponent(template.id)}`, { method: 'DELETE' });
        }
        state.templates = state.templates.filter(item => item.id !== id);
        if (fromDialog) closeDialog();
        persist(); renderAll(); notify('Template removed from the database.');
      } catch (error) { notify(error.message, 'error'); }
      return;
    }
    state.templates = state.templates.filter(item => item.id !== id);
    if (fromDialog) closeDialog();
    persist(); renderAll(); notify('Template deleted from the local preview.');
  }

  // Message composer and live preview.
  function renderTemplateSelect() {
    const select = $('#templateSelect');
    if (!select) return;
    const previous = select.value;
    select.innerHTML = `<option value="">Write from scratch</option>` + state.templates.map(template => `<option value="${esc(template.id)}">${esc(template.name)} · ${esc(template.scope)}</option>`).join('');
    if (state.templates.some(template => template.id === previous)) select.value = previous;
  }
  function useTemplate(id) {
    const template = findTemplate(id);
    if (!template) return;
    if (template.scope === 'Member-specific') {
      state.audienceMode = 'member';
      $('#audienceMember').value = template.memberId || '';
    } else if (TIERS.includes(template.scope)) {
      state.audienceMode = 'tier';
      $('#audienceTier').value = template.scope;
    }
    setAudienceMode(state.audienceMode);
    $('#templateSelect').value = template.id;
    $('#messageTitle').value = template.name;
    $('#messageBody').value = template.content;
    state.attachedMediaId = template.mediaId || '';
    syncAttachedMediaUI();
    go('compose');
    updateComposer();
    notify('Template loaded into the composer. Review the audience and content before adding it to the outbox.');
  }
  $('#templateSelect').addEventListener('change', () => {
    const template = findTemplate($('#templateSelect').value);
    if (!template) return;
    $('#messageTitle').value = template.name;
    $('#messageBody').value = template.content;
    state.attachedMediaId = template.mediaId || '';
    if (template.scope === 'Member-specific' && findMember(template.memberId)) {
      $('#audienceMember').value = template.memberId;
      setAudienceMode('member');
    } else if (TIERS.includes(template.scope)) {
      $('#audienceTier').value = template.scope;
      setAudienceMode('tier');
    }
    syncAttachedMediaUI(); updateComposer();
  });
  $$('#audienceTabs [data-audience]').forEach(button => button.addEventListener('click', () => setAudienceMode(button.dataset.audience)));
  $('#audienceTier').addEventListener('change', updateComposer);
  $('#audiencePhase').addEventListener('change', updateComposer);
  $('#audienceMember').addEventListener('change', updateComposer);
  $('#audienceGroup').addEventListener('change', updateComposer);
  $('#messageTitle').addEventListener('input', updateComposer);
  $('#messageBody').addEventListener('input', updateComposer);
  $$('[data-token]').forEach(button => button.addEventListener('click', () => {
    const body = $('#messageBody');
    const start = body.selectionStart ?? body.value.length;
    const end = body.selectionEnd ?? body.value.length;
    body.setRangeText(button.dataset.token, start, end, 'end');
    body.focus(); updateComposer();
  }));
  $$('input[name="delivery"]').forEach(input => input.addEventListener('change', updateComposer));
  $('#scheduleDate').min = todayIST();
  const suggestedSchedule = suggestedISTSchedule();
  $('#scheduleDate').value = suggestedSchedule.date;
  $('#scheduleTime').value = suggestedSchedule.time;
  $('#scheduleDate').addEventListener('change', updateComposer);
  $('#scheduleTime').addEventListener('change', updateComposer);
  $('#attachMediaBtn').addEventListener('click', () => openMediaPicker({ kind: 'composer' }, state.attachedMediaId));
  $('#removeMediaBtn').addEventListener('click', () => { state.attachedMediaId = ''; syncAttachedMediaUI(); updateComposer(); });
  $('#resetComposer').addEventListener('click', () => {
    if (!window.confirm('Clear the composer? This will not delete items already in the outbox.')) return;
    resetComposer(); notify('Composer cleared.');
  });

  function populateAudienceOptions() {
    $('#audienceMember').innerHTML = memberOptions('');
    $('#audienceGroup').innerHTML = `<option value="">Choose a group</option>` + demoGroups.map(group => `<option value="${esc(group.id)}">${esc(group.name)}</option>`).join('');
  }
  function setAudienceMode(mode) {
    state.audienceMode = mode;
    $$('#audienceTabs [data-audience]').forEach(button => button.classList.toggle('selected', button.dataset.audience === mode));
    $('#tierFields').hidden = mode !== 'tier';
    $('#memberFields').hidden = mode !== 'member';
    $('#groupFields').hidden = mode !== 'group';
    updateComposer();
  }
  function getAudience() {
    if (state.audienceMode === 'member') {
      const member = findMember($('#audienceMember').value);
      return member ? { mode: 'member', id: member.id, label: `${member.name} · ${member.code}`, description: `${member.tier} · ${member.phase}`, member } : { mode: 'member', id: '', label: '', description: '' };
    }
    if (state.audienceMode === 'group') {
      const group = findGroup($('#audienceGroup').value);
      return group ? { mode: 'group', id: group.id, label: group.name, description: `${group.members.length} member${group.members.length === 1 ? '' : 's'}`, group } : { mode: 'group', id: '', label: '', description: '' };
    }
    const tier = $('#audienceTier').value;
    const phase = $('#audiencePhase').value;
    return { mode: 'tier', id: tier, label: `${tier}${phase !== 'all' ? ` · ${phase}` : ' · All phases'}`, description: phase === 'all' ? 'All phases' : `Phase ${phase}`, tier, phase };
  }
  function getSelectedDelivery() { return $('input[name="delivery"]:checked')?.value || 'now'; }
  function selectedAsset() { return state.attachedMediaId ? findAsset(state.attachedMediaId) : null; }
  function getAssetScopeIssue(asset, audience) {
    if (!asset || asset.scope === 'Shared') return '';
    if (asset.scope === 'Member-specific') {
      const member = findMember(asset.memberId);
      if (audience.mode !== 'member') return 'Member-specific media can only be used for that individual member.';
      if (!member || audience.member?.id !== member.id) return 'This media is scoped to a different member.';
      return '';
    }
    if (TIERS.includes(asset.scope)) {
      if (audience.mode === 'group') return 'Group audiences cannot be matched against tier-scoped media here. Use Shared media or verify this scope in the backend.';
      const audienceTier = audience.mode === 'tier' ? audience.tier : audience.member?.tier;
      if (audienceTier !== asset.scope) return `This media is scoped to ${asset.scope}, but the selected audience is ${audienceTier || 'unknown'}.`;
    }
    return '';
  }
  function syncAttachedMediaUI() {
    const asset = selectedAsset();
    if (!asset) {
      $('#attachedMediaTitle').textContent = state.attachedMediaId ? 'Media needs to be re-added' : 'No media attached';
      $('#attachedMediaDescription').textContent = state.attachedMediaId ? 'This file was added in an earlier browser session. Re-upload it or attach a hosted URL.' : 'Attach one item from your library, or add a hosted URL in Media library.';
      $('#attachedMediaWarning').hidden = !state.attachedMediaId;
      $('#attachedMediaWarning').textContent = state.attachedMediaId ? 'Attachment reference no longer has a file preview.' : '';
      $('#removeMediaBtn').hidden = !state.attachedMediaId;
      $('#attachMediaBtn').textContent = 'Choose media';
      return;
    }
    $('#attachedMediaTitle').textContent = asset.name;
    $('#attachedMediaDescription').textContent = `${asset.type} · ${scopeLabel(asset)} · ${asset.storageMode === 'local' ? 'temporary session preview' : asset.serverAssetId ? 'saved on local server' : 'hosted URL registered'}`;
    const warning = asset.storageMode === 'local' ? 'Temporary file: it is not hosted or sent to any server.' : '';
    $('#attachedMediaWarning').textContent = warning;
    $('#attachedMediaWarning').hidden = !warning;
    $('#removeMediaBtn').hidden = false;
    $('#attachMediaBtn').textContent = 'Change media';
  }
  function updatePreviewChecklist(audience, text, asset, delivery) {
    const audienceOK = Boolean(audience.id);
    const contentOK = Boolean(text.trim() || asset);
    const scheduleDate = $('#scheduleDate').value;
    const scheduleTime = $('#scheduleTime').value;
    const futureOK = delivery !== 'schedule' || Boolean(istDateTime(scheduleDate, scheduleTime) && istDateTime(scheduleDate, scheduleTime).getTime() > Date.now());
    const deliveryOK = delivery !== 'schedule' || futureOK;
    const setCheck = (id, textId, ok, message, failMessage) => {
      const el = $(id); el.classList.toggle('done', ok); el.textContent = ok ? '✓' : '•';
      $(textId).textContent = ok ? message : failMessage;
    };
    setCheck('#checkAudience', '#checkAudienceText', audienceOK, 'Audience selected', 'Choose the intended audience');
    setCheck('#checkContent', '#checkContentText', contentOK, 'Message text or media attached', 'Add text or attach media');
    setCheck('#checkDelivery', '#checkDeliveryText', deliveryOK, delivery === 'schedule' ? 'Future delivery time selected' : delivery === 'draft' ? 'Ready to save as draft' : (backendLiveSendingEnabled ? (audience.mode === 'tier' ? 'Select one member or group' : 'Ready for allowlisted live send') : 'Ready for queue preview'), delivery === 'schedule' ? 'Select a future date and time' : 'Choose a delivery plan');
  }
  function updateComposer() {
    const audience = getAudience();
    const text = $('#messageBody').value;
    const asset = selectedAsset();
    const delivery = getSelectedDelivery();
    $('#charCount').textContent = `${text.length} / 4096`;
    $('#previewText').textContent = text.trim() || (asset ? 'Media preview. Add an optional caption above.' : 'Your message preview will appear here as you type.');
    $('#previewGroupName').textContent = audience.id ? audience.label : (state.audienceMode === 'tier' ? $('#audienceTier').value : 'Choose an audience');
    const mediaCard = $('#previewMediaCard');
    mediaCard.hidden = !state.attachedMediaId;
    if (state.attachedMediaId) {
      $('#previewMediaName').textContent = asset?.name || 'Media needs to be re-added';
      $('#previewMediaMeta').textContent = asset ? `${asset.type} · ${asset.storageMode === 'local' ? 'temporary preview only' : asset.serverAssetId ? 'saved on local server' : 'hosted URL'}` : 'Re-upload this media';
      $('#previewMediaIcon').innerHTML = icon(assetIconName(asset?.type || 'Document'));
    }
    $('#scheduleFields').hidden = delivery !== 'schedule';
    $$('.delivery-card').forEach(card => card.classList.toggle('selected', card.querySelector('input').checked));
    const submit = $('#submitComposer');
    if (delivery === 'draft') { submit.innerHTML = `${icon('file')}<span>Save draft</span>`; }
    else if (delivery === 'schedule') { submit.innerHTML = `${icon('calendar')}<span>Schedule preview</span>`; }
    else if (backendLiveSendingEnabled && audience.mode !== 'tier') { submit.innerHTML = `${icon('send')}<span>Send live message</span>`; }
    else if (backendLiveSendingEnabled) { submit.innerHTML = `${icon('send')}<span>Select one recipient</span>`; }
    else { submit.innerHTML = `${icon('send')}<span>Add to preview queue</span>`; }
    const audienceHint = state.audienceMode === 'tier'
      ? 'A tier may include many eligible members. Check that the content is suitable for everyone in the selected tier and phase. Direct sends require one member or group.'
      : state.audienceMode === 'member'
        ? 'Targets one member from the database. The backend verifies member access and status before sending.'
        : 'Group membership comes from the database. Confirm the group and its members before sending.';
    $('#audienceHint').textContent = audienceHint;
    const scopeIssue = getAssetScopeIssue(asset, audience);
    $('#attachedMediaWarning').hidden = !(scopeIssue || (asset?.storageMode === 'local'));
    $('#attachedMediaWarning').textContent = scopeIssue || (asset?.storageMode === 'local' ? 'Temporary file: not uploaded to the backend.' : '');
    updatePreviewChecklist(audience, text, asset, delivery);
  }
  function openMediaPicker(context = { kind: 'composer' }, selectedId = '') {
    const usable = state.assets;
    const body = usable.length ? `<div class="dialog-form"><p class="page-subtitle" style="margin-bottom:2px">Choose one asset. Scope conflicts will be flagged in the composer.</p><label class="media-pick-row ${!selectedId ? 'selected' : ''}"><input type="radio" name="mediaChoice" value="" ${!selectedId ? 'checked' : ''}><span class="media-pick-icon">${icon('close')}</span><span class="media-pick-copy"><strong>No media</strong><small>Text-only message</small></span></label>${usable.map(asset => `<label class="media-pick-row ${asset.id === selectedId ? 'selected' : ''}"><input type="radio" name="mediaChoice" value="${esc(asset.id)}" ${asset.id === selectedId ? 'checked' : ''}><span class="media-pick-icon">${icon(assetIconName(asset.type))}</span><span class="media-pick-copy"><strong>${esc(asset.name)}</strong><small>${esc(asset.type)} · ${esc(scopeLabel(asset))}${asset.storageMode === 'local' ? ' · session preview' : ''}</small></span><span class="media-pick-radio"></span></label>`).join('')}</div>` : `<div class="empty-state"><span class="empty-state-icon">${icon('library')}</span><h3>Your library is empty</h3><p>Add a local file preview or hosted media URL before attaching it here.</p><button class="button button-secondary" id="goAddMediaFromPicker" type="button">Open media library</button></div>`;
    const footer = `<button class="button button-secondary" id="cancelMediaPicker" type="button">Cancel</button><button class="button button-primary" id="confirmMediaPicker" type="button" ${usable.length ? '' : 'disabled'}>Attach selected media</button>`;
    state.dialogContext = { type: 'media-picker', context };
    openDialog('Choose media', 'MEDIA LIBRARY', body, footer);
    $$('#dialogBody input[name="mediaChoice"]').forEach(radio => radio.addEventListener('change', () => {
      $$('.media-pick-row', $('#dialogBody')).forEach(row => row.classList.toggle('selected', row.querySelector('input').checked));
    }));
    $('#cancelMediaPicker').addEventListener('click', closeDialog);
    $('#confirmMediaPicker').addEventListener('click', () => {
      const selectedRadio = $('input[name="mediaChoice"]:checked', $('#dialogBody'));
      if (!selectedRadio) { notify('Select a media item, or choose “No media”.', 'error'); return; }
      const choice = selectedRadio.value || '';
      if (context.kind === 'composer') {
        state.attachedMediaId = choice;
        closeDialog();
        go('compose');
        syncAttachedMediaUI();
        updateComposer();
        const asset = choice ? findAsset(choice) : null;
        notify(asset ? `Attached “${asset.name}” to the message.` : 'Media attachment cleared.');
        return;
      } else if (context.kind === 'template') {
        const select = $('#templateMedia');
        if (select) select.value = choice;
      }
      closeDialog();
      notify(choice ? 'Selected media attached.' : 'Media attachment cleared.');
    });
    const addButton = $('#goAddMediaFromPicker');
    if (addButton) addButton.addEventListener('click', () => { closeDialog(); go('media'); });
  }
  $('#composerForm').addEventListener('submit', async event => {
    event.preventDefault();
    const delivery = getSelectedDelivery();
    const audience = getAudience();
    const title = $('#messageTitle').value.trim();
    const text = $('#messageBody').value.trim();
    const asset = selectedAsset();
    if (!audience.id) { notify('Choose a valid audience before continuing.', 'error'); return; }
    if (!text && !state.attachedMediaId) { notify('Write a message or attach media before continuing.', 'error'); $('#messageBody').focus(); return; }
    if (state.attachedMediaId && !asset) { notify('The selected media is unavailable. Re-upload it or choose another asset.', 'error'); return; }
    const scopeIssue = getAssetScopeIssue(asset, audience);
    if (scopeIssue) { notify(scopeIssue, 'error'); return; }
    let scheduledDate = '';
    let scheduledTime = '';
    let scheduledAt = '';
    if (delivery === 'schedule') {
      scheduledDate = $('#scheduleDate').value;
      scheduledTime = $('#scheduleTime').value;
      const date = istDateTime(scheduledDate, scheduledTime);
      if (!date || date.getTime() <= Date.now()) { notify('Choose a date and time in the future (Asia/Kolkata).', 'error'); $('#scheduleTime').focus(); return; }
      scheduledAt = date.toISOString();
    }
    if (delivery === 'now' && backendLiveSendingEnabled) {
      if (!backendConnected) { notify('The backend is not connected. No message was sent.', 'error'); return; }
      if (audience.mode !== 'member' && audience.mode !== 'group') {
        notify('Live sends are limited to one member or one group. Tier/phase bulk sends remain disabled.', 'error');
        return;
      }
      let liveMediaUrl = '';
      if (asset) {
        liveMediaUrl = String(asset.url || '').trim();
        if (!/^https:\/\//i.test(liveMediaUrl)) {
          notify('This file is stored on your local Mac. Periskope cannot fetch a local /uploads URL. Use a registered, publicly reachable HTTPS media URL for live media; text sends are available now.', 'error');
          return;
        }
      }
      const approvedRecipient = audience.label;
      const textPreview = text || '(no caption; media only)';
      const mediaPreview = asset ? `\nMedia: ${asset.name} (${asset.type})` : '';
      const confirmation = `REAL WHATSAPP SEND\n\nTo: ${approvedRecipient}${mediaPreview}\n\nMessage:\n${textPreview}\n\nThis sends immediately to one allowlisted recipient and cannot be undone. Continue?`;
      if (!window.confirm(confirmation)) return;
      const submitButton = $('#submitComposer');
      const submitHtml = submitButton.innerHTML;
      submitButton.disabled = true;
      submitButton.innerHTML = `${icon('send')}<span>Sending…</span>`;
      try {
        const mediaType = asset ? ({ PDF: 'document', Image: 'image', Video: 'video', Audio: 'audio', Document: 'document' }[asset.type] || String(asset.type).toLowerCase()) : null;
        const result = await apiRequest('/api/send', {
          method: 'POST',
          body: JSON.stringify({
            audience_mode: audience.mode,
            member_id: audience.mode === 'member' ? audience.id : null,
            group_id: audience.mode === 'group' ? audience.id : null,
            message: text,
            template_id: $('#templateSelect').value || null,
            media_asset_id: asset?.serverAssetId || null,
            media_url: liveMediaUrl || null,
            media_type: mediaType,
            filename: asset?.filename || asset?.name || null
          })
        });
        const statusLabel = ({ QUEUED: 'Queued at Periskope', SENT: 'Sent via Periskope', DELIVERED: 'Delivered via Periskope', READ: 'Read via Periskope' })[result.status] || 'Queued at Periskope';
        const sentItem = {
          id: uid('live'), title: title || (text ? text.replace(/\s+/g, ' ').slice(0, 58) : asset?.name || 'Live media message'),
          audienceMode: audience.mode, audienceId: audience.id, audienceLabel: audience.label, audienceDescription: audience.description,
          tier: audience.tier || audience.member?.tier || '', phase: audience.phase || audience.member?.phase || '',
          memberId: audience.member?.id || '', groupId: audience.group?.id || '', message: text,
          templateId: $('#templateSelect').value || '', mediaId: asset?.id || '', mediaName: asset?.name || '',
          mediaType: asset?.type || '', mediaUrl: liveMediaUrl, mediaStorageMode: asset?.storageMode || '',
          deliveryMode: 'now', status: statusLabel, scheduledAt: new Date().toISOString(),
          createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), demoOnly: false,
          periskopeMessageId: result.periskope_message_id || '', messageLogId: result.message_log_id || ''
        };
        state.outbox.unshift(sentItem);
        persist();
        resetComposer(); renderAll(); go('outbox');
        notify(`${result.message || 'Periskope accepted the request.'} Log ID: ${result.message_log_id || 'not returned'}.`);
      } catch (error) {
        notify(`Live-send request did not return success: ${error.message}. If the outcome is uncertain, check Periskope and message_logs before retrying.`, 'error');
      } finally {
        submitButton.disabled = false;
        submitButton.innerHTML = submitHtml;
        updateComposer();
      }
      return;
    }

    const statuses = { now: 'Queue preview', schedule: 'Scheduled preview', draft: 'Draft' };
    const item = {
      id: state.editingOutboxId || uid('msg'), title: title || (text ? text.replace(/\s+/g, ' ').slice(0, 58) : asset?.name || 'Media message'),
      audienceMode: audience.mode, audienceId: audience.id, audienceLabel: audience.label, audienceDescription: audience.description,
      tier: audience.tier || audience.member?.tier || '', phase: audience.phase || audience.member?.phase || '',
      memberId: audience.member?.id || '', groupId: audience.group?.id || '',
      message: text, templateId: $('#templateSelect').value || '', mediaId: asset?.id || '',
      mediaName: asset?.name || '', mediaType: asset?.type || '', mediaUrl: asset?.storageMode === 'hosted' ? asset.url : '',
      mediaStorageMode: asset?.storageMode || '', deliveryMode: delivery, status: statuses[delivery],
      scheduledDate, scheduledTime, scheduledAt: delivery === 'now' ? new Date().toISOString() : scheduledAt,
      createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
      demoOnly: true
    };
    if (state.editingOutboxId) {
      const index = state.outbox.findIndex(existing => existing.id === state.editingOutboxId);
      if (index >= 0) state.outbox[index] = { ...state.outbox[index], ...item, id: state.editingOutboxId };
      else state.outbox.unshift(item);
    } else state.outbox.unshift(item);
    persist();
    const message = delivery === 'draft' ? 'Draft saved to this browser.' : delivery === 'schedule' ? 'Schedule preview saved locally. No timer or WhatsApp delivery is active.' : 'Queue preview added locally. No WhatsApp message was sent.';
    resetComposer(); renderAll(); go('outbox'); notify(message);
  });
  function resetComposer() {
    $('#composerForm').reset();
    $('#messageTitle').value = ''; $('#messageBody').value = '';
    $('#templateSelect').value = '';
    state.attachedMediaId = ''; state.editingOutboxId = '';
    $('#audienceTier').value = 'Foundation'; $('#audiencePhase').value = 'all';
    $('#audienceMember').value = ''; $('#audienceGroup').value = '';
    setAudienceMode('tier');
    $('input[name="delivery"][value="now"]').checked = true;
    const suggestion = suggestedISTSchedule();
    $('#scheduleDate').min = todayIST();
    $('#scheduleDate').value = suggestion.date; $('#scheduleTime').value = suggestion.time;
    syncAttachedMediaUI(); updateComposer();
  }
  function editOutboxItem(id) {
    const item = state.outbox.find(message => message.id === id);
    if (!item || item.status !== 'Draft') return;
    state.editingOutboxId = id;
    $('#messageTitle').value = item.title || '';
    $('#messageBody').value = item.message || '';
    $('#templateSelect').value = item.templateId || '';
    state.attachedMediaId = item.mediaId || '';
    if (item.audienceMode === 'member') $('#audienceMember').value = item.memberId || item.audienceId || '';
    if (item.audienceMode === 'group') $('#audienceGroup').value = item.groupId || item.audienceId || '';
    if (item.audienceMode === 'tier') { $('#audienceTier').value = item.tier || item.audienceId || 'Foundation'; $('#audiencePhase').value = item.phase || 'all'; }
    setAudienceMode(item.audienceMode || 'tier');
    $('input[name="delivery"][value="draft"]').checked = true;
    updateComposer(); go('compose'); notify('Draft loaded. Save again to update this outbox item.');
  }
  function duplicateOutboxItem(id) {
    const item = state.outbox.find(message => message.id === id);
    if (!item) return;
    state.editingOutboxId = '';
    $('#messageTitle').value = `${item.title || 'Message'} (copy)`;
    $('#messageBody').value = item.message || '';
    $('#templateSelect').value = item.templateId || '';
    state.attachedMediaId = item.mediaId || '';
    if (item.audienceMode === 'member') $('#audienceMember').value = item.memberId || item.audienceId || '';
    if (item.audienceMode === 'group') $('#audienceGroup').value = item.groupId || item.audienceId || '';
    if (item.audienceMode === 'tier') { $('#audienceTier').value = item.tier || item.audienceId || 'Foundation'; $('#audiencePhase').value = item.phase || 'all'; }
    setAudienceMode(item.audienceMode || 'tier');
    $('input[name="delivery"][value="draft"]').checked = true;
    updateComposer(); go('compose'); notify('Copied to a new draft. Review target and content before continuing.');
  }
  function cancelOutboxItem(id) {
    const item = state.outbox.find(message => message.id === id);
    if (!item) return;
    if (item.status === 'Cancelled') return;
    const verb = item.status === 'Scheduled preview' ? 'Cancel this scheduled preview?' : 'Remove this local queue preview?';
    if (!window.confirm(verb)) return;
    if (item.status === 'Scheduled preview') item.status = 'Cancelled';
    else state.outbox = state.outbox.filter(message => message.id !== id);
    persist(); renderAll(); notify(item.status === 'Cancelled' ? 'Schedule preview cancelled locally.' : 'Local queue preview removed.');
  }
  function deleteOutboxItem(id) {
    const item = state.outbox.find(message => message.id === id);
    if (!item) return;
    if (!window.confirm(`Delete “${item.title}” from this browser's outbox?`)) return;
    state.outbox = state.outbox.filter(message => message.id !== id);
    persist(); renderAll(); notify('Outbox item removed from the local preview.');
  }

  // Outbox rendering and filters.
  $('#outboxSearch').addEventListener('input', renderOutbox);
  $('#outboxStatusFilter').addEventListener('change', renderOutbox);
  $('#clearOutboxFilters').addEventListener('click', () => { $('#outboxSearch').value = ''; $('#outboxStatusFilter').value = 'all'; renderOutbox(); });
  function statusClass(status) {
    return status === 'Scheduled preview' ? 'status-scheduled-preview' : (['Queue preview', 'Queued at Periskope', 'Sent via Periskope', 'Delivered via Periskope', 'Read via Periskope'].includes(status) ? 'status-queue-preview' : status === 'Cancelled' ? 'status-cancelled' : 'status-draft');
  }
  function statusIcon(status) {
    return status === 'Scheduled preview' ? 'clock' : (['Queue preview', 'Queued at Periskope', 'Sent via Periskope', 'Delivered via Periskope', 'Read via Periskope'].includes(status) ? 'send' : status === 'Cancelled' ? 'close' : 'file');
  }
  function deliveryDescription(item) {
    if (item.status === 'Scheduled preview') {
      const date = istDateTime(item.scheduledDate, item.scheduledTime) || new Date(item.scheduledAt);
      return `Scheduled preview · ${formatIST(date)}, ${formatClock(date)} IST`;
    }
    if (item.status === 'Queue preview') return `Send-now preview · created ${formatClock(item.createdAt)} IST`;
    if (['Queued at Periskope', 'Sent via Periskope', 'Delivered via Periskope', 'Read via Periskope'].includes(item.status)) return `${item.status} · message log ${item.messageLogId || 'ID not returned'}${item.periskopeMessageId ? ` · provider ID ${item.periskopeMessageId}` : ''}`;
    if (item.status === 'Cancelled') return 'Cancelled locally · no message was sent';
    return 'Draft · not submitted';
  }
  function renderOutbox() {
    const query = $('#outboxSearch').value.trim().toLowerCase();
    const filter = $('#outboxStatusFilter').value;
    const visible = state.outbox.filter(item => `${item.title} ${item.audienceLabel} ${item.message}`.toLowerCase().includes(query) && (filter === 'all' || item.status === filter));
    $('#outboxList').innerHTML = visible.map(item => {
      const mediaMissing = item.mediaId && !findAsset(item.mediaId);
      const media = item.mediaName || mediaNameFor(item.mediaId, 'Attachment');
      const actions = item.status === 'Draft'
        ? `<button class="button button-secondary button-small" type="button" data-action="outbox-edit" data-id="${esc(item.id)}">Edit draft</button><button class="button button-quiet button-small" type="button" data-action="outbox-delete" data-id="${esc(item.id)}">Delete</button>`
        : item.status === 'Scheduled preview'
          ? `<button class="button button-secondary button-small" type="button" data-action="outbox-duplicate" data-id="${esc(item.id)}">Duplicate</button><button class="button button-quiet button-small danger-link" type="button" data-action="outbox-cancel" data-id="${esc(item.id)}">Cancel</button>`
          : item.status === 'Cancelled'
            ? `<button class="button button-secondary button-small" type="button" data-action="outbox-duplicate" data-id="${esc(item.id)}">Duplicate</button><button class="button button-quiet button-small" type="button" data-action="outbox-delete" data-id="${esc(item.id)}">Remove</button>`
            : `<button class="button button-secondary button-small" type="button" data-action="outbox-duplicate" data-id="${esc(item.id)}">Duplicate</button><button class="button button-quiet button-small" type="button" data-action="outbox-cancel" data-id="${esc(item.id)}">Remove</button>`;
      return `<article class="outbox-card ${item.status === 'Cancelled' ? 'cancelled' : ''}">
        <span class="outbox-main-icon">${icon(statusIcon(item.status))}</span>
        <div class="outbox-main"><div class="outbox-title-row"><strong>${esc(item.title || 'Untitled message')}</strong><span class="status-chip ${statusClass(item.status)}">${esc(item.status)}</span></div>
          <div class="outbox-audience">To: <strong>${esc(item.audienceLabel || 'Audience missing')}</strong>${item.audienceDescription ? ` · ${esc(item.audienceDescription)}` : ''}</div>
          ${item.message ? `<p class="outbox-message-excerpt">${esc(item.message.slice(0, 260))}${item.message.length > 260 ? '…' : ''}</p>` : ''}
          <div class="outbox-meta-row"><span>${icon('clock', 'tiny')} ${esc(deliveryDescription(item))}</span>${item.mediaId || item.mediaName ? `<span class="meta-dot"></span><span>${icon('file', 'tiny')} ${esc(media)}${mediaMissing ? ' · re-upload before production' : ''}</span>` : ''}<span class="meta-dot"></span><span>${item.demoOnly === false ? 'Provider request logged in PostgreSQL' : 'Local preview only'}</span></div>
        </div><div class="outbox-actions">${actions}</div>
      </article>`;
    }).join('');
    $('#outboxEmpty').hidden = visible.length > 0;
    $('#outboxList').hidden = visible.length === 0;
    if (visible.length === 0 && state.outbox.length > 0) {
      $('#outboxEmpty').querySelector('h3').textContent = 'No matching messages';
      $('#outboxEmpty').querySelector('p').textContent = 'Try another search or clear the status filter.';
      $('#outboxEmpty').querySelector('button').textContent = 'Clear filters';
      $('#outboxEmpty').querySelector('button').onclick = () => { $('#outboxSearch').value = ''; $('#outboxStatusFilter').value = 'all'; renderOutbox(); };
    } else {
      $('#outboxEmpty').querySelector('h3').textContent = 'Nothing in your outbox';
      $('#outboxEmpty').querySelector('p').textContent = 'Draft a message, create a queue preview, or choose a future delivery time.';
      const button = $('#outboxEmpty').querySelector('button');
      button.textContent = 'Create a message'; button.onclick = () => go('compose');
    }
    $('#outboxAllCount').textContent = String(state.outbox.length);
    $('#outboxDraftCount').textContent = String(state.outbox.filter(item => item.status === 'Draft').length);
    $('#outboxScheduledCount').textContent = String(state.outbox.filter(item => item.status === 'Scheduled preview').length);
    $('#outboxQueueCount').textContent = String(state.outbox.filter(item => item.status === 'Queue preview').length);
    renderNavigationCounts();
  }

  // Overview and application-level counts.
  function renderNavigationCounts() {
    if ($('#navMediaCount')) $('#navMediaCount').textContent = String(state.assets.length);
    if ($('#navTemplateCount')) $('#navTemplateCount').textContent = String(state.templates.length);
    if ($('#navOutboxCount')) $('#navOutboxCount').textContent = String(state.outbox.filter(item => item.status !== 'Cancelled').length);
  }
  function renderOverview() {
    const now = new Date();
    $('#todayLabel').textContent = new Intl.DateTimeFormat('en-IN', { weekday: 'long', month: 'long', day: 'numeric', timeZone: 'Asia/Kolkata' }).format(now).toUpperCase();
    const hour = Number(new Intl.DateTimeFormat('en-GB', { hour: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }).format(now));
    const hello = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
    // The heading remains task-focused rather than using an account-specific name.
    $('#overviewTitle').innerHTML = `${hello}. Make every message count<span class="heading-period">.</span>`;
    $('#statAssets').textContent = String(state.assets.length);
    $('#statTemplates').textContent = String(state.templates.length);
    $('#statScheduled').textContent = String(state.outbox.filter(item => ['Draft', 'Scheduled preview', 'Queue preview'].includes(item.status)).length);
    const whatsappStat = $('#statWhatsapp');
    if (whatsappStat) whatsappStat.textContent = backendLiveSendingEnabled ? 'Live sends on' : (backendConnected ? 'Not enabled' : 'Not connected');
    const upcoming = state.outbox.filter(item => item.status === 'Scheduled preview').sort((a, b) => (a.scheduledAt || '').localeCompare(b.scheduledAt || '')).slice(0, 3);
    $('#overviewUpcoming').innerHTML = upcoming.map(item => {
      const date = istDateTime(item.scheduledDate, item.scheduledTime) || new Date(item.scheduledAt);
      return `<div class="upcoming-item"><div class="upcoming-time">${esc(formatClock(date))}</div><div class="upcoming-timeline"></div><div class="upcoming-main"><strong>${esc(item.title)}</strong><p>${esc(item.audienceLabel)} · ${item.mediaName ? esc(item.mediaName) : 'Text message'}</p><span class="status-chip status-scheduled-preview">Scheduled preview</span></div></div>`;
    }).join('');
    $('#overviewUpcomingEmpty').hidden = upcoming.length > 0;
    $('#overviewUpcoming').hidden = upcoming.length === 0;
    const recentAssets = state.assets.slice(0, 4);
    $('#overviewAssets').innerHTML = recentAssets.map(asset => `<button type="button" class="asset-mini" data-action="asset-edit" data-id="${esc(asset.id)}"><span class="asset-mini-icon">${icon(assetIconName(asset.type))}</span><span class="asset-mini-copy"><strong>${esc(asset.name)}</strong><small>${esc(asset.type)} · ${esc(scopeLabel(asset))}</small></span></button>`).join('');
    $('#overviewAssetsEmpty').hidden = recentAssets.length > 0;
    $('#overviewAssets').hidden = recentAssets.length === 0;
    renderNavigationCounts();
  }
  function renderAll() {
    renderMedia(); renderTemplates(); renderOutbox(); renderOverview(); syncAttachedMediaUI(); updateComposer();
  }

  // Initialize UI state; recipients arrive from the database bootstrap.
  populateAudienceOptions();
  syncAttachedMediaUI();
  updateComposer();
  renderAll();
  void initializeBackend();

  // Drafts and future schedules remain local previews; only an explicitly enabled, confirmed now-send reaches Periskope.
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      if (state.page === 'compose') { event.preventDefault(); $('#composerForm').requestSubmit(); }
    }
  });
})();
