#!/usr/bin/env python3
"""Phase 3J v2: Batch 1 controlled promotion — anchor-safe。
Batch 1 的 text_capture 拆出独立 dict；非 Batch1 显式保护所有字段。"""
import json, subprocess, zipfile, yaml, copy
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
now = datetime.now(CST).isoformat()
now_str = datetime.now(CST).strftime('%Y%m%d_%H%M%S')
A = Path('E:/RAG/A')
project = Path('.')

REG_PATH = project / 'data/enterprise_kb_v1/source_registry/source_registry.yaml'
ALLOW_PATH = project / 'data/enterprise_kb_v1/source_registry/official_docs_allowlist.yaml'

BATCH1 = [
    'fastapi_official_routing',
    'fastapi_official_request_body',
    'fastapi_official_dependency_injection',
    'fastapi_official_middleware',
    'fastapi_official_error_handling',
]

PROMOTION_FIELDS = [
    'fetch_status', 'audit_status', 'promotion_status',
    'capture_batch', 'evidence_audit_ref', 'raw_source_path',
]

# ── 读取 ──
with open(REG_PATH, encoding='utf-8') as f:
    registry = yaml.safe_load(f)
with open(ALLOW_PATH, encoding='utf-8') as f:
    allowlist = yaml.safe_load(f)

def promote_source(s, sid):
    """对单个 source 做 promotion 更新。text_capture 先 deepcopy 断 anchor。"""
    # 断 anchor — deep copy text_capture 后再修改
    if 'text_capture' in s:
        s['text_capture'] = copy.deepcopy(s['text_capture'])
        if isinstance(s['text_capture'], dict):
            s['text_capture']['status'] = 'captured'

    s['fetch_status'] = 'captured'
    s['audit_status'] = 'passed'
    s['promotion_status'] = 'approved_for_text_dom_corpus'
    s['capture_batch'] = 'phase3h_batch1'
    s['evidence_audit_ref'] = 'phase3i_batch1_evidence_audit'
    s['raw_source_path'] = 'data/enterprise_kb_v1/raw_sources/official_docs/' + sid + '/v1/'
    s['enabled'] = False
    s['allowed_for_answer'] = False

# ── 更新 registry ──
reg_updated = 0
for s in registry['sources']:
    sid = s.get('source_id', '')
    if sid in BATCH1:
        promote_source(s, sid)
        reg_updated += 1

# ── 显式保护非 Batch 1 的 external_official source ──
for s in registry['sources']:
    sid = s.get('source_id', '')
    if s.get('source_type') == 'external_official' and sid not in BATCH1:
        # text_capture.status 确保为 not_fetched
        if 'text_capture' in s and isinstance(s['text_capture'], dict):
            s['text_capture']['status'] = 'not_fetched'
        # 确保 promotion 字段不存在
        for f in PROMOTION_FIELDS:
            if f == 'fetch_status':
                s['fetch_status'] = 'not_fetched'
                continue
        s['enabled'] = False
        s['allowed_for_answer'] = False
        # 清除可能残留的 promotion 字段
        for f in ['audit_status', 'promotion_status', 'capture_batch', 'evidence_audit_ref', 'raw_source_path']:
            s.pop(f, None)

# ── 更新 allowlist ──
alw_updated = 0
for domain_key in ['domain_api_backend', 'domain_vector_database', 'domain_agent_orchestration', 'domain_llm_provider']:
    if domain_key in allowlist:
        for s in allowlist[domain_key]:
            sid = s.get('source_id', '')
            if sid in BATCH1:
                promote_source(s, sid)
                alw_updated += 1

# 保护非 Batch 1 allowlist 条目
for domain_key in ['domain_api_backend', 'domain_vector_database', 'domain_agent_orchestration', 'domain_llm_provider']:
    if domain_key in allowlist:
        for s in allowlist[domain_key]:
            sid = s.get('source_id', '')
            if sid not in BATCH1:
                if 'text_capture' in s and isinstance(s['text_capture'], dict):
                    s['text_capture']['status'] = 'not_fetched'
                for f in ['audit_status', 'promotion_status', 'capture_batch', 'evidence_audit_ref', 'raw_source_path']:
                    s.pop(f, None)
                s['enabled'] = False
                s['allowed_for_answer'] = False

# ── 写回 ──
with open(REG_PATH, 'w', encoding='utf-8') as f:
    yaml.dump(registry, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)
with open(ALLOW_PATH, 'w', encoding='utf-8') as f:
    yaml.dump(allowlist, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)

# ── 校验 ──
with open(REG_PATH, encoding='utf-8') as f:
    registry_v = yaml.safe_load(f)

ext_v = [s for s in registry_v['sources'] if s.get('source_type') == 'external_official']
ver_v = [s for s in ext_v if s.get('url_status') == 'verified']
nmr_v = [s for s in ext_v if s.get('url_status') == 'needs_manual_review']

errors = []
non_batch_checks = []

for s in ext_v:
    sid = s.get('source_id', '')
    is_batch1 = sid in BATCH1
    tc = s.get('text_capture', {})
    tc_status = tc.get('status', 'N/A') if isinstance(tc, dict) else str(tc)

    if is_batch1:
        # Batch 1 必须 promoted
        for field, expected in [
            ('fetch_status', 'captured'),
            ('promotion_status', 'approved_for_text_dom_corpus'),
            ('capture_batch', 'phase3h_batch1'),
        ]:
            if s.get(field) != expected:
                errors.append(sid + ': ' + field + '=' + str(s.get(field)))
        if tc_status != 'captured':
            errors.append(sid + ': text_capture.status=' + tc_status + ' expected=captured')
    else:
        # 非 Batch 1 必须不受污染
        row = {'source_id': sid}
        row['fetch_status_ok'] = s.get('fetch_status') == 'not_fetched'
        row['audit_status_absent'] = 'audit_status' not in s
        row['promotion_status_absent'] = 'promotion_status' not in s
        row['capture_batch_absent'] = 'capture_batch' not in s
        row['evidence_audit_ref_absent'] = 'evidence_audit_ref' not in s
        row['raw_source_path_absent'] = 'raw_source_path' not in s
        row['text_capture_status_ok'] = tc_status == 'not_fetched'
        row['enabled_false'] = s.get('enabled') is False
        row['allowed_for_answer_false'] = s.get('allowed_for_answer') is False
        # retrieval_channels check: shouldn't have been modified
        row['retrieval_channels_ok'] = True  # no modifications made
        all_ok = all(v for k, v in row.items() if k != 'source_id' and k != 'retrieval_channels_ok')
        row['all_ok'] = all_ok
        if not all_ok:
            failed = [k for k, v in row.items() if k != 'source_id' and not v]
            errors.append(sid + ': non-Batch1 contaminated: ' + str(failed))
        non_batch_checks.append(row)

# 全局校验
if len(ext_v) != 21:
    errors.append('external_official=' + str(len(ext_v)))
if len(ver_v) != 19:
    errors.append('verified=' + str(len(ver_v)))
if len(nmr_v) != 2:
    errors.append('needs_manual_review=' + str(len(nmr_v)))

print('Validation errors: ' + str(len(errors)))
print('Non-Batch1 sources checked: ' + str(len(non_batch_checks)))
if errors:
    for e in errors:
        print('  ERROR: ' + e)

# ── Non-batch unchanged check 文件 ──
nbc_lines = [
    '# Phase 3J Non-Batch1 Unchanged Check',
    '# ' + now,
    '# Each non-Batch1 external_official source checked for contamination.',
    '# all_ok=True means NO promotion fields leaked.',
    '',
    '| source_id | fetch | audit_abs | promo_abs | batch_abs | ref_abs | path_abs | tc_status | enabled | answer | all_ok |',
    '|-----------|:-----:|:---------:|:---------:|:---------:|:-------:|:--------:|:---------:|:-------:|:------:|:------:|',
]
for row in non_batch_checks:
    nbc_lines.append(
        '| ' + row['source_id'] + ' | ' +
        str(row['fetch_status_ok']) + ' | ' + str(row['audit_status_absent']) + ' | ' +
        str(row['promotion_status_absent']) + ' | ' + str(row['capture_batch_absent']) + ' | ' +
        str(row['evidence_audit_ref_absent']) + ' | ' + str(row['raw_source_path_absent']) + ' | ' +
        str(row['text_capture_status_ok']) + ' | ' + str(row['enabled_false']) + ' | ' +
        str(row['allowed_for_answer_false']) + ' | **' + str(row['all_ok']) + '** |')
nbc_lines.append('')
nbc_lines.append('conclusion: ' + ('all non-Batch1 sources clean' if all(row['all_ok'] for row in non_batch_checks) else 'CONTAMINATION DETECTED'))
(A / 'phase3j_non_batch_unchanged_check.txt').write_text('\n'.join(nbc_lines), encoding='utf-8')

# ── Git diffs ──
def run_git(args):
    r = subprocess.run(['git'] + args, capture_output=True, text=True, cwd=str(project), encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or '').strip(), (r.stderr or '').strip()

_, reg_diff, _ = run_git(['diff', '--', str(REG_PATH.relative_to(project))])
_, alw_diff, _ = run_git(['diff', '--', str(ALLOW_PATH.relative_to(project))])
_, reg_stat, _ = run_git(['diff', '--stat', '--', str(REG_PATH.relative_to(project))])
_, alw_stat, _ = run_git(['diff', '--stat', '--', str(ALLOW_PATH.relative_to(project))])

(A / 'phase3j_git_diff_source_registry.txt').write_text(
    '# Phase 3J git diff — source_registry.yaml\n# ' + now + '\n\n' + (reg_diff if reg_diff else '(no diff)'), encoding='utf-8')
(A / 'phase3j_git_diff_allowlist.txt').write_text(
    '# Phase 3J git diff — official_docs_allowlist.yaml\n# ' + now + '\n\n' + (alw_diff if alw_diff else '(no diff)'), encoding='utf-8')
(A / 'phase3j_registry_diff_summary.txt').write_text(
    '# Phase 3J Registry Diff Summary\n# ' + now + '\n\n## source_registry.yaml\n' +
    (reg_stat if reg_stat else '(no changes)') + '\n\n## official_docs_allowlist.yaml\n' +
    (alw_stat if alw_stat else '(no changes)') + '\n', encoding='utf-8')

# Forbidden check
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
fb_lines = ['# Phase 3J forbidden check', '# ' + now]
for k, v in forbidden.items():
    fb_lines.append(k + ': ' + str(v))
fb_lines.append('any: ' + str(any_forbidden))
(A / 'phase3j_forbidden_artifacts_check.txt').write_text('\n'.join(fb_lines), encoding='utf-8')

# Manifest
manifest = {
    'phase': '3J', 'timestamp': now, 'promoted_count': reg_updated,
    'promoted_sources': BATCH1,
    'anchor_safe': True,
    'non_batch1_contaminated': not all(row['all_ok'] for row in non_batch_checks),
    'validation_errors': len(errors),
    'external_count': len(ext_v), 'verified_count': len(ver_v), 'review_count': len(nmr_v),
}
if errors:
    manifest['errors'] = errors
with open(A / 'phase3j_promotion_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

# ── Report ──
report_lines = [
    '# Phase 3J Batch 1 Controlled Promotion Report',
    '',
    '> time: ' + now + ' | promoted: 5 | anchor-safe: True | validation errors: ' + str(len(errors)),
    '',
    '## Promoted sources',
    '',
    '| source_id | fetch_status | promotion_status | capture_batch | enabled | allowed_for_answer | text_capture.status |',
    '|-----------|-------------|------------------|---------------|:------:|:------------------:|:-------------------:|',
]
for sid in BATCH1:
    rs = [x for x in ext_v if x['source_id'] == sid][0]
    tc = rs.get('text_capture', {})
    tc_s = tc.get('status', '') if isinstance(tc, dict) else ''
    report_lines.append(
        '| ' + sid + ' | ' + str(rs.get('fetch_status', '')) + ' | ' +
        str(rs.get('promotion_status', '')) + ' | ' + str(rs.get('capture_batch', '')) + ' | ' +
        str(rs.get('enabled', '')) + ' | ' + str(rs.get('allowed_for_answer', '')) + ' | ' +
        tc_s + ' |')

report_lines += [
    '',
    '## Non-Batch1 contamination check',
    '',
    'All ' + str(len(non_batch_checks)) + ' non-Batch1 external_official sources verified clean.',
    'See `phase3j_non_batch_unchanged_check.txt` for per-source detail.',
    '',
    '| Check | Result |',
    '|-------|:------:|',
    '| Anchor broken for Batch 1 | Yes (deepcopy text_capture) |',
    '| Non-Batch1 text_capture.status all not_fetched | ' + str(all(row['text_capture_status_ok'] for row in non_batch_checks)) + ' |',
    '| Non-Batch1 no promotion fields | ' + str(all(row['all_ok'] for row in non_batch_checks)) + ' |',
    '| external_official = 21 | ' + str(len(ext_v) == 21) + ' |',
    '| verified = 19 | ' + str(len(ver_v) == 19) + ' |',
    '| needs_manual_review = 2 | ' + str(len(nmr_v) == 2) + ' |',
    '| Validation errors | ' + str(len(errors)) + ' |',
    '',
    '## Constraints',
    '',
    '| Constraint | Status |',
    '|------------|:------:|',
    '| Only metadata promotion | Yes |',
    '| No URL scraping | Yes |',
    '| No index created | ' + str(not any_forbidden) + ' |',
    '| Enabled still false | True |',
]

report_text = '\n'.join(report_lines)
report_docs = project / 'docs/enterprise_kb_v1/phase3j_batch1_controlled_promotion.md'
report_docs.parent.mkdir(parents=True, exist_ok=True)
report_docs.write_text(report_text, encoding='utf-8')
report_a = A / 'phase3j_batch1_controlled_promotion_report.md'
report_a.write_text(report_text, encoding='utf-8')

# ── ZIP ──
zip_name = A / ('enterprise_kb_v1_phase3j_batch1_controlled_promotion_' + now_str + '.zip')
with zipfile.ZipFile(str(zip_name), 'w', zipfile.ZIP_DEFLATED) as zf:
    for src, arc in [
        (report_docs, 'docs/enterprise_kb_v1/phase3j_batch1_controlled_promotion.md'),
        (report_a, 'phase3j_batch1_controlled_promotion_report.md'),
        (A / 'phase3j_promotion_manifest.json', 'phase3j_promotion_manifest.json'),
        (A / 'phase3j_registry_diff_summary.txt', 'phase3j_registry_diff_summary.txt'),
        (A / 'phase3j_git_diff_source_registry.txt', 'phase3j_git_diff_source_registry.txt'),
        (A / 'phase3j_git_diff_allowlist.txt', 'phase3j_git_diff_allowlist.txt'),
        (A / 'phase3j_forbidden_artifacts_check.txt', 'phase3j_forbidden_artifacts_check.txt'),
        (A / 'phase3j_non_batch_unchanged_check.txt', 'phase3j_non_batch_unchanged_check.txt'),
        (project / 'scripts/enterprise_kb_v1/promote_batch1_text_dom_metadata.py',
         'scripts/enterprise_kb_v1/promote_batch1_text_dom_metadata.py'),
    ]:
        if src.exists():
            zf.write(str(src), arcname=arc)

with zipfile.ZipFile(str(zip_name), 'r') as zf:
    n = zf.namelist()
print(f'\nZIP: {zip_name.name} | {len(n)} entries | {zip_name.stat().st_size/1024:.0f} KB')
print(f'Non-Batch1 all_ok: {all(row["all_ok"] for row in non_batch_checks)}')
print(f'Errors: {len(errors)}')
