#!/usr/bin/env python3
"""
نظام السحب - سجل سحب المركبات التالفة
Cloud version - Flask app for gunicorn
"""
import os
import json
import uuid
import hashlib
import re
import io
import zipfile
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, send_file

app = Flask(__name__, static_folder='web', static_url_path='')

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, 'data')
ATTACHMENTS_DIR = os.path.join(DATA_DIR, 'attachments')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
RECORDS_FILE = os.path.join(DATA_DIR, 'records.json')
WEB_DIR = os.path.join(ROOT, 'web')

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
SESSION_LIFETIME_HOURS = 12

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

sessions = {}
static_cache = {}

STATUS_AR = {
    'towed': 'مسحوبة', 'not_towed': 'غير مسحوبة', 'rejected': 'مرفوضة',
    'on_way': 'بالطريق', 'could_not': 'تعذر السحب', 'deferred': 'تأجيل السحب'
}
VALID_STATUS = ['towed', 'not_towed', 'rejected', 'on_way', 'could_not', 'deferred']


def read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            c = f.read().strip()
            if c:
                return json.loads(c)
    except:
        pass
    return None


def write_json(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=4)


def get_users():
    data = read_json(USERS_FILE)
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def save_users(u):
    write_json(USERS_FILE, u)


def get_records():
    data = read_json(RECORDS_FILE)
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def save_records(r):
    write_json(RECORDS_FILE, r)


def new_id():
    return uuid.uuid4().hex


def hash_password(password, salt):
    return hashlib.sha256((salt + ':' + password).encode('utf-8')).hexdigest()


def ensure_data():
    if not os.path.exists(USERS_FILE):
        salt = new_id()[:8]
        users = [{'username': 'admin', 'salt': salt, 'passHash': hash_password('admin123', salt), 'created': datetime.now().isoformat()}]
        save_users(users)
    if not os.path.exists(RECORDS_FILE):
        save_records([])


def get_session(token):
    if not token or token not in sessions:
        return None
    sess = sessions[token]
    if sess['expires'] > datetime.now():
        return sess
    del sessions[token]
    return None


def create_session(username):
    token = new_id()
    sessions[token] = {'username': username, 'expires': datetime.now() + timedelta(hours=SESSION_LIFETIME_HOURS)}
    return token


def normalize_date(s):
    if not s:
        return None
    s = s.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        try:
            datetime.strptime(s, '%Y-%m-%d')
            return s
        except:
            return None
    m = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$', s)
    if m:
        return f'{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}'
    try:
        num = float(s)
        if 20000 < num < 60000:
            from datetime import date, timedelta as td
            dt = date(1899, 12, 30) + td(days=num)
            if 1900 < dt.year < 2100:
                return dt.strftime('%Y-%m-%d')
    except:
        pass
    return None


def normalize_status(v):
    if not v:
        return None
    s = v.strip().lower()
    if not s:
        return None
    mapping = [
        (['غير مسحوب', 'not towed', 'not_towed'], 'not_towed'),
        (['مسحوب', 'تسحب', 'towed'], 'towed'),
        (['مرفوض', 'reject'], 'rejected'),
        (['بالطريق', 'على الطريق', 'في الطريق', 'on way', 'on_way'], 'on_way'),
        (['تعذر', 'تعذرت', 'could not', 'could_not'], 'could_not'),
        (['تاجيل', 'تأجيل', 'مؤجل', 'ماجل', 'تاخير', 'تأخير', 'deferr'], 'deferred'),
    ]
    for keywords, status in mapping:
        for kw in keywords:
            if s.startswith(kw) or kw.startswith(s):
                return status
    return None


def attachment_path(rec):
    if not rec or not rec.get('attachment_name'):
        return None
    return os.path.join(ATTACHMENTS_DIR, rec['id'] + '_' + rec['attachment_name'])


def save_attachment(rec, name, base64_data):
    if not rec or not name or not base64_data:
        return False
    try:
        data = base64.b64decode(base64_data)
    except:
        return False
    if len(data) == 0 or len(data) > MAX_ATTACHMENT_BYTES:
        return False
    old = attachment_path(rec)
    if old and os.path.exists(old):
        os.remove(old)
    safe = re.sub(r'[^\w.\-]', '_', os.path.basename(name))
    if not safe:
        safe = 'file.bin'
    rec['attachment_name'] = safe
    path = os.path.join(ATTACHMENTS_DIR, rec['id'] + '_' + safe)
    with open(path, 'wb') as f:
        f.write(data)
    return True


def xml_escape(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def new_excel_bytes(headers, rows):
    col_count = len(headers)
    cols = []
    for i in range(col_count):
        if i < 26:
            cols.append(chr(65 + i))
        else:
            cols.append(chr(64 + i // 26) + chr(65 + i % 26))

    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    lines.append(f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:{cols[col_count - 1]}{len(rows) + 1}"/><sheetData>')
    lines.append('<row r="1">')
    for i, h in enumerate(headers):
        lines.append(f'<c r="{cols[i]}1" t="inlineStr" s="1"><is><t>{xml_escape(h)}</t></is></c>')
    lines.append('</row>')
    for ri, row in enumerate(rows, 2):
        lines.append(f'<row r="{ri}">')
        for i in range(col_count):
            val = row[i] if i < len(row) else ''
            lines.append(f'<c r="{cols[i]}{ri}" t="inlineStr"><is><t>{xml_escape(str(val))}</t></is></c>')
        lines.append('</row>')
    lines.append('</sheetData></worksheet>')
    sheet_xml = ''.join(lines)

    ct = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'
    rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    wb = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    wb_rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="center"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', ct)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('xl/workbook.xml', wb)
        zf.writestr('xl/_rels/workbook.xml.rels', wb_rels)
        zf.writestr('xl/styles.xml', styles)
        zf.writestr('xl/worksheets/sheet1.xml', sheet_xml)
    return buf.getvalue()


def parse_excel_rows(data):
    result = {'headers': [], 'rows': []}
    try:
        buf = io.BytesIO(data)
        with zipfile.ZipFile(buf, 'r') as zf:
            shared = []
            try:
                ss_xml = zf.read('xl/sharedStrings.xml').decode('utf-8')
                ss_root = ET.fromstring(ss_xml)
                ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                for si in ss_root.findall('.//m:si', ns):
                    t = si.find('m:t', ns)
                    if t is not None:
                        shared.append(t.text or '')
                    else:
                        parts = [rt.text or '' for rt in si.findall('.//m:r/m:t', ns)]
                        shared.append(''.join(parts))
            except:
                pass
            sheet_xml = zf.read('xl/worksheets/sheet1.xml').decode('utf-8')
            root = ET.fromstring(sheet_xml)
            ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            row_num = 0
            for row_el in root.findall('.//m:sheetData/m:row', ns):
                row_num += 1
                cells = {}
                max_col = -1
                for c in row_el.findall('m:c', ns):
                    ref = c.get('r', '')
                    col_str = ''.join(ch for ch in ref if ch.isalpha())
                    col_idx = 0
                    for ch in col_str:
                        col_idx = col_idx * 26 + (ord(ch) - 64)
                    col_idx -= 1
                    if col_idx > 40:
                        continue
                    t = c.get('t', '')
                    v = ''
                    if t == 's':
                        vn = c.find('m:v', ns)
                        if vn is not None:
                            try:
                                idx = int(vn.text)
                                if 0 <= idx < len(shared):
                                    v = shared[idx]
                            except:
                                pass
                    elif t == 'inlineStr':
                        is_el = c.find('m:is', ns)
                        if is_el is not None:
                            v = is_el.text or ''
                    else:
                        vn = c.find('m:v', ns)
                        if vn is not None:
                            v = vn.text or ''
                    cells[col_idx] = v
                    if col_idx > max_col:
                        max_col = col_idx
                if max_col < 0:
                    continue
                cell_arr = [cells.get(i, '') for i in range(max_col + 1)]
                if row_num == 1:
                    result['headers'] = cell_arr
                else:
                    result['rows'].append(cell_arr)
    except Exception as e:
        print(f'Excel parse error: {e}')
    return result


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'ok': False, 'error': 'UNAUTHORIZED'}), 401
        sess = get_session(auth[7:].strip())
        if not sess:
            return jsonify({'ok': False, 'error': 'UNAUTHORIZED'}), 401
        request.auth_user = sess
        return f(*args, **kwargs)
    return decorated


# ============ API Routes ============

@app.route('/api/login', methods=['POST'])
def api_login():
    body = request.get_json(silent=True)
    if not body or not body.get('username'):
        return jsonify({'ok': False, 'error': 'BAD_REQUEST'}), 400
    users = get_users()
    user = None
    for u in users:
        if u.get('username') == body.get('username'):
            user = u
            break
    if user and hash_password(str(body.get('password', '')), user['salt']) == user['passHash']:
        token = create_session(user['username'])
        return jsonify({'ok': True, 'token': token, 'username': user['username']})
    return jsonify({'ok': False, 'error': 'INVALID_CREDENTIALS'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    return jsonify({'ok': True})


@app.route('/api/me', methods=['GET'])
@require_auth
def api_me():
    return jsonify({'ok': True, 'username': request.auth_user['username']})


@app.route('/api/records', methods=['GET'])
@require_auth
def api_list_records():
    records = get_records()
    frm = request.args.get('from')
    to = request.args.get('to')
    status = request.args.get('status')
    q = request.args.get('q')
    result = []
    for r in records:
        if frm and (r.get('date') or '') < frm:
            continue
        if to and (r.get('date') or '') > to:
            continue
        if status and r.get('status') != status:
            continue
        if q:
            needle = q.strip().lower()
            if needle:
                hay = ' '.join([str(r.get(k, '')) for k in ['vehicle', 'plate', 'claim', 'carrier', 'towing_area']]).lower()
                if needle not in hay:
                    continue
        result.append({k: str(r.get(k, '')) for k in ['id', 'date', 'vehicle', 'plate', 'claim', 'carrier', 'towing_area', 'status', 'note', 'attachment_name', 'createdAt']})
    result.sort(key=lambda x: (x.get('date', ''), x.get('createdAt', '')), reverse=True)
    return jsonify({'ok': True, 'items': result})


@app.route('/api/records', methods=['POST'])
@require_auth
def api_create_record():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'BAD_REQUEST'}), 400
    date = str(body.get('date', ''))
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return jsonify({'ok': False, 'error': 'DATE_INVALID'}), 400
    vehicle = str(body.get('vehicle', '')).strip()
    if not vehicle:
        return jsonify({'ok': False, 'error': 'VEHICLE_REQUIRED'}), 400
    status = str(body.get('status', '')).strip() or 'not_towed'
    if status not in VALID_STATUS:
        return jsonify({'ok': False, 'error': 'STATUS_INVALID'}), 400
    rec = {
        'id': new_id(), 'date': date, 'vehicle': vehicle,
        'plate': str(body.get('plate', '')).strip(),
        'claim': str(body.get('claim', '')).strip(),
        'carrier': str(body.get('carrier', '')).strip(),
        'towing_area': str(body.get('towing_area', '')).strip(),
        'status': status, 'note': str(body.get('note', '')),
        'attachment_name': '', 'createdAt': datetime.now().isoformat()
    }
    if body.get('attachmentName') and body.get('attachmentBase64'):
        if not save_attachment(rec, body['attachmentName'], body['attachmentBase64']):
            return jsonify({'ok': False, 'error': 'ATTACHMENT_INVALID'}), 400
    records = get_records()
    records.append(rec)
    save_records(records)
    return jsonify({'ok': True, 'item': rec})


@app.route('/api/records/<rid>', methods=['PUT'])
@require_auth
def api_update_record(rid):
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'BAD_REQUEST'}), 400
    date = str(body.get('date', ''))
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return jsonify({'ok': False, 'error': 'DATE_INVALID'}), 400
    vehicle = str(body.get('vehicle', '')).strip()
    if not vehicle:
        return jsonify({'ok': False, 'error': 'VEHICLE_REQUIRED'}), 400
    status = str(body.get('status', '')).strip() or 'not_towed'
    if status not in VALID_STATUS:
        return jsonify({'ok': False, 'error': 'STATUS_INVALID'}), 400
    records = get_records()
    idx = next((i for i, r in enumerate(records) if r.get('id') == rid), -1)
    if idx < 0:
        return jsonify({'ok': False, 'error': 'NOT_FOUND'}), 404
    records[idx]['date'] = date
    records[idx]['vehicle'] = vehicle
    records[idx]['plate'] = str(body.get('plate', '')).strip()
    records[idx]['claim'] = str(body.get('claim', '')).strip()
    records[idx]['carrier'] = str(body.get('carrier', '')).strip()
    records[idx]['towing_area'] = str(body.get('towing_area', '')).strip()
    records[idx]['status'] = status
    records[idx]['note'] = str(body.get('note', ''))
    if body.get('attachmentName') and body.get('attachmentBase64'):
        if not save_attachment(records[idx], body['attachmentName'], body['attachmentBase64']):
            return jsonify({'ok': False, 'error': 'ATTACHMENT_INVALID'}), 400
    save_records(records)
    return jsonify({'ok': True, 'item': records[idx]})


@app.route('/api/records/<rid>', methods=['DELETE'])
@require_auth
def api_delete_record(rid):
    records = get_records()
    rec = next((r for r in records if r.get('id') == rid), None)
    if not rec:
        return jsonify({'ok': False, 'error': 'NOT_FOUND'}), 404
    p = attachment_path(rec)
    if p and os.path.exists(p):
        os.remove(p)
    records = [r for r in records if r.get('id') != rid]
    save_records(records)
    return jsonify({'ok': True})


@app.route('/api/records/<rid>/attachment', methods=['POST'])
@require_auth
def api_add_attachment(rid):
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'BAD_REQUEST'}), 400
    records = get_records()
    idx = next((i for i, r in enumerate(records) if r.get('id') == rid), -1)
    if idx < 0:
        return jsonify({'ok': False, 'error': 'NOT_FOUND'}), 404
    if not save_attachment(records[idx], body.get('attachmentName', ''), body.get('attachmentBase64', '')):
        return jsonify({'ok': False, 'error': 'ATTACHMENT_INVALID'}), 400
    save_records(records)
    return jsonify({'ok': True, 'attachment_name': records[idx].get('attachment_name', '')})


@app.route('/api/records/<rid>/attachment', methods=['DELETE'])
@require_auth
def api_delete_attachment(rid):
    records = get_records()
    idx = next((i for i, r in enumerate(records) if r.get('id') == rid), -1)
    if idx < 0:
        return jsonify({'ok': False, 'error': 'NOT_FOUND'}), 404
    p = attachment_path(records[idx])
    if p and os.path.exists(p):
        os.remove(p)
    records[idx]['attachment_name'] = ''
    save_records(records)
    return jsonify({'ok': True})


@app.route('/api/attachment/<rid>', methods=['GET'])
@require_auth
def api_download_attachment(rid):
    rec = next((r for r in get_records() if r.get('id') == rid), None)
    if not rec:
        return jsonify({'ok': False, 'error': 'NOT_FOUND'}), 404
    p = attachment_path(rec)
    if not p or not os.path.exists(p):
        return jsonify({'ok': False, 'error': 'NOT_FOUND'}), 404
    ct_map = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.doc': 'application/msword', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.zip': 'application/zip'}
    ext = os.path.splitext(rec.get('attachment_name', ''))[1].lower()
    ct = ct_map.get(ext, 'application/octet-stream')
    return send_file(p, mimetype=ct, as_attachment=True, download_name=rec['attachment_name'])


@app.route('/api/stats', methods=['GET'])
@require_auth
def api_stats():
    records = get_records()
    counts = {'towed': 0, 'not_towed': 0, 'rejected': 0, 'on_way': 0, 'could_not': 0, 'deferred': 0}
    for r in records:
        s = r.get('status', 'not_towed')
        counts[s] = counts.get(s, 0) + 1 if s in counts else counts.__setitem__('not_towed', counts.get('not_towed', 0) + 1) or 0
    sorted_recs = sorted(records, key=lambda x: (x.get('date', ''), x.get('createdAt', '')), reverse=True)
    recent = [{k: str(r.get(k, '')) for k in ['id', 'date', 'vehicle', 'plate', 'claim', 'carrier', 'towing_area', 'status', 'note']} for r in sorted_recs[:8]]
    return jsonify({'ok': True, 'total': len(records), 'counts': counts, 'recent': recent})


@app.route('/api/export', methods=['GET'])
@require_auth
def api_export():
    records = get_records()
    frm = request.args.get('from')
    to = request.args.get('to')
    status = request.args.get('status')
    q = request.args.get('q')
    ids_str = request.args.get('ids')
    id_set = set(i.strip() for i in ids_str.split(',') if i.strip()) if ids_str else set()
    rows = []
    for r in records:
        if id_set and r.get('id') not in id_set:
            continue
        if frm and (r.get('date') or '') < frm:
            continue
        if to and (r.get('date') or '') > to:
            continue
        if status and r.get('status') != status:
            continue
        if q:
            needle = q.strip().lower()
            if needle:
                hay = ' '.join([str(r.get(k, '')) for k in ['vehicle', 'plate', 'claim', 'carrier', 'towing_area']]).lower()
                if needle not in hay:
                    continue
        st = STATUS_AR.get(r.get('status', ''), r.get('status', ''))
        rows.append([r.get('date', ''), r.get('vehicle', ''), r.get('plate', ''), r.get('claim', ''), r.get('carrier', ''), r.get('towing_area', ''), st, r.get('note', ''), r.get('attachment_name', '')])
    headers = ['التاريخ', 'اسم المركبة', 'رقم اللوحة', 'رقم المطالبة', 'اسم الناقل', 'منطقة السحب', 'الحالة', 'ملاحظات', 'اسم الملف']
    xlsx = new_excel_bytes(headers, rows)
    return send_file(io.BytesIO(xlsx), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name='records.xlsx')


@app.route('/api/import', methods=['POST'])
@require_auth
def api_import():
    data = request.get_data()
    if not data:
        return jsonify({'ok': False, 'error': 'BAD_REQUEST'}), 400
    parsed = parse_excel_rows(data)
    if not parsed['headers'] or not parsed['rows']:
        return jsonify({'ok': False, 'error': 'IMPORT_EMPTY'}), 400
    field_map = {
        'date': ['التاريخ', 'date'], 'vehicle': ['اسم المركبة', 'المركبة', 'vehicle'],
        'plate': ['رقم اللوحة', 'اللوحة', 'plate'], 'claim': ['رقم المطالبة', 'المطالبة', 'claim'],
        'carrier': ['اسم الناقل', 'الناقل', 'carrier'], 'towing_area': ['منطقة السحب', 'منطقة', 'area'],
        'status': ['الحالة', 'حالة', 'status'], 'note': ['ملاحظات', 'ملاحظة', 'note']
    }
    col_of = {}
    for i, h in enumerate(parsed['headers']):
        h_clean = h.strip().lower()
        if not h_clean:
            continue
        for field, keywords in field_map.items():
            if field in col_of:
                continue
            for kw in keywords:
                if h_clean == kw or kw in h_clean:
                    col_of[field] = i
                    break
    if 'date' not in col_of or 'vehicle' not in col_of:
        return jsonify({'ok': False, 'error': 'IMPORT_HEADERS'}), 400
    records = get_records()
    existing_plates = {r.get('plate', '').replace(' ', '').lower() for r in records if r.get('plate')}
    imported = skipped = duplicates = 0
    for r in parsed['rows']:
        date = normalize_date(r[col_of['date']] if col_of['date'] < len(r) else '')
        vehicle = str(r[col_of['vehicle']] if col_of['vehicle'] < len(r) else '').strip()
        if not date or not vehicle:
            skipped += 1
            continue
        st = 'not_towed'
        if 'status' in col_of and col_of['status'] < len(r):
            ns = normalize_status(str(r[col_of['status']]))
            if ns:
                st = ns
        plate = str(r[col_of['plate']] if 'plate' in col_of and col_of['plate'] < len(r) else '').strip()
        pk = plate.replace(' ', '').lower()
        if pk and pk in existing_plates:
            duplicates += 1
            continue
        records.append({
            'id': new_id(), 'date': date, 'vehicle': vehicle, 'plate': plate,
            'claim': str(r[col_of['claim']] if 'claim' in col_of and col_of['claim'] < len(r) else '').strip(),
            'carrier': str(r[col_of['carrier']] if 'carrier' in col_of and col_of['carrier'] < len(r) else '').strip(),
            'towing_area': str(r[col_of['towing_area']] if 'towing_area' in col_of and col_of['towing_area'] < len(r) else '').strip(),
            'status': st,
            'note': str(r[col_of['note']] if 'note' in col_of and col_of['note'] < len(r) else ''),
            'attachment_name': '', 'createdAt': datetime.now().isoformat()
        })
        if pk:
            existing_plates.add(pk)
        imported += 1
    save_records(records)
    return jsonify({'ok': True, 'imported': imported, 'skipped': skipped, 'duplicates': duplicates})


@app.route('/api/change-password', methods=['POST'])
@require_auth
def api_change_password():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'BAD_REQUEST'}), 400
    cur = str(body.get('currentPassword', ''))
    new = str(body.get('newPassword', ''))
    if len(new) < 6:
        return jsonify({'ok': False, 'error': 'PASSWORD_SHORT'}), 400
    users = get_users()
    for u in users:
        if u.get('username') == request.auth_user['username']:
            if hash_password(cur, u['salt']) != u['passHash']:
                return jsonify({'ok': False, 'error': 'PASSWORD_WRONG'}), 400
            u['salt'] = new_id()[:8]
            u['passHash'] = hash_password(new, u['salt'])
            save_users(users)
            return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'NOT_FOUND'}), 404


@app.route('/api/change-username', methods=['POST'])
@require_auth
def api_change_username():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'BAD_REQUEST'}), 400
    new_name = str(body.get('newUsername', '')).strip()
    if not new_name:
        return jsonify({'ok': False, 'error': 'NAME_REQUIRED'}), 400
    if len(new_name) > 30:
        return jsonify({'ok': False, 'error': 'NAME_TOO_LONG'}), 400
    password = str(body.get('password', ''))
    users = get_users()
    for u in users:
        if u.get('username') == request.auth_user['username']:
            if hash_password(password, u['salt']) != u['passHash']:
                return jsonify({'ok': False, 'error': 'PASSWORD_WRONG'}), 400
            for other in users:
                if other is not u and other.get('username') == new_name:
                    return jsonify({'ok': False, 'error': 'USER_EXISTS'}), 400
            u['username'] = new_name
            save_users(users)
            for sess in sessions.values():
                if sess['username'] == request.auth_user['username']:
                    sess['username'] = new_name
            return jsonify({'ok': True, 'username': new_name})
    return jsonify({'ok': False, 'error': 'NOT_FOUND'}), 404


@app.route('/api/health', methods=['GET'])
def api_health():
    return jsonify({'ok': True, 'status': 'healthy'})


@app.route('/health', methods=['GET'])
def health_root():
    return jsonify({'ok': True, 'status': 'healthy'})


# ============ Static files (SPA) ============

@app.route('/')
@app.route('/index.html')
def serve_index():
    return send_from_directory(WEB_DIR, 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    full = os.path.join(WEB_DIR, path)
    if os.path.isfile(full):
        return send_from_directory(WEB_DIR, path)
    return send_from_directory(WEB_DIR, 'index.html')


ensure_data()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8081))
    print(f'Server starting on port {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
