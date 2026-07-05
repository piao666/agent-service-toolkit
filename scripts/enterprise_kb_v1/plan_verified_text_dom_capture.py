#!/usr/bin/env python3
"""Phase 3G: 从 source_registry.yaml 读取 19 条 verified external_official source，
生成 Text/DOM 正式采集 dry-run manifest。使用 yaml.safe_load。不执行真实抓取。"""
import json, subprocess, zipfile, yaml
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
now = datetime.now(CST).isoformat()
now_str = datetime.now(CST).strftime('%Y%m%d_%H%M%S')

A = Path('E:/RAG/A')
project = Path('.')

# ── 读取 YAML ──
reg_path = project / 'data/enterprise_kb_v1/source_registry/source_registry.yaml'
allowlist_path = project / 'data/enterprise_kb_v1/source_registry/official_docs_allowlist.yaml'

with open(reg_path, encoding='utf-8') as f:
    registry = yaml.safe_load(f)
with open(allowlist_path, encoding='utf-8') as f:
    allowlist = yaml.safe_load(f)

all_sources = registry.get('sources', [])
ext = [s for s in all_sources if s.get('source_type') == 'external_official']
verified = [s for s in ext if s.get('url_status') == 'verified']
needs_review = [s for s in ext if s.get('url_status') == 'needs_manual_review']

ext_count = len(ext)
ver_count = len(verified)
review_count = len(needs_review)
qwen_excluded = all('qwen' in s.get('source_id', '').lower() for s in needs_review)
counts_ok = (ext_count == 21 and ver_count == 19 and review_count == 2 and qwen_excluded)

# ── Manifest entries: 每条的 planned_output_dir / capture_eligible ──
manifest_entries = []
for s in verified:
    sid = s['source_id']
    url = s.get('candidate_url') or s.get('origin_url') or ''
    domain = s.get('domain', '')
    is_qwen = 'qwen' in sid.lower()

    # text_capture.enabled (bool)
    tc = s.get('text_capture', {})
    if isinstance(tc, dict):
        tc_enabled = bool(tc.get('enabled', True))
    else:
        tc_enabled = bool(tc)

    capture_eligible = bool(not is_qwen and tc_enabled)
    exclusion_reason = ''
    if is_qwen:
        exclusion_reason = 'Qwen needs_manual_review, text_capture disabled'
    elif not tc_enabled:
        exclusion_reason = 'text_capture.enabled=false'

    # planned_output_dir — 一致指向 raw_sources
    planned_dir = f'data/enterprise_kb_v1/raw_sources/official_docs/{sid}/v1/'

    manifest_entries.append({
        'source_id': sid,
        'domain': domain,
        'origin_url': url,
        'url_status': str(s.get('url_status', '')),
        'fetch_status': str(s.get('fetch_status', 'not_fetched')),
        'enabled': bool(s.get('enabled', False)),
        'allowed_for_answer': bool(s.get('allowed_for_answer', False)),
        'text_capture_enabled': tc_enabled,
        'capture_eligible': capture_eligible,
        'exclusion_reason': exclusion_reason,
        'planned_output_dir': planned_dir,
    })

# ── 分 batch ──
domain_order = ['api_backend', 'vector_database', 'agent_orchestration', 'llm_provider']
domains = {}
for s in verified:
    d = s.get('domain', 'unknown')
    domains.setdefault(d, []).append(s)

batches = []
current_batch = []
batch_size = 5
for domain in domain_order:
    for s in domains.get(domain, []):
        current_batch.append(s)
        if len(current_batch) >= batch_size:
            batches.append(list(current_batch))
            current_batch = []
if current_batch:
    batches.append(current_batch)

# 分配 batch 编号
sid_to_batch = {}
for bi, batch in enumerate(batches):
    for s in batch:
        sid_to_batch[s['source_id']] = bi + 1
for e in manifest_entries:
    e['batch'] = sid_to_batch.get(e['source_id'], None)

# ── 失败处理策略 ──
failure_strategies = {
    'page_inaccessible': 'fetch_status=failed, url_status=inaccessible, skip this source',
    'topic_mismatch': 'manual review, doc_status=topic_mismatch',
    'empty_content': 'raw.html < 500 bytes or normalized.md < 100 chars -> quality=fail',
    'table_loss': 'extraction_warning, do not block batch',
    'code_block_loss': 'extraction_warning, do not block batch',
    'dynamic_content_missing': 'retry with MCP Playwright, if still fail -> fetch_status=js_required',
    'url_redirect_abnormal': 'record final_url, if domain change > 1 -> manual review',
}

# ── Git 检查 ──
def run_git(args):
    r = subprocess.run(['git'] + args, capture_output=True, text=True, cwd=str(project))
    return r.returncode, r.stdout.strip(), r.stderr.strip()

rc, out_reg, _ = run_git(['status', '--short', '--',
    'data/enterprise_kb_v1/source_registry/source_registry.yaml',
    'data/enterprise_kb_v1/source_registry/official_docs_allowlist.yaml'])
registry_clean = not bool(out_reg.strip())

_, out_exp, _ = run_git(['status', '--short', '--', 'data/enterprise_kb_v1/experiments/'])
experiments_clean = not bool(out_exp.strip())

_, out_stg, _ = run_git(['diff', '--cached', '--name-only'])
staged_empty = not bool(out_stg.strip())

# ── 完整 forbidden artifacts 检查 ──
def count_glob(pattern):
    return len([x for x in project.rglob(pattern) if '.git' not in str(x) and '__pycache__' not in str(x)])

forbidden = {
    'chroma_persist_dir': (project / 'storage/chroma_enterprise_kb_v1').exists(),
    'faiss_files': count_glob('*.faiss'),
    'index_files': count_glob('*.index'),
    'pkl_files': count_glob('*.pkl'),
    'bin_files': count_glob('*.bin'),
    'parquet_files': count_glob('*.parquet'),
    'h5_files': count_glob('*.h5'),
    'pt_files': count_glob('*.pt'),
    'onnx_files': count_glob('*.onnx'),
}
any_forbidden = forbidden['chroma_persist_dir'] or sum(
    v for k, v in forbidden.items() if k != 'chroma_persist_dir') > 0

forbidden_lines = [
    '# Phase 3G forbidden artifacts check',
    '# timestamp: ' + now,
]
for k, v in forbidden.items():
    forbidden_lines.append(k + ': ' + str(v))
forbidden_lines.append('any_forbidden: ' + str(any_forbidden))
forbidden_lines.append('conclusion: ' + ('no forbidden artifacts' if not any_forbidden else 'FORBIDDEN_ARTIFACTS_FOUND'))
(A / 'phase3g_forbidden_artifacts_check.txt').write_text('\n'.join(forbidden_lines), encoding='utf-8')

# ── Git evidence ──
(A / 'phase3g_git_status_registry_allowlist.txt').write_text(
    '# Phase 3G git status — registry/allowlist\n# timestamp: ' + now + '\n'
    '# result: ' + (out_reg if out_reg else '(clean)') + '\n'
    '# registry_modified: ' + str(not registry_clean) + '\n', encoding='utf-8')
(A / 'phase3g_git_status_experiments.txt').write_text(
    '# Phase 3G git status — experiments\n# timestamp: ' + now + '\n'
    '# result: ' + (out_exp if out_exp else '(clean — gitignored)') + '\n'
    '# experiments_staged: ' + str(not experiments_clean) + '\n', encoding='utf-8')
(A / 'phase3g_git_diff_cached_names.txt').write_text(
    '# Phase 3G git diff cached\n# timestamp: ' + now + '\n'
    '# result: ' + (out_stg if out_stg else '(empty)') + '\n'
    '# has_staged_files: ' + str(not staged_empty) + '\n', encoding='utf-8')

# ── Inventory ──
inv = [
    '# Phase 3G Evidence Inventory',
    '# timestamp: ' + now,
    '# note: dry-run plan only — no raw.html/normalized.md generated',
    '#',
    '# source_registry.yaml: EXISTS (' + str(reg_path.stat().st_size) + ' bytes)',
    '# official_docs_allowlist.yaml: EXISTS (' + str(allowlist_path.stat().st_size) + ' bytes)',
    '# external_official: ' + str(ext_count) + ' (expected 21)',
    '# verified: ' + str(ver_count) + ' (expected 19)',
    '# needs_manual_review: ' + str(review_count) + ' (expected 2, both Qwen)',
    '# counts_ok: ' + str(counts_ok),
    '# qwen_excluded: ' + str(qwen_excluded),
    '# batches: ' + str(len(batches)),
    '#',
]
for bi, batch in enumerate(batches):
    inv.append('# Batch ' + str(bi+1) + ' (' + str(len(batch)) + ' sources):')
    for s in batch:
        inv.append('#   ' + s['source_id'])
inv.append('#')
inv.append('# forbidden artifacts:')
for k, v in forbidden.items():
    inv.append('#   ' + k + ': ' + str(v))
(A / 'phase3g_evidence_inventory.txt').write_text('\n'.join(inv), encoding='utf-8')

# ── Dry-run manifest ──
manifest = {
    'phase': '3G',
    'timestamp': now,
    'type': 'dry_run_plan',
    'not_real_capture': True,
    'counts': {
        'external_official_total': ext_count,
        'verified': ver_count,
        'needs_manual_review': review_count,
        'qwen_excluded': qwen_excluded,
        'counts_ok': counts_ok,
    },
    'batches': [{'batch_id': i+1, 'source_count': len(b), 'sources': [s['source_id'] for s in b]} for i, b in enumerate(batches)],
    'entries': manifest_entries,
    'batch_strategy': {
        'max_per_batch': 5,
        'stop_on_failure': True,
        'per_batch_artifacts': ['audit.json', 'manifest.yaml', 'report.md'],
    },
    'quality_gates': ['G0 file existence', 'G1 content quality', 'G2 structure integrity', 'G3 format', 'G4 specific checks'],
    'failure_strategies': failure_strategies,
    'planned_output_base': 'data/enterprise_kb_v1/raw_sources/official_docs/{source_id}/v1/',
    'git_checks': {
        'registry_clean': registry_clean,
        'staged_empty': staged_empty,
        'any_forbidden': any_forbidden,
    },
    'forbidden_artifacts': forbidden,
}
with open(A / 'phase3g_dry_run_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

# ── ZIP ──
zip_name = A / ('enterprise_kb_v1_phase3g_verified_sources_text_dom_capture_plan_' + now_str + '.zip')
with zipfile.ZipFile(str(zip_name), 'w', zipfile.ZIP_DEFLATED) as zf:
    for arc, src in [
        ('docs/enterprise_kb_v1/phase3g_verified_sources_text_dom_capture_plan.md',
         project / 'docs/enterprise_kb_v1/phase3g_verified_sources_text_dom_capture_plan.md'),
        ('docs/enterprise_kb_v1/text_dom_capture_quality_gate.md',
         project / 'docs/enterprise_kb_v1/text_dom_capture_quality_gate.md'),
        ('scripts/enterprise_kb_v1/plan_verified_text_dom_capture.py',
         project / 'scripts/enterprise_kb_v1/plan_verified_text_dom_capture.py'),
        ('phase3g_verified_sources_text_dom_capture_report.md',
         A / 'phase3g_verified_sources_text_dom_capture_report.md'),
        ('phase3g_dry_run_manifest.json', A / 'phase3g_dry_run_manifest.json'),
        ('phase3g_evidence_inventory.txt', A / 'phase3g_evidence_inventory.txt'),
    ]:
        if src.exists():
            zf.write(str(src), arcname=arc)
    for fn in ['phase3g_git_status_registry_allowlist.txt', 'phase3g_git_status_experiments.txt',
               'phase3g_git_diff_cached_names.txt', 'phase3g_forbidden_artifacts_check.txt']:
        zf.write(str(A / fn), arcname=fn)

with zipfile.ZipFile(str(zip_name), 'r') as zf:
    n = zf.namelist()
print('ZIP: ' + zip_name.name + ' | ' + str(len(n)) + ' entries | ' + str(int(zip_name.stat().st_size / 1024)) + ' KB')
print('Counts: ext=' + str(ext_count) + ' verified=' + str(ver_count) + ' review=' + str(review_count))
print('qwen_excluded=' + str(qwen_excluded) + ' | counts_ok=' + str(counts_ok))
print('Batches: ' + str(len(batches)))
print('Forbidden: ' + str(any_forbidden))
print('OK')
