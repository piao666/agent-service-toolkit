#!/usr/bin/env python3
"""Phase 3F: 生成 manifest + git evidence + inventory + ZIP。纯决策，不执行采集。"""
import json, subprocess, zipfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
now = datetime.now(CST).isoformat()
now_str = datetime.now(CST).strftime('%Y%m%d_%H%M%S')
A = Path('E:/RAG/A')
project = Path('.')

def run_git(args):
    r = subprocess.run(['git'] + args, capture_output=True, text=True, cwd=str(project))
    return r.returncode, r.stdout.strip(), r.stderr.strip()

# Git checks
rc, out_reg, _ = run_git(['status', '--short', '--',
    'data/enterprise_kb_v1/source_registry/source_registry.yaml',
    'data/enterprise_kb_v1/source_registry/official_docs_allowlist.yaml'])
registry_clean = not bool(out_reg.strip())

rc, out_exp, _ = run_git(['status', '--short', '--', 'data/enterprise_kb_v1/experiments/'])
experiments_clean = not bool(out_exp.strip())

rc, out_stg, _ = run_git(['diff', '--cached', '--name-only'])
staged_empty = not bool(out_stg.strip())

chroma_dir = project / 'storage/chroma_enterprise_kb_v1'
chroma_exists = chroma_dir.exists()
faiss = [x for x in project.rglob('*.faiss') if '.git' not in str(x)]
idx = [x for x in project.rglob('*.index') if '.git' not in str(x)]
no_index = not chroma_exists and len(faiss) == 0 and len(idx) == 0

# Write git evidence
def write_evidence(filename, lines):
    (A / filename).write_text('\n'.join(lines), encoding='utf-8')

write_evidence('phase3f_git_status_registry_allowlist.txt', [
    '# Phase 3F git status — registry/allowlist',
    '# timestamp: ' + now,
    '# result: ' + (out_reg if out_reg else '(clean)'),
    '# registry_modified: ' + str(not registry_clean),
    '# allowlist_modified: ' + str(not registry_clean),
])

write_evidence('phase3f_git_status_experiments.txt', [
    '# Phase 3F git status — experiments',
    '# timestamp: ' + now,
    '# result: ' + (out_exp if out_exp else '(clean — gitignored)'),
    '# experiments_staged: ' + str(not experiments_clean),
])

write_evidence('phase3f_git_diff_cached_names.txt', [
    '# Phase 3F git diff cached',
    '# timestamp: ' + now,
    '# result: ' + (out_stg if out_stg else '(empty)'),
    '# has_staged_files: ' + str(not staged_empty),
])

write_evidence('phase3f_forbidden_artifacts_check.txt', [
    '# Phase 3F forbidden artifacts check',
    '# timestamp: ' + now,
    'chroma_persist_dir_exists: ' + str(chroma_exists),
    'faiss_files: ' + str(len(faiss)),
    'index_files: ' + str(len(idx)),
    'chroma_or_index_created: ' + str(not no_index),
    'conclusion: ' + ('no forbidden artifacts' if no_index else 'FORBIDDEN'),
])

# Inventory
inv = [
    '# Phase 3F Evidence Inventory',
    '# timestamp: ' + now,
    '# note: Phase 3F is strategy decision only — no scraping/screenshots/indexing',
    '#',
    '# Input evidence (from prior phases):',
]
for label, p in [
    ('audit.json (3E1-A)', 'data/enterprise_kb_v1/manifests/phase3e1_text_dom_audit.json'),
    ('results.json (3E1-B1)', 'data/enterprise_kb_v1/experiments/phase3d_multimodal/visual/phase3e1b1_results.json'),
    ('comparison manifest (3E1-C)', 'E:/RAG/A/phase3e1c_review_manifest.json'),
]:
    fp = Path(p)
    inv.append('  ' + label + ': ' + ('EXISTS' if fp.exists() else 'MISSING') + ' (' + str(fp.stat().st_size if fp.exists() else 0) + ' bytes)')

inv.append('#')
inv.append('# Phase 3F output docs:')
for label, p in [
    ('strategy decision', 'docs/enterprise_kb_v1/phase3f_formal_ingestion_strategy_decision.md'),
    ('visual sidecar policy', 'docs/enterprise_kb_v1/visual_sidecar_policy.md'),
    ('decision report', 'E:/RAG/A/phase3f_formal_ingestion_strategy_decision_report.md'),
]:
    fp = Path(p)
    inv.append('  ' + label + ': ' + ('EXISTS' if fp.exists() else 'MISSING') + ' (' + str(fp.stat().st_size if fp.exists() else 0) + ' bytes)')

inv.append('#')
inv.append('# Git evidence:')
for fn in ['phase3f_git_status_registry_allowlist.txt', 'phase3f_git_status_experiments.txt',
           'phase3f_git_diff_cached_names.txt', 'phase3f_forbidden_artifacts_check.txt']:
    fp = A / fn
    inv.append('  ' + fn + ': ' + ('EXISTS' if fp.exists() else 'MISSING'))

(A / 'phase3f_evidence_inventory.txt').write_text('\n'.join(inv), encoding='utf-8')

# Manifest
manifest = {
    'phase': '3F',
    'timestamp': now,
    'type': 'strategy_decision',
    'not_formal_ingestion': True,
    'decisions': {
        'primary_channel': 'text_dom',
        'visual_sidecar': 'keep_as_evidence_not_retrieval',
        'visual_embedding': 'deferred',
        'next_phase': '3G — 19 source Text/DOM dry-run plan',
        'screenshot_criteria': {
            'needed': ['long_page_md_gt_20kb', 'headings_gt_20', 'tables_ge_2', 'code_gt_10_with_tabs', 'complex_layout'],
            'not_needed': ['short_page_md_lt_10kb', 'text_dom_sufficient'],
        },
    },
    'git_checks': {
        'git_available': rc == 0,
        'registry_clean': registry_clean,
        'allowlist_clean': registry_clean,
        'experiments_staged': not experiments_clean,
        'staged_files': not staged_empty,
        'chroma_or_index': not no_index,
    },
    'key_findings': {
        'S1': 'visual_sidecar_value=low — text_dom sufficient',
        'S2': 'visual_sidecar_value=medium — visual complementary',
        'S3': 'visual_sidecar_value=high — long page structure key value',
    },
    'evidence_sufficient': True,
}
with open(A / 'phase3f_review_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

# ZIP
zip_name = A / ('enterprise_kb_v1_phase3f_strategy_decision_' + now_str + '.zip')
with zipfile.ZipFile(str(zip_name), 'w', zipfile.ZIP_DEFLATED) as zf:
    for arc, src in [
        ('docs/enterprise_kb_v1/phase3f_formal_ingestion_strategy_decision.md',
         project / 'docs/enterprise_kb_v1/phase3f_formal_ingestion_strategy_decision.md'),
        ('docs/enterprise_kb_v1/visual_sidecar_policy.md',
         project / 'docs/enterprise_kb_v1/visual_sidecar_policy.md'),
        ('phase3f_formal_ingestion_strategy_decision_report.md',
         A / 'phase3f_formal_ingestion_strategy_decision_report.md'),
        ('phase3f_review_manifest.json', A / 'phase3f_review_manifest.json'),
        ('phase3f_evidence_inventory.txt', A / 'phase3f_evidence_inventory.txt'),
    ]:
        if src.exists():
            zf.write(str(src), arcname=arc)
    for fn in ['phase3f_git_status_registry_allowlist.txt', 'phase3f_git_status_experiments.txt',
               'phase3f_git_diff_cached_names.txt', 'phase3f_forbidden_artifacts_check.txt']:
        zf.write(str(A / fn), arcname=fn)

with zipfile.ZipFile(str(zip_name), 'r') as zf:
    names = zf.namelist()
print('ZIP: ' + zip_name.name + ' | ' + str(len(names)) + ' entries | ' + str(int(zip_name.stat().st_size / 1024)) + ' KB')
print('Registry clean: ' + str(registry_clean) + ' | No index: ' + str(no_index) + ' | Staged empty: ' + str(staged_empty))
print('OK')
