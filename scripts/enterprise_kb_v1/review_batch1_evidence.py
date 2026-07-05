#!/usr/bin/env python3
"""Phase 3I: Batch 1 evidence audit / promotion review。
读取 5 个 FastAPI source 产物，复算 audit 指标，逐项检查。不抓取、不索引。"""
import json, re, subprocess, zipfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

CST = timezone(timedelta(hours=8))
now = datetime.now(CST).isoformat()
now_str = datetime.now(CST).strftime('%Y%m%d_%H%M%S')
A = Path('E:/RAG/A')
project = Path('.')
BASE = project / 'data/enterprise_kb_v1/raw_sources/official_docs'

SOURCES = [
    'fastapi_official_routing',
    'fastapi_official_request_body',
    'fastapi_official_dependency_injection',
    'fastapi_official_middleware',
    'fastapi_official_error_handling',
]

class TableCounter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.count = 0
    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.count += 1

def count_md_tables(body):
    lines = body.split('\n')
    tables = 0
    in_fence = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if re.match(r'^\|?\s*[-:]+(\s*\|\s*[-:]+\s*)+\|?\s*$', s):
            prev = lines[i-1].strip() if i > 0 else ''
            nxt = lines[i+1].strip() if i+1 < len(lines) else ''
            if '|' in prev and '|' in nxt:
                tables += 1
    return tables

def extract_body(md_text):
    """提取 front matter 之后的正文。"""
    if not md_text.startswith('---'):
        return md_text
    end = md_text.find('---', 3)
    if end < 0:
        return md_text
    body_start = md_text.find('\n', end + 3) + 1
    return md_text[body_start:]

def audit_from_evidence(raw_path, md_path):
    """从 raw.html + normalized.md 复算 audit 指标。返回 (audit_dict, warnings)。"""
    warnings = []
    raw_html = raw_path.read_text(encoding='utf-8')
    md_text = md_path.read_text(encoding='utf-8')
    body = extract_body(md_text)

    # Headings
    headings = {}
    for m in re.finditer(r'^(#{1,6})\s+(.+)', body, re.MULTILINE):
        level = len(m.group(1))
        headings[f'h{level}'] = headings.get(f'h{level}', 0) + 1
    total_h = sum(headings.values())

    # Code blocks (fenced)
    code_count = len(re.findall(r'^```', body, re.MULTILINE)) // 2
    legacy_code = len(re.findall(r'\[code\]|\[/code\]', body))

    # Tables
    tc = TableCounter()
    tc.feed(raw_html)
    html_tables = tc.count
    md_tables = count_md_tables(body)

    # Links
    links = len(re.findall(r'\[([^\]]+)\]\(([^)]+)\)', body))

    # Empty / zero-width headings
    empty_h = len(re.findall(r'^(#{1,6})\s*$', body, re.MULTILINE))
    zw_empty = 0
    for line in body.split('\n'):
        m = re.match(r'^(#{1,6})(.*)$', line)
        if m:
            rest = m.group(2)
            stripped = rest
            for ch in ['​', '‌', '‍', '﻿', '­', ' ']:
                stripped = stripped.replace(ch, '')
            if stripped == '' and rest != '':
                zw_empty += 1
            elif rest.strip() == '':
                zw_empty += 1

    # Front matter check
    fm_ok = md_text.startswith('---') and md_text.find('---', 3) > 0

    # Byte sizes from disk
    raw_bytes = raw_path.stat().st_size
    md_bytes = md_path.stat().st_size

    # Warnings
    if legacy_code > 0:
        warnings.append(f'legacy_code_tags={legacy_code}')
    if empty_h > 0:
        warnings.append(f'empty_headings={empty_h}')
    if zw_empty > 0:
        warnings.append(f'zero_width_headings={zw_empty}')
    if raw_bytes < 500:
        warnings.append('raw_html_too_small')
    if not fm_ok:
        warnings.append('front_matter_missing')

    audit = {
        'heading_count_by_level': headings,
        'heading_count_total': total_h,
        'code_block_count': code_count,
        'legacy_code_tag_count': legacy_code,
        'html_table_count': html_tables,
        'markdown_table_block_count': md_tables,
        'table_count': md_tables,
        'link_count': links,
        'empty_heading_count': empty_h,
        'zero_width_empty_heading_count': zw_empty,
        'front_matter_ok': fm_ok,
        'raw_html_bytes_disk': raw_bytes,
        'normalized_md_bytes_disk': md_bytes,
        'format_ok': legacy_code == 0 and empty_h == 0 and zw_empty == 0 and fm_ok,
        'warnings': warnings,
    }
    return audit, warnings

# ── 逐 source 审查 ──
results = []
all_audit_pass = True
promotion_blockers = []

for sid in SOURCES:
    d = BASE / sid / 'v1'
    r = {'source_id': sid, 'output_dir': str(d.relative_to(project))}

    # 文件存在性
    for fn in ['raw.html', 'normalized.md', 'text_metadata.json', 'audit.json']:
        p = d / fn
        r[fn + '_exists'] = p.exists()
        if p.exists():
            r[fn + '_size'] = p.stat().st_size

    if not all(r.get(fn + '_exists') for fn in ['raw.html', 'normalized.md', 'text_metadata.json', 'audit.json']):
        r['evidence_sufficient'] = False
        r['missing_files'] = [fn for fn in ['raw.html', 'normalized.md', 'text_metadata.json', 'audit.json'] if not r.get(fn + '_exists')]
        r['audit_pass'] = False
        results.append(r)
        all_audit_pass = False
        promotion_blockers.append(f'{sid}: missing files {r["missing_files"]}')
        continue

    raw_path = d / 'raw.html'
    md_path = d / 'normalized.md'
    meta_path = d / 'text_metadata.json'
    audit_path = d / 'audit.json'

    # 复算 audit
    evidence_audit, evidence_warnings = audit_from_evidence(raw_path, md_path)

    # 读取存储的 audit.json + text_metadata.json
    with open(audit_path, encoding='utf-8') as f:
        stored_audit = json.load(f)
    with open(meta_path, encoding='utf-8') as f:
        stored_meta = json.load(f)

    # ── 逐项交叉验证 ──
    checks = {}

    # 字节数一致性
    checks['raw_bytes_match'] = stored_audit.get('raw_html_bytes', -1) == evidence_audit['raw_html_bytes_disk']
    checks['md_bytes_match'] = stored_audit.get('normalized_md_bytes', -1) == evidence_audit['normalized_md_bytes_disk']

    # Audit 指标一致性
    for key in ['heading_count_total', 'code_block_count', 'table_count', 'link_count',
                'empty_heading_count', 'zero_width_empty_heading_count']:
        stored_val = stored_audit.get(key, -1)
        evidence_val = evidence_audit.get(key, -1)
        checks[key + '_match'] = stored_val == evidence_val

    # heading_by_level 一致性
    stored_hl = stored_audit.get('heading_count_by_level', {})
    evidence_hl = evidence_audit.get('heading_count_by_level', {})
    checks['headings_detail_match'] = stored_hl == evidence_hl

    # metadata 服从 audit
    meta_vs_audit = {
        'heading_count': stored_meta.get('heading_count', {}) == stored_audit.get('heading_count_by_level', {}),
        'code_block_count': stored_meta.get('code_block_count', -1) == stored_audit.get('code_block_count', -1),
        'table_count': stored_meta.get('table_count', -1) == stored_audit.get('table_count', -1),
        'link_count': stored_meta.get('link_count', -1) == stored_audit.get('link_count', -1),
    }
    checks['metadata_obeys_audit'] = all(meta_vs_audit.values())

    # 格式检查
    checks['no_legacy_code'] = evidence_audit['legacy_code_tag_count'] == 0
    checks['no_empty_headings'] = evidence_audit['empty_heading_count'] == 0
    checks['no_zero_width_headings'] = evidence_audit['zero_width_empty_heading_count'] == 0
    checks['front_matter_ok'] = evidence_audit['front_matter_ok']
    checks['fenced_code_blocks'] = evidence_audit['code_block_count'] > 0

    # 字段完整性
    checks['origin_url_present'] = bool(stored_audit.get('origin_url'))
    checks['source_id_present'] = bool(stored_audit.get('source_id'))
    checks['final_url_present'] = bool(stored_audit.get('final_url'))

    # Content warnings
    content_warnings = list(evidence_warnings)
    if stored_audit.get('http_status', 200) != 200:
        content_warnings.append(f'http_status={stored_audit.get("http_status")}')
    if stored_audit.get('redirected'):
        content_warnings.append('url_redirected')
    if evidence_audit['heading_count_total'] == 0:
        content_warnings.append('no_headings_found')
    if evidence_audit['code_block_count'] == 0:
        content_warnings.append('no_code_blocks_found')

    all_checks_ok = all(checks.values())
    r['checks'] = checks
    r['content_warnings'] = content_warnings
    r['evidence_audit'] = evidence_audit
    r['audit_pass'] = all_checks_ok and len(content_warnings) == 0
    r['evidence_sufficient'] = True

    if not all_checks_ok:
        all_audit_pass = False
        failed_checks = [k for k, v in checks.items() if not v]
        promotion_blockers.append(f'{sid}: checks failed {failed_checks}')
    if content_warnings:
        promotion_blockers.append(f'{sid}: warnings {content_warnings}')
        r['audit_pass'] = False

    results.append(r)
    status = 'PASS' if r['audit_pass'] else 'FAIL'
    print(f'{sid}: checks={sum(checks.values())}/{len(checks)} warnings={len(content_warnings)} {status}')

# ── 综合判定 ──
promote_ready = all_audit_pass and len(promotion_blockers) == 0
if promote_ready:
    recommended_next = 'Phase 3I complete — 5/5 sources audit pass, recommend promotion to enabled state after human sign-off'
else:
    recommended_next = 'Fix promotion_blockers before enabling sources'

# ── Git evidence ──
def run_git(args):
    r = subprocess.run(['git'] + args, capture_output=True, text=True, cwd=str(project))
    return r.returncode, r.stdout.strip(), r.stderr.strip()

_, out_reg, _ = run_git(['status', '--short', '--',
    'data/enterprise_kb_v1/source_registry/source_registry.yaml',
    'data/enterprise_kb_v1/source_registry/official_docs_allowlist.yaml'])
registry_clean = not bool(out_reg.strip())
_, out_exp, _ = run_git(['status', '--short', '--', 'data/enterprise_kb_v1/experiments/'])
_, out_stg, _ = run_git(['diff', '--cached', '--name-only'])
staged_empty = not bool(out_stg.strip())

def count_glob(pattern):
    return len([x for x in project.rglob(pattern) if '.git' not in str(x) and '__pycache__' not in str(x)])

forbidden = {
    'chroma_persist_dir': (project / 'storage/chroma_enterprise_kb_v1').exists(),
    'faiss_files': count_glob('*.faiss'), 'index_files': count_glob('*.index'),
    'pkl_files': count_glob('*.pkl'), 'bin_files': count_glob('*.bin'),
    'parquet_files': count_glob('*.parquet'), 'h5_files': count_glob('*.h5'),
    'pt_files': count_glob('*.pt'), 'onnx_files': count_glob('*.onnx'),
}
any_forbidden = forbidden['chroma_persist_dir'] or sum(v for k, v in forbidden.items() if k != 'chroma_persist_dir') > 0

prefix = 'phase3i_batch1_'
for fn, content in [
    ('git_status_registry_allowlist.txt',
     '# Phase 3I git — registry/allowlist\n# ' + now + '\n# ' + (out_reg if out_reg else '(clean)') + '\n# modified: ' + str(not registry_clean)),
    ('git_status_experiments.txt',
     '# Phase 3I git — experiments\n# ' + now + '\n# ' + (out_exp if out_exp else '(clean — gitignored)') + '\n# staged: False'),
    ('git_diff_cached_names.txt',
     '# Phase 3I git diff cached\n# ' + now + '\n# ' + (out_stg if out_stg else '(empty)') + '\n# staged: ' + str(not staged_empty)),
]:
    (A / (prefix + fn)).write_text(content, encoding='utf-8')

fb_lines = ['# Phase 3I forbidden check', '# ' + now]
for k, v in forbidden.items():
    fb_lines.append(k + ': ' + str(v))
fb_lines.append('any: ' + str(any_forbidden))
(A / (prefix + 'forbidden_artifacts_check.txt')).write_text('\n'.join(fb_lines), encoding='utf-8')

# Inventory
inv = ['# Phase 3I Evidence Inventory', '# ' + now, '#']
for r in results:
    inv.append('# ' + r['source_id'] + ':')
    for fn in ['raw.html', 'normalized.md', 'text_metadata.json', 'audit.json']:
        inv.append('  ' + fn + ': ' + ('EXISTS' if r.get(fn + '_exists') else 'MISSING') + ' (' + str(r.get(fn + '_size', 0)) + ' bytes)')
inv.append('# promote_ready: ' + str(promote_ready))
(A / (prefix + 'evidence_inventory.txt')).write_text('\n'.join(inv), encoding='utf-8')

# Manifest
manifest = {
    'phase': '3I', 'timestamp': now, 'source_count': 5,
    'all_audit_pass': all_audit_pass,
    'promote_ready': promote_ready,
    'promotion_blockers': promotion_blockers,
    'recommended_next_action': recommended_next,
    'registry_clean': registry_clean, 'staged_empty': staged_empty,
    'any_forbidden': any_forbidden,
    'sources': [],
}
for r in results:
    manifest['sources'].append({
        'source_id': r['source_id'],
        'evidence_sufficient': r.get('evidence_sufficient', False),
        'audit_pass': r['audit_pass'],
        'checks_passed': sum(r.get('checks', {}).values()) if r.get('checks') else 0,
        'checks_total': len(r.get('checks', {})) if r.get('checks') else 0,
        'content_warnings': r.get('content_warnings', []),
    })
with open(A / 'phase3i_batch1_review_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

# ── Report ──
report_lines = [
    '# Phase 3I Batch 1 Evidence Audit / Promotion Review',
    '',
    '> time: ' + now + ' | sources: 5 | audit_pass: ' + str(all_audit_pass),
    '> promote_ready: ' + str(promote_ready),
    '',
    '## Per-source audit results',
    '',
    '| source_id | raw.html | norm.md | metadata | audit.json | checks | warnings | status |',
    '|-----------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|',
]
for r in results:
    checks_n = sum(r.get('checks', {}).values()) if r.get('checks') else 0
    checks_t = len(r.get('checks', {})) if r.get('checks') else 0
    warnings_n = len(r.get('content_warnings', []))
    status = 'PASS' if r['audit_pass'] else 'FAIL'
    report_lines.append(
        f'| {r["source_id"]} | {"OK" if r.get("raw.html_exists") else "MISS"} | '
        f'{"OK" if r.get("normalized.md_exists") else "MISS"} | '
        f'{"OK" if r.get("text_metadata.json_exists") else "MISS"} | '
        f'{"OK" if r.get("audit.json_exists") else "MISS"} | '
        f'{checks_n}/{checks_t} | {warnings_n} | **{status}** |')

report_lines += [
    '',
    '## Promotion review',
    '',
    '| Field | Value |',
    '|-------|-------|',
    '| promote_ready | ' + str(promote_ready) + ' |',
    '| promotion_blockers | ' + (str(len(promotion_blockers)) + ' items' if promotion_blockers else 'none') + ' |',
    '| recommended_next_action | ' + recommended_next + ' |',
    '',
]
if promotion_blockers:
    for b in promotion_blockers:
        report_lines.append('- ' + b)

report_lines += [
    '',
    '## Constraints check',
    '',
    '| Constraint | Status |',
    '|------------|:------:|',
    '| Phase 3I only (evidence audit) | Yes |',
    '| Sources reviewed | 5 |',
    '| Registry modified | ' + str(not registry_clean) + ' |',
    '| Allowlist modified | ' + str(not registry_clean) + ' |',
    '| Sources enabled | False |',
    '| Chroma/index created | ' + str(any_forbidden) + ' |',
    '| Screenshots taken | False |',
]

report_text = '\n'.join(report_lines)
report_docs = project / 'docs/enterprise_kb_v1/phase3i_batch1_evidence_audit_promotion_review.md'
report_docs.parent.mkdir(parents=True, exist_ok=True)
report_docs.write_text(report_text, encoding='utf-8')
report_a = A / 'phase3i_batch1_evidence_audit_report.md'
report_a.write_text(report_text, encoding='utf-8')

# ── ZIP ──
zip_name = A / ('enterprise_kb_v1_phase3i_batch1_evidence_audit_' + now_str + '.zip')
with zipfile.ZipFile(str(zip_name), 'w', zipfile.ZIP_DEFLATED) as zf:
    # Reports
    zf.write(str(report_docs), arcname='docs/enterprise_kb_v1/phase3i_batch1_evidence_audit_promotion_review.md')
    zf.write(str(report_a), arcname='phase3i_batch1_evidence_audit_report.md')
    # Manifest + inventory
    zf.write(str(A / 'phase3i_batch1_review_manifest.json'), arcname='phase3i_batch1_review_manifest.json')
    zf.write(str(A / (prefix + 'evidence_inventory.txt')), arcname=prefix + 'evidence_inventory.txt')
    # Git evidence
    for fn in ['git_status_registry_allowlist.txt', 'git_status_experiments.txt',
               'git_diff_cached_names.txt', 'forbidden_artifacts_check.txt']:
        zf.write(str(A / (prefix + fn)), arcname=prefix + fn)
    # Script
    zf.write(str(project / 'scripts/enterprise_kb_v1/review_batch1_evidence.py'),
             arcname='scripts/enterprise_kb_v1/review_batch1_evidence.py')
    # Audit evidence (5 sources × 2 key files)
    for sid in SOURCES:
        d = BASE / sid / 'v1'
        for fn in ['audit.json', 'text_metadata.json']:
            src = d / fn
            zf.write(str(src), arcname='evidence/' + sid + '/' + fn)

with zipfile.ZipFile(str(zip_name), 'r') as zf:
    n = zf.namelist()
print(f'\nZIP: {zip_name.name} | {len(n)} entries | {zip_name.stat().st_size/1024:.0f} KB')
print(f'promote_ready: {promote_ready}')
print(f'blockers: {len(promotion_blockers)}')
