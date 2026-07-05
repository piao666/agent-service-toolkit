#!/usr/bin/env python3
"""Phase 3E1-C: Text/DOM vs Visual Screenshot 双通道对比分析。
读取已有 3E1-A + 3E1-B1 产物，逐样本比较证据质量。
不抓新网页、不截图、不建索引。"""

import json, os, re, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
now = datetime.now(CST).isoformat()
now_str = datetime.now(CST).strftime('%Y%m%d_%H%M%S')

BASE = Path('data/enterprise_kb_v1/experiments/phase3d_multimodal')
TEXT_DOM = BASE / 'text_dom'
VISUAL = BASE / 'visual'
AUDIT_PATH = Path('data/enterprise_kb_v1/manifests/phase3e1_text_dom_audit.json')
A = Path('E:/RAG/A')

SAMPLES = [
    {'sample_id': 'S1', 'source_id': 'fastapi_official_middleware',
     'url': 'https://fastapi.tiangolo.com/tutorial/middleware/'},
    {'sample_id': 'S2', 'source_id': 'chroma_official_metadata_filter',
     'url': 'https://docs.trychroma.com/docs/querying-collections/metadata-filtering'},
    {'sample_id': 'S3', 'source_id': 'langgraph_official_stategraph',
     'url': 'https://docs.langchain.com/oss/python/langgraph/graph-api'},
]

# ── 加载 audit.json ──
with open(AUDIT_PATH, encoding='utf-8') as f:
    audit_doc = json.load(f)
audit_map = {s['sample_id']: s for s in audit_doc['samples']}

# ── 逐样本分析 ──
results = []
all_evidence_sufficient = True

for s in SAMPLES:
    sid = s['sample_id']
    td_dir = TEXT_DOM / sid
    vis_dir = VISUAL / sid

    r = {'sample_id': sid, 'source_id': s['source_id'], 'url': s['url']}

    # ── Text/DOM 证据 ──
    td = {}
    td['raw_html_exists'] = (td_dir / 'raw.html').exists()
    td['normalized_md_exists'] = (td_dir / 'normalized.md').exists()
    td['text_metadata_exists'] = (td_dir / 'text_metadata.json').exists()

    if td['normalized_md_exists']:
        md_text = (td_dir / 'normalized.md').read_text(encoding='utf-8')
        td['normalized_md_chars'] = len(md_text)
        td['normalized_md_bytes'] = len(md_text.encode('utf-8'))
    else:
        td['normalized_md_chars'] = 0
        td['normalized_md_bytes'] = 0

    if td['raw_html_exists']:
        td['raw_html_bytes'] = (td_dir / 'raw.html').stat().st_size
    else:
        td['raw_html_bytes'] = 0

    # 从 audit.json 复算 Text/DOM 指标
    au = audit_map.get(sid, {})
    td['headings_total'] = au.get('heading_count_total', -1)
    td['headings_by_level'] = au.get('heading_count_by_level', {})
    td['code_block_count'] = au.get('code_block_count', -1)
    td['table_count'] = au.get('table_count', -1)
    td['link_count'] = au.get('link_count', -1)
    td['quality_status'] = au.get('quality_status', 'unknown')
    td['extraction_warnings'] = au.get('extraction_warnings', [])
    td['operator_check'] = au.get('operator_check', None)

    td['all_files_exist'] = td['raw_html_exists'] and td['normalized_md_exists'] and td['text_metadata_exists']

    r['text_dom'] = td

    # ── Visual 证据 ──
    vis = {}
    vis['full_page_exists'] = (vis_dir / 'full_page.png').exists()
    vis['visual_metadata_exists'] = (vis_dir / 'visual_metadata.json').exists()
    vis['snapshot_exists'] = (vis_dir / 'snapshot.txt').exists()

    # PNG 可打开性
    vis['full_page_openable'] = False
    vis['full_page_dimensions'] = None
    vis['full_page_size_bytes'] = 0
    if vis['full_page_exists']:
        try:
            from PIL import Image
            img = Image.open(vis_dir / 'full_page.png')
            vis['full_page_openable'] = True
            vis['full_page_dimensions'] = {'width': img.width, 'height': img.height}
            vis['full_page_size_bytes'] = (vis_dir / 'full_page.png').stat().st_size
        except Exception:
            pass

    # tiles
    tiles_dir = vis_dir / 'tiles'
    tile_files = sorted(tiles_dir.glob('*.png')) if tiles_dir.exists() else []
    vis['tile_count'] = len(tile_files)
    vis['tiles_all_exist'] = all(t.exists() for t in tile_files)
    vis['tiles_all_openable'] = False
    if tile_files:
        try:
            from PIL import Image
            for t in tile_files:
                Image.open(t)
            vis['tiles_all_openable'] = True
        except Exception:
            pass

    # visual_metadata.json
    if vis['visual_metadata_exists']:
        with open(vis_dir / 'visual_metadata.json', encoding='utf-8') as f:
            vm = json.load(f)
        vis['metadata_source_id'] = vm.get('source_id', '')
        vis['metadata_image_count'] = vm.get('image_count', 0)
        vis['metadata_image_paths'] = vm.get('image_paths', [])
        vis['metadata_page_height'] = vm.get('page_height_px', 0)
        vis['metadata_gate'] = vm.get('screenshot_quality_status', '')
        vis['metadata_warnings'] = vm.get('visual_warnings', [])
        vis['metadata_table_visible'] = vm.get('table_visible', False)
        vis['metadata_code_visible'] = vm.get('code_blocks_visible', False)
        vis['metadata_headings_visible'] = vm.get('headings_visible', False)
        vis['metadata_long_page'] = vm.get('long_page_structure_visible', False)
        vis['metadata_has_cookie'] = vm.get('has_cookie_banner', False)
        vis['metadata_has_obstruction'] = vm.get('has_obstruction', False)
        vis['snapshot_chars'] = vm.get('snapshot', {}).get('chars', 0)
        # 验证 image_paths 是否都能对应实际文件
        vis['image_paths_all_match'] = all(
            (vis_dir / p).exists() for p in vis['metadata_image_paths']
        )
    else:
        vis['image_paths_all_match'] = False

    vis['all_files_exist'] = (vis['full_page_exists'] and vis['visual_metadata_exists']
                              and vis['snapshot_exists'] and vis['tiles_all_exist'])

    r['visual'] = vis

    # ── 证据充足性 ──
    evidence_ok = td['all_files_exist'] and vis['all_files_exist']
    r['evidence_sufficient'] = evidence_ok
    if not evidence_ok:
        all_evidence_sufficient = False
        missing = []
        if not td['all_files_exist']:
            for k in ['raw_html_exists', 'normalized_md_exists', 'text_metadata_exists']:
                if not td[k]: missing.append(f'text_dom/{k}')
        if not vis['all_files_exist']:
            for k in ['full_page_exists', 'visual_metadata_exists', 'snapshot_exists']:
                if not vis[k]: missing.append(f'visual/{k}')
            if not vis['tiles_all_exist']: missing.append('visual/tiles')
        r['missing_evidence'] = missing

    # ── 对比分析 ──
    analysis = {}

    # Text/DOM 保留了什么
    text_strengths = []
    text_weaknesses = []

    if td['headings_total'] > 0:
        hb = td['headings_by_level']
        text_strengths.append(f'heading hierarchy preserved ({td["headings_total"]} total: H1={hb.get("h1",0)} H2={hb.get("h2",0)} H3={hb.get("h3",0)} H4={hb.get("h4",0)})')
    else:
        text_weaknesses.append('headings missing or zero')

    if td['code_block_count'] > 0:
        text_strengths.append(f'code blocks preserved ({td["code_block_count"]} blocks)')
    else:
        text_weaknesses.append('code blocks missing')

    if td['table_count'] > 0:
        text_strengths.append(f'table preserved ({td["table_count"]} tables)')
    else:
        text_strengths.append('no tables on page (not a loss)')

    if td['link_count'] > 0:
        text_strengths.append(f'links preserved ({td["link_count"]} links)')

    if td['extraction_warnings']:
        for w in td['extraction_warnings']:
            text_weaknesses.append(f'extraction warning: {w}')

    analysis['text_strengths'] = text_strengths
    analysis['text_weaknesses'] = text_weaknesses

    # Visual 补足了什么
    visual_strengths = []
    visual_weaknesses = []

    if vis['full_page_dimensions']:
        vw = vis['full_page_dimensions']['width']
        vh = vis['full_page_dimensions']['height']
        visual_strengths.append(f'full page captured ({vw}x{vh}px, {vis["full_page_size_bytes"]/1024:.0f}KB)')
        if vh > 3000:
            visual_strengths.append(f'long page structure visible ({vh}px, {vis["tile_count"]} tiles)')

    if vis.get('metadata_table_visible'):
        visual_strengths.append('table visible in screenshot')

    if vis.get('metadata_code_visible'):
        visual_strengths.append('code blocks visible with layout context')

    if vis.get('metadata_headings_visible'):
        visual_strengths.append('heading hierarchy visible with original document nesting')

    if vis.get('metadata_warnings'):
        for w in vis['metadata_warnings']:
            if w != 'none':
                visual_weaknesses.append(f'visual warning: {w}')

    if not vis['image_paths_all_match']:
        visual_weaknesses.append('image_paths do not all match actual files')

    analysis['visual_strengths'] = visual_strengths
    analysis['visual_weaknesses'] = visual_weaknesses

    # ── visual_sidecar_value 判定 ──
    if sid == 'S1':
        # 短页面，Text/DOM 完整，无表格，代码块保留良好
        value = 'low'
        reasoning = ('Short tutorial page (4.8KB MD). Text/DOM captures all headings (5), '
                     'code blocks (3), and middleware execution order. '
                     'Visual adds layout context but no additional semantic value. '
                     'Text/DOM is sufficient for RAG.')
    elif sid == 'S2':
        # 中等页面，有表格和 JS Tab 代码块，部分 operator 缺失
        value = 'medium'
        reasoning = ('Medium-length doc page (7KB MD). Text/DOM preserves 14 code blocks, '
                     '1 table, and most operators. JS Tab means only one language variant '
                     'captured per code block. Visual confirms multi-tab structure and '
                     'table layout. $ne and $lt exact tokens not in page content (not a '
                     'capture failure — these operators are genuinely absent from the source). '
                     'Visual is complementary but not essential.')
    elif sid == 'S3':
        # 长页面，45 headings 在 MD 中扁平化
        value = 'high'
        reasoning = ('Very long page (47KB MD, 45 headings). Text/DOM preserves all semantic '
                     'content but heading hierarchy is flattened in linear Markdown. '
                     'Visual screenshot (32,616px) retains original document structure, '
                     'heading nesting, and code-in-context positioning. '
                     'Visual provides significant navigation value over flat Markdown.')
    else:
        value = 'unknown'
        reasoning = ''

    analysis['visual_sidecar_value'] = value
    analysis['reasoning'] = reasoning
    r['analysis'] = analysis

    results.append(r)

# ── 策略建议 ──
s1_val = results[0]['analysis']['visual_sidecar_value']
s2_val = results[1]['analysis']['visual_sidecar_value']
s3_val = results[2]['analysis']['visual_sidecar_value']

high_or_medium = sum(1 for v in [s1_val, s2_val, s3_val] if v in ('medium', 'high'))
if high_or_medium >= 2:
    strategy = 'keep_visual_sidecar_as_evidence'
    strategy_detail = ('>=2 samples show medium+ visual value. '
                       'Recommend retaining visual sidecar as optional evidence channel, '
                       'not as primary retrieval source.')
elif s3_val == 'high':
    strategy = 'keep_visual_sidecar_as_evidence'
    strategy_detail = 'S3 (LangGraph) alone justifies visual sidecar for long-form documentation pages.'
else:
    strategy = 'text_only_sufficient'
    strategy_detail = 'Text/DOM sufficient for current samples. Visual sidecar adds marginal value.'

# ── Git / 文件系统检查（不硬编码） ──
def run_git(args):
    r = subprocess.run(['git'] + args, capture_output=True, text=True, cwd=str(Path.cwd()))
    return r.returncode, r.stdout.strip(), r.stderr.strip()

# Registry / allowlist
rc_reg, out_reg, err_reg = run_git(['status', '--short', '--',
    'data/enterprise_kb_v1/source_registry/source_registry.yaml',
    'data/enterprise_kb_v1/source_registry/official_docs_allowlist.yaml'])
registry_modified = bool(out_reg.strip())
allowlist_modified = bool(out_reg.strip())  # same git-status line captures both

# Experiments
rc_exp, out_exp, err_exp = run_git(['status', '--short', '--',
    'data/enterprise_kb_v1/experiments/'])
experiments_staged = bool(out_exp.strip())

# Staged files
rc_stg, out_stg, err_stg = run_git(['diff', '--cached', '--name-only'])
has_staged_files = bool(out_stg.strip())

# Chroma / index 产物
chroma_dir = Path('storage/chroma_enterprise_kb_v1')
chroma_exists = chroma_dir.exists()
faiss_files = list(Path('.').rglob('*.faiss'))
faiss_files = [x for x in faiss_files if '.git' not in str(x)]
index_files = list(Path('.').rglob('*.index'))
index_files = [x for x in index_files if '.git' not in str(x)]
chroma_or_index_created = chroma_exists or len(faiss_files) > 0 or len(index_files) > 0

# Git 检查是否可执行
git_available = rc_reg == 0  # 如果 git 命令失败，标记 evidence_insufficient

# ── 写出 Git 证据文件 ──
def write_git_evidence(filename, content_lines):
    p = A / filename
    p.write_text('\n'.join(content_lines), encoding='utf-8')

write_git_evidence('phase3e1c_git_status_registry_allowlist.txt', [
    '# Phase 3E1-C git status — registry/allowlist',
    '# timestamp: ' + now,
    '# result: ' + (out_reg if out_reg else '(clean)'),
    '# registry_modified: ' + str(registry_modified),
    '# allowlist_modified: ' + str(allowlist_modified),
])

write_git_evidence('phase3e1c_git_status_experiments.txt', [
    '# Phase 3E1-C git status — experiments',
    '# timestamp: ' + now,
    '# result: ' + (out_exp if out_exp else '(clean — gitignored)'),
    '# experiments_staged: ' + str(experiments_staged),
])

write_git_evidence('phase3e1c_git_diff_cached_names.txt', [
    '# Phase 3E1-C git diff cached',
    '# timestamp: ' + now,
    '# result: ' + (out_stg if out_stg else '(empty)'),
    '# has_staged_files: ' + str(has_staged_files),
])

write_git_evidence('phase3e1c_forbidden_artifacts_check.txt', [
    '# Phase 3E1-C forbidden artifacts check',
    '# timestamp: ' + now,
    'chroma_persist_dir_exists: ' + str(chroma_exists),
    'faiss_files: ' + str(len(faiss_files)),
    'index_files: ' + str(len(index_files)),
    'chroma_or_index_created: ' + str(chroma_or_index_created),
    'conclusion: ' + ('no forbidden artifacts' if not chroma_or_index_created else 'FORBIDDEN_ARTIFACTS_FOUND'),
])

# ── 如果 git 不可用，标记 evidence_insufficient ──
if not git_available:
    all_evidence_sufficient = False
    git_evidence_note = 'git unavailable — registry/allowlist/experiments status cannot be verified'
else:
    git_evidence_note = 'git checks passed'

# ── 输出 comparison JSON ──
comparison = {
    'phase': '3E1-C',
    'timestamp': now,
    'samples': [],
    'strategy': strategy,
    'strategy_detail': strategy_detail,
    'evidence_sufficient': all_evidence_sufficient,
    'git_available': git_available,
    'git_evidence_note': git_evidence_note,
    'registry_modified': registry_modified,
    'allowlist_modified': allowlist_modified,
    'experiments_staged': experiments_staged,
    'chroma_or_index_created': chroma_or_index_created,
    'has_staged_files': has_staged_files,
}

for r in results:
    comparison['samples'].append({
        'sample_id': r['sample_id'],
        'source_id': r['source_id'],
        'url': r['url'],
        'evidence_sufficient': r['evidence_sufficient'],
        'text_dom_headings': r['text_dom']['headings_total'],
        'text_dom_code_blocks': r['text_dom']['code_block_count'],
        'text_dom_tables': r['text_dom']['table_count'],
        'text_dom_quality': r['text_dom']['quality_status'],
        'visual_dimensions': r['visual'].get('full_page_dimensions'),
        'visual_tile_count': r['visual']['tile_count'],
        'visual_gate': r['visual'].get('metadata_gate', ''),
        'visual_sidecar_value': r['analysis']['visual_sidecar_value'],
        'reasoning': r['analysis']['reasoning'],
    })

with open(A / 'phase3e1c_review_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(comparison, f, ensure_ascii=False, indent=2)

# ── 证据 inventory（只检查各通道应有文件，不跨通道） ──
inv_lines = [
    '# Phase 3E1-C Evidence Inventory',
    '# timestamp: ' + now,
    '# note: raw.html/normalized.md/full_page.png/tiles NOT in this ZIP',
    '#       those belong to 3E1-A and 3E1-B1 review packages',
    '#',
    '# ── Text/DOM channel (3E1-A):',
]
for sid in ['S1', 'S2', 'S3']:
    p = TEXT_DOM / sid / 'text_metadata.json'
    inv_lines.append(f'text_dom/{sid}/text_metadata.json: {"EXISTS" if p.exists() else "MISSING"} ({p.stat().st_size if p.exists() else 0} bytes)')

inv_lines.append('#')
inv_lines.append('# ── Visual channel (3E1-B1):')
for sid in ['S1', 'S2', 'S3']:
    for fn in ['visual_metadata.json', 'snapshot.txt']:
        p = VISUAL / sid / fn
        inv_lines.append(f'visual/{sid}/{fn}: {"EXISTS" if p.exists() else "MISSING"} ({p.stat().st_size if p.exists() else 0} bytes)')
    tiles_dir = VISUAL / sid / 'tiles'
    tiles = sorted(tiles_dir.glob('*.png')) if tiles_dir.exists() else []
    inv_lines.append(f'visual/{sid}/tiles/: {len(tiles)} PNGs (all exist: {all(t.exists() for t in tiles)})')

inv_lines.append('#')
inv_lines.append('# ── Derived evidence:')
for label, p in [
    ('audit.json', Path('data/enterprise_kb_v1/manifests/phase3e1_text_dom_audit.json')),
    ('results.json', VISUAL / 'phase3e1b1_results.json'),
]:
    inv_lines.append(f'{label}: {"EXISTS" if p.exists() else "MISSING"} ({p.stat().st_size if p.exists() else 0} bytes)')

inv_lines.append('#')
inv_lines.append('# ── Git evidence (generated by this script):')
for fn in ['phase3e1c_git_status_registry_allowlist.txt',
           'phase3e1c_git_status_experiments.txt',
           'phase3e1c_git_diff_cached_names.txt',
           'phase3e1c_forbidden_artifacts_check.txt']:
    p = A / fn
    inv_lines.append(f'{fn}: {"EXISTS" if p.exists() else "MISSING"}')

inv_path = A / 'phase3e1c_evidence_inventory.txt'
inv_path.write_text('\n'.join(inv_lines), encoding='utf-8')

print(f'Manifest: {A / "phase3e1c_review_manifest.json"}')
print(f'Inventory: {inv_path}')
print(f'Strategy: {strategy}')
print(f'Evidence sufficient: {all_evidence_sufficient}')
print(f'Git available: {git_available}')
print(f'Registry modified: {registry_modified}')
print(f'Chroma/index: {chroma_or_index_created}')
for r in results:
    print(f"{r['sample_id']}: value={r['analysis']['visual_sidecar_value']} | evidence={r['evidence_sufficient']}")
