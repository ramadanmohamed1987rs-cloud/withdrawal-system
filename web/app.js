'use strict';

const $ = (id) => document.getElementById(id);
const API = location.pathname.indexOf('/withdrawal') === 0 ? '/withdrawal/api' : '/api';

let token = localStorage.getItem('towing_token') || '';
let user = localStorage.getItem('towing_user') || '';
let currentRecords = [];

const STATUS = {
  towed:     { label: 'مسحوبة',      cls: 'st-towed' },
  not_towed: { label: 'غير مسحوبة',  cls: 'st-not_towed' },
  rejected:  { label: 'مرفوضة',      cls: 'st-rejected' },
  on_way:    { label: 'بالطريق',     cls: 'st-on_way' },
  could_not: { label: 'تعذر السحب',  cls: 'st-could_not' },
  deferred:  { label: 'تأجيل السحب', cls: 'st-deferred' },
};

const MSG = {
  INVALID_CREDENTIALS: 'اسم المستخدم أو كلمة المرور غير صحيحة',
  UNAUTHORIZED: 'الرجاء تسجيل الدخول',
  VEHICLE_REQUIRED: 'الرجاء إدخال اسم المركبة',
  STATUS_INVALID: 'حالة المركبة غير صحيحة',
  DATE_INVALID: 'الرجاء إدخال تاريخ صحيح',
  NOT_FOUND: 'العنصر غير موجود',
  PASSWORD_WRONG: 'كلمة المرور الحالية غير صحيحة',
  PASSWORD_SHORT: 'كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل',
  NAME_REQUIRED: 'الرجاء إدخال اسم المستخدم',
  NAME_TOO_LONG: 'اسم المستخدم طويل جداً (الحد الأقصى 30 حرف)',
  USER_EXISTS: 'هذا اسم المستخدم موجود بالفعل',
  BAD_REQUEST: 'طلب غير صحيح',
  IMPORT_EMPTY: 'الملف لا يحتوي على بيانات صالحة للاستيراد',
  IMPORT_HEADERS: 'صيغة الملف غير مدعومة - يجب أن يحتوي على عمودي التاريخ واسم المركبة على الأقل',
  NETWORK: 'لا يمكن الاتصال بالخادم',
  ERROR: 'حدث خطأ غير متوقع',
};
function msg(code) { return MSG[code] || MSG.ERROR; }

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function fmtDate(d) {
  if (!d) return '';
  const p = String(d).split('-');
  return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : d;
}

function today() { return new Date().toISOString().slice(0, 10); }

function statusBadge(s) {
  const info = STATUS[s] || STATUS.not_towed;
  return '<span class="badge ' + info.cls + '">' + info.label + '</span>';
}

function attachCell(r) {
  if (r.attachment_name) {
    return '<button class="btn btn-mini" data-action="dl-attach" data-id="' + esc(r.id) + '">تحميل الملف</button> ' +
      '<button class="btn btn-mini btn-danger" data-action="del-attach" data-id="' + esc(r.id) + '">حذف</button>';
  }
  return '<button class="btn btn-mini" data-action="add-attach" data-id="' + esc(r.id) + '">إضافة ملف</button>';
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(',')[1]);
    fr.onerror = reject;
    fr.readAsDataURL(file);
  });
}

let toastTimer;
function toast(text, kind) {
  const t = $('toast');
  t.textContent = text;
  t.className = 'toast' + (kind === 'error' ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), 3000);
}

// ---------- API ----------
async function api(path, method, body) {
  const headers = {};
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const opts = { method: method || 'GET', headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try { res = await fetch(API + path, opts); }
  catch (e) { throw new Error('NETWORK'); }
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (res.status === 401) {
    if (path !== '/login') {
      logout();
      throw new Error('UNAUTHORIZED');
    }
  }
  if (!res.ok) throw new Error((data && data.error) || 'ERROR');
  return data;
}

// ---------- Auth ----------
function showLogin() {
  $('app-view').classList.add('hidden');
  $('login-view').classList.remove('hidden');
  $('loginPass').focus();
}
function showApp() {
  $('login-view').classList.add('hidden');
  $('app-view').classList.remove('hidden');
  $('nav-username').textContent = user;
  showView('dashboard');
}
function logout() {
  token = '';
  user = '';
  localStorage.removeItem('towing_token');
  localStorage.removeItem('towing_user');
  showLogin();
}

async function doLogin(e) {
  e.preventDefault();
  const username = $('loginUser').value.trim();
  const password = $('loginPass').value;
  const errBox = $('login-error');
  errBox.classList.add('hidden');
  if (!username || !password) { errBox.textContent = 'الرجاء إدخال اسم المستخدم وكلمة المرور'; errBox.classList.remove('hidden'); return; }
  try {
    const d = await api('/login', 'POST', { username, password });
    token = d.token;
    user = d.username;
    localStorage.setItem('towing_token', token);
    localStorage.setItem('towing_user', user);
    $('loginPass').value = '';
    showApp();
  } catch (err) {
    errBox.textContent = msg(err.message);
    errBox.classList.remove('hidden');
  }
}

// ---------- Navigation ----------
function showView(v) {
  document.querySelectorAll('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
  document.querySelectorAll('.view').forEach((s) => s.classList.toggle('hidden', s.id !== 'view-' + v));
  if (v === 'dashboard') loadDashboard();
  if (v === 'records') loadRecordsView();
}

// ---------- Table builders ----------
function recRow(r) {
  const tr = document.createElement('tr');
  tr.innerHTML =
    '<td class="td-check"><input type="checkbox" class="rec-check" data-id="' + esc(r.id) + '"></td>' +
    '<td class="col-date">' + esc(fmtDate(r.date)) + '</td>' +
    '<td class="col-vehicle">' + esc(r.vehicle) + '</td>' +
    '<td class="col-actions actions">' +
      '<button class="btn btn-mini" data-action="edit-rec" data-id="' + esc(r.id) + '">تعديل</button> ' +
      '<button class="btn btn-mini btn-danger" data-action="del-rec" data-id="' + esc(r.id) + '">حذف</button>' +
    '</td>' +
    '<td class="col-plate">' + esc(r.plate) + '</td>' +
    '<td class="col-claim">' + esc(r.claim) + '</td>' +
    '<td class="col-carrier">' + esc(r.carrier) + '</td>' +
    '<td class="col-area">' + esc(r.towing_area) + '</td>' +
    '<td class="col-status">' + statusBadge(r.status) + '</td>' +
    '<td class="col-note">' + esc(r.note) + '</td>' +
    '<td class="col-file actions">' + attachCell(r) + '</td>';
  return tr;
}

function emptyRow(tdCount, text) {
  const tr = document.createElement('tr');
  const td = document.createElement('td');
  td.colSpan = tdCount;
  td.className = 'empty';
  td.textContent = text;
  tr.appendChild(td);
  return tr;
}

// ---------- Dashboard ----------
async function loadDashboard() {
  try {
    const d = await api('/stats');
    $('d-total').textContent = d.total;
    $('d-towed').textContent = d.counts.towed;
    $('d-not_towed').textContent = d.counts.not_towed;
    $('d-rejected').textContent = d.counts.rejected;
    $('d-on_way').textContent = d.counts.on_way;
    $('d-could_not').textContent = d.counts.could_not;
    $('d-deferred').textContent = d.counts.deferred;
    const tbody = $('d-recent');
    tbody.innerHTML = '';
    if (!d.recent || !d.recent.length) {
      tbody.appendChild(emptyRow(8, 'لا توجد عمليات بعد'));
    } else {
      d.recent.forEach((r) => {
        const tr = document.createElement('tr');
        tr.innerHTML =
          '<td>' + esc(fmtDate(r.date)) + '</td>' +
          '<td>' + esc(r.vehicle) + '</td>' +
          '<td>' + esc(r.plate) + '</td>' +
          '<td>' + esc(r.claim) + '</td>' +
          '<td>' + esc(r.carrier) + '</td>' +
          '<td>' + esc(r.towing_area) + '</td>' +
          '<td>' + statusBadge(r.status) + '</td>' +
          '<td>' + esc(r.note) + '</td>';
        tbody.appendChild(tr);
      });
    }
  } catch (e) { toast(msg(e.message), 'error'); }
}

// ---------- Records ----------
async function loadRecordsView() {
  try {
    const params = new URLSearchParams();
    const from = $('rf-from').value, to = $('rf-to').value, status = $('rf-status').value, q = $('rf-q').value.trim();
    if (from) params.set('from', from);
    if (to) params.set('to', to);
    if (status) params.set('status', status);
    if (q) params.set('q', q);
    const qs = params.toString();
    const d = await api('/records' + (qs ? '?' + qs : ''));
    currentRecords = d.items || [];
    renderRecords();
  } catch (e) { toast(msg(e.message), 'error'); }
}

function renderRecords() {
  const tbody = $('rec-list');
  tbody.innerHTML = '';
  $('rf-count').textContent = currentRecords.length;
  $('rf-selected').textContent = 0;
  $('sel-count-box').classList.remove('on');
  $('check-all').checked = false;
  if (!currentRecords.length) {
    tbody.appendChild(emptyRow(11, 'لا توجد عمليات'));
    syncTopScroll();
    return;
  }
  currentRecords.forEach((r) => tbody.appendChild(recRow(r)));
  applyCols();
  syncTopScroll();
}

function updateRowSelection(cb) {
  const tr = cb.closest('tr');
  if (tr) tr.classList.toggle('selected', cb.checked);
}

function updateSelectedCount() {
  const n = document.querySelectorAll('.rec-check:checked').length;
  $('rf-selected').textContent = n;
  $('sel-count-box').classList.toggle('on', n > 0);
}

// ---------- Column visibility ----------
const COLUMNS = [
  { key: 'date',    label: 'التاريخ' },
  { key: 'vehicle', label: 'اسم المركبة' },
  { key: 'actions', label: 'إجراءات (تعديل / حذف)' },
  { key: 'plate',   label: 'رقم اللوحة' },
  { key: 'claim',   label: 'رقم المطالبة' },
  { key: 'carrier', label: 'اسم الناقل' },
  { key: 'area',    label: 'منطقة السحب' },
  { key: 'status',  label: 'الحالة' },
  { key: 'note',    label: 'ملاحظات' },
  { key: 'file',    label: 'الملف' },
];

let colPrefs = {};
try { colPrefs = JSON.parse(localStorage.getItem('towing_cols') || '{}') || {}; } catch (e) { colPrefs = {}; }

function buildColsPanel() {
  const panel = $('cols-panel');
  panel.innerHTML = '';
  const head = document.createElement('div');
  head.className = 'cols-panel-head';
  head.textContent = 'إظهار / إخفاء الأعمدة';
  panel.appendChild(head);
  COLUMNS.forEach((c) => {
    const label = document.createElement('label');
    const inp = document.createElement('input');
    inp.type = 'checkbox';
    inp.dataset.col = c.key;
    inp.checked = colPrefs[c.key] !== false;
    label.appendChild(inp);
    label.appendChild(document.createTextNode(' ' + c.label));
    panel.appendChild(label);
  });
}

function applyCols() {
  const table = document.querySelector('#rec-table-wrap table');
  if (!table) return;
  COLUMNS.forEach((c) => {
    table.classList.toggle('hide-' + c.key, colPrefs[c.key] === false);
  });
  document.querySelectorAll('#cols-panel input[data-col]').forEach((inp) => {
    inp.checked = colPrefs[inp.dataset.col] !== false;
  });
  syncTopScroll();
}

function bindColsPanel() {
  $('btn-cols').addEventListener('click', (e) => {
    e.stopPropagation();
    $('cols-panel').classList.toggle('hidden');
  });
  $('cols-panel').addEventListener('change', (e) => {
    const inp = e.target;
    if (!inp.dataset.col) return;
    if (inp.checked) delete colPrefs[inp.dataset.col];
    else colPrefs[inp.dataset.col] = false;
    try { localStorage.setItem('towing_cols', JSON.stringify(colPrefs)); } catch (e) {}
    applyCols();
  });
  document.addEventListener('click', (e) => {
    const panel = $('cols-panel');
    if (!panel.classList.contains('hidden') && !panel.contains(e.target) && !$('btn-cols').contains(e.target)) {
      panel.classList.add('hidden');
    }
  });
  buildColsPanel();
}

function syncTopScroll() {
  const wrap = $('rec-table-wrap');
  const top = $('rec-scroll-top');
  if (!wrap || !top) return;
  const hasOverflow = wrap.scrollWidth > wrap.clientWidth;
  top.style.display = hasOverflow ? 'block' : 'none';
  if (hasOverflow) $('rec-scroll-spacer').style.width = wrap.scrollWidth + 'px';
}

function bindTopScroll() {
  const wrap = $('rec-table-wrap');
  const top = $('rec-scroll-top');
  top.addEventListener('scroll', () => { wrap.scrollLeft = top.scrollLeft; });
  wrap.addEventListener('scroll', () => { top.scrollLeft = wrap.scrollLeft; });
  window.addEventListener('resize', syncTopScroll);
}

function readForm(prefix) {
  return {
    date: $(prefix + 'date').value,
    vehicle: $(prefix + 'vehicle').value.trim(),
    plate: $(prefix + 'plate').value.trim(),
    claim: $(prefix + 'claim').value.trim(),
    carrier: $(prefix + 'carrier').value.trim(),
    towing_area: $(prefix + 'area').value.trim(),
    status: $(prefix + 'status').value,
    note: $(prefix + 'note').value.trim(),
  };
}

async function addRecord(e) {
  e.preventDefault();
  const payload = readForm('rec-');
  if (!payload.date) { toast('الرجاء إدخال التاريخ', 'error'); return; }
  if (!payload.vehicle) { toast('الرجاء إدخال اسم المركبة', 'error'); return; }
  const fileInput = $('rec-file');
  const file = fileInput.files[0];
  if (file) {
    if (file.size > 20 * 1024 * 1024) { toast('حجم الملف يجب أن يكون أقل من 20 ميجابايت', 'error'); return; }
    payload.attachmentName = file.name;
    payload.attachmentBase64 = await fileToBase64(file);
  }
  try {
    await api('/records', 'POST', payload);
    toast('تمت إضافة العملية');
    $('rec-vehicle').value = '';
    $('rec-plate').value = '';
    $('rec-claim').value = '';
    $('rec-carrier').value = '';
    $('rec-area').value = '';
    $('rec-status').value = 'not_towed';
    $('rec-note').value = '';
    fileInput.value = '';
    loadRecordsView();
  } catch (err) { toast(msg(err.message), 'error'); }
}

function openRecModal(id) {
  const r = currentRecords.find((x) => x.id === id);
  if (!r) return;
  $('recm-id').value = r.id;
  $('recm-date').value = r.date;
  $('recm-vehicle').value = r.vehicle;
  $('recm-plate').value = r.plate;
  $('recm-claim').value = r.claim;
  $('recm-carrier').value = r.carrier;
  $('recm-area').value = r.towing_area || '';
  $('recm-status').value = r.status;
  $('recm-note').value = r.note || '';
  openModal('rec-modal');
}

async function saveRec(e) {
  e.preventDefault();
  const id = $('recm-id').value;
  const payload = readForm('recm-');
  if (!payload.date) { toast('الرجاء إدخال التاريخ', 'error'); return; }
  if (!payload.vehicle) { toast('الرجاء إدخال اسم المركبة', 'error'); return; }
  try {
    await api('/records/' + id, 'PUT', payload);
    toast('تم تعديل العملية');
    closeModal('rec-modal');
    loadRecordsView();
  } catch (err) { toast(msg(err.message), 'error'); }
}

async function deleteRecord(id) {
  if (!confirm('هل تريد حذف هذه العملية؟')) return;
  try {
    await api('/records/' + id, 'DELETE');
    toast('تم حذف العملية');
    loadRecordsView();
  } catch (err) { toast(msg(err.message), 'error'); }
}

async function deleteSelected() {
  const checks = Array.from(document.querySelectorAll('.rec-check:checked'));
  if (!checks.length) { toast('الرجاء تحديد المركبات المطلوب حذفها أولاً', 'error'); return; }
  if (!confirm('هل تريد حذف ' + checks.length + ' مركبة محددة؟')) return;
  let ok = 0;
  try {
    for (const c of checks) {
      await api('/records/' + c.dataset.id, 'DELETE');
      ok++;
    }
    toast('تم حذف ' + ok + ' مركبة');
    $('check-all').checked = false;
    loadRecordsView();
  } catch (err) { toast(msg(err.message), 'error'); }
}

// ---------- Attachments ----------
async function uploadAttachment(id, file) {
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) { toast('حجم الملف يجب أن يكون أقل من 20 ميجابايت', 'error'); return; }
  try {
    const attachmentBase64 = await fileToBase64(file);
    await api('/records/' + id + '/attachment', 'POST', { attachmentName: file.name, attachmentBase64 });
    toast('تم إرفاق الملف');
    loadRecordsView();
  } catch (err) { toast(msg(err.message), 'error'); }
}

async function deleteAttachment(id) {
  if (!confirm('هل تريد حذف الملف المرفق؟')) return;
  try {
    await api('/records/' + id + '/attachment', 'DELETE');
    toast('تم حذف الملف');
    loadRecordsView();
  } catch (err) { toast(msg(err.message), 'error'); }
}

async function downloadAttachment(id) {
  try {
    const res = await fetch(API + '/attachment/' + encodeURIComponent(id), {
      headers: { Authorization: 'Bearer ' + token },
    });
    if (res.status === 401) { logout(); throw new Error('UNAUTHORIZED'); }
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch (e) {}
      throw new Error((data && data.error) || 'ERROR');
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    let name = 'ملف_' + id;
    const cd = res.headers.get('Content-Disposition');
    if (cd) {
      const m = cd.match(/filename="?([^";]+)"?/);
      if (m) name = m[1];
    }
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
  } catch (e) { toast(msg(e.message), 'error'); }
}

// ---------- Export / Import Excel ----------
function recFilterQuery() {
  const params = new URLSearchParams();
  const from = $('rf-from').value, to = $('rf-to').value, status = $('rf-status').value, q = $('rf-q').value.trim();
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  if (status) params.set('status', status);
  if (q) params.set('q', q);
  return params;
}

async function exportExcel(ids) {
  const params = recFilterQuery();
  if (ids && ids.length) params.set('ids', ids.join(','));
  const q = params.toString();
  const fname = (ids && ids.length) ? 'سحب_المحدد_' + today() + '.xlsx' : 'سحب_المركبات_' + today() + '.xlsx';
  try {
    const res = await fetch(API + '/export' + (q ? '?' + q : ''), {
      headers: { Authorization: 'Bearer ' + token },
    });
    if (res.status === 401) { logout(); throw new Error('UNAUTHORIZED'); }
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch (e) {}
      throw new Error((data && data.error) || 'ERROR');
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
    toast('تم تصدير الملف');
  } catch (e) { toast(msg(e.message), 'error'); }
}

async function exportSelected() {
  const checks = Array.from(document.querySelectorAll('.rec-check:checked'));
  if (!checks.length) { toast('الرجاء تحديد المركبات المطلوب تصديرها أولاً', 'error'); return; }
  await exportExcel(checks.map((c) => c.dataset.id));
}

async function importExcelFile(file) {
  try {
    const buf = await file.arrayBuffer();
    const res = await fetch(API + '/import', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + token,
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      },
      body: buf,
    });
    if (res.status === 401) { logout(); throw new Error('UNAUTHORIZED'); }
    let data = null;
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) throw new Error((data && data.error) || 'ERROR');
    let text = 'تم استيراد ' + data.imported + ' عملية جديدة';
    if (data.duplicates > 0) text += '، وتخطي ' + data.duplicates + ' لوحة مكررة';
    if (data.skipped > 0) text += '، وتخطي ' + data.skipped + ' صف غير صالح';
    toast(text);
    loadRecordsView();
  } catch (e) { toast(msg(e.message), 'error'); }
}

// ---------- Settings ----------
async function changeUsername(e) {
  e.preventDefault();
  const newName = $('u-name').value.trim();
  const pass = $('u-pass').value;
  if (!newName) { toast('الرجاء إدخال اسم المستخدم الجديد', 'error'); return; }
  if (!pass) { toast('الرجاء إدخال كلمة المرور الحالية', 'error'); return; }
  try {
    const d = await api('/change-username', 'POST', { newUsername: newName, password: pass });
    user = d.username;
    localStorage.setItem('towing_user', user);
    $('nav-username').textContent = user;
    $('u-name').value = '';
    $('u-pass').value = '';
    toast('تم تغيير اسم المستخدم بنجاح');
  } catch (err) { toast(msg(err.message), 'error'); }
}

async function changePassword(e) {
  e.preventDefault();
  const cur = $('p-cur').value;
  const n1 = $('p-new').value;
  const n2 = $('p-confirm').value;
  if (!cur || !n1) { toast('الرجاء إدخال كلمة المرور الحالية والجديدة', 'error'); return; }
  if (n1.length < 6) { toast(msg('PASSWORD_SHORT'), 'error'); return; }
  if (n1 !== n2) { toast('كلمتا المرور غير متطابقتين', 'error'); return; }
  try {
    await api('/change-password', 'POST', { currentPassword: cur, newPassword: n1 });
    toast('تم تغيير كلمة المرور بنجاح');
    $('p-cur').value = $('p-new').value = $('p-confirm').value = '';
  } catch (err) { toast(msg(err.message), 'error'); }
}

// ---------- Modals ----------
function openModal(id) { $(id).classList.remove('hidden'); }
function closeModal(id) { $(id).classList.add('hidden'); }

// ---------- Events ----------
function bindEvents() {
  $('login-form').addEventListener('submit', doLogin);
  $('logout-btn').addEventListener('click', () => {
    api('/logout', 'POST').catch(() => {});
    logout();
  });

  document.querySelectorAll('.nav-btn').forEach((b) => {
    b.addEventListener('click', () => showView(b.dataset.view));
  });

  $('rec-form').addEventListener('submit', addRecord);
  $('recm-form').addEventListener('submit', saveRec);
  $('user-form').addEventListener('submit', changeUsername);
  $('pass-form').addEventListener('submit', changePassword);
  $('rec-filter').addEventListener('submit', (e) => { e.preventDefault(); loadRecordsView(); });
  $('rf-clear').addEventListener('click', () => {
    $('rf-from').value = $('rf-to').value = '';
    $('rf-status').value = '';
    $('rf-q').value = '';
    loadRecordsView();
  });
  $('btn-export').addEventListener('click', exportExcel);
  $('btn-import').addEventListener('click', () => $('import-file').click());
  $('import-file').addEventListener('change', (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    if (!confirm('هل تريد استيراد العمليات من الملف "' + file.name + '"?')) return;
    importExcelFile(file);
  });
  $('check-all').addEventListener('change', (e) => {
    document.querySelectorAll('.rec-check').forEach((c) => {
      c.checked = e.target.checked;
      updateRowSelection(c);
    });
    updateSelectedCount();
  });
  $('btn-export-selected').addEventListener('click', exportSelected);
  $('btn-del-selected').addEventListener('click', deleteSelected);
  document.addEventListener('change', (e) => {
    if (e.target.classList && e.target.classList.contains('rec-check')) {
      updateRowSelection(e.target);
      updateSelectedCount();
    }
  });
  bindTopScroll();
  bindColsPanel();

  document.addEventListener('click', (e) => {
    const act = e.target.closest('[data-action]');
    if (!act) return;
    const action = act.dataset.action;
    const id = act.dataset.id;
    const target = act.dataset.target;
    if (action === 'close-modal') closeModal(target);
    if (action === 'edit-rec') openRecModal(id);
    if (action === 'del-rec') deleteRecord(id);
    if (action === 'dl-attach') downloadAttachment(id);
    if (action === 'del-attach') deleteAttachment(id);
    if (action === 'add-attach') {
      const input = document.createElement('input');
      input.type = 'file';
      input.onchange = () => uploadAttachment(id, input.files[0]);
      input.click();
    }
  });

  document.querySelectorAll('.modal').forEach((m) => {
    m.addEventListener('click', (e) => { if (e.target === m) closeModal(m.id); });
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') document.querySelectorAll('.modal').forEach((m) => m.classList.add('hidden'));
  });

  $('rec-date').value = today();
}

document.addEventListener('DOMContentLoaded', () => {
  bindEvents();
  if (token && user) {
    showApp();
  } else {
    showLogin();
  }
});
