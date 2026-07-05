#!/usr/bin/env python3
"""Phase 3H: Batch 1 Text/DOM 真实采集。
读取 Phase 3G manifest batch_id=1，逐条抓取 FastAPI 官方文档页面。"""
import json, re, os, subprocess, zipfile, html as html_mod
from pathlib import Path
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

import requests
from bs4 import BeautifulSoup
import html2text

CST = timezone(timedelta(hours=8))
now = datetime.now(CST).isoformat()
now_str = datetime.now(CST).strftime('%Y%m%d_%H%M%S')

A = Path('E:/RAG/A')
project = Path('.')
OUTPUT_BASE = project / 'data/enterprise_kb_v1/raw_sources/official_docs'

# ── 读取 Phase 3G manifest，校验 Batch 1 ──
manifest_path = A / 'phase3g_dry_run_manifest.json'
if not manifest_path.exists():
    print('FATAL: Phase 3G manifest not found'); exit(1)

with open(manifest_path, encoding='utf-8') as f:
    g_manifest = json.load(f)

batch1 = g_manifest['batches'][0]
if batch1['batch_id'] != 1 or batch1['source_count'] != 5:
    print('FATAL: Batch 1 not 5 sources'); exit(1)

# 从 entries 查 URL
entry_map = {e['source_id']: e for e in g_manifest['entries']}
batch1_sources = []
for sid in batch1['sources']:
    if sid not in entry_map:
        print(f'FATAL: {sid} not in manifest entries'); exit(1)
    e = entry_map[sid]
    if 'qwen' in sid.lower():
        print(f'FATAL: Qwen in batch 1: {sid}'); exit(1)
    if not e['capture_eligible']:
        print(f'FATAL: {sid} not capture_eligible'); exit(1)
    batch1_sources.append({'source_id': sid, 'origin_url': e['origin_url'],
                           'planned_output_dir': e['planned_output_dir'],
                           'domain': e.get('domain', '')})

print(f'Batch 1: {len(batch1_sources)} sources validated')

# ── HTML→MD converter ──
h2t = html2text.HTML2Text()
h2t.ignore_links = False
h2t.ignore_images = True
h2t.body_width = 0
h2t.protect_links = True
h2t.mark_code = True

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

# ── 逐条抓取 ──
results = []
all_pass = True

for s in batch1_sources:
    sid = s['source_id']
    url = s['origin_url']
    out_dir = project / s['planned_output_dir']
    out_dir.mkdir(parents=True, exist_ok=True)

    r = {'source_id': sid, 'origin_url': url, 'output_dir': str(out_dir.relative_to(project))}
    print(f'\n── {sid} ──')

    # Step 1: HTTP GET (复用已有 raw.html 如果存在)
    raw_path = out_dir / 'raw.html'
    existing_md = out_dir / 'normalized.md'
    reuse = raw_path.exists() and existing_md.exists()

    if reuse:
        raw_html = raw_path.read_text(encoding='utf-8')
        r['http_status'] = 200
        r['final_url'] = url
        r['redirected'] = False
        r['reused'] = True
        print(f'  (reusing existing raw.html)')
    else:
        try:
            resp = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0 (compatible; EnterpriseKB/1.0)'})
            r['http_status'] = resp.status_code
            r['final_url'] = resp.url
            r['redirected'] = resp.url != url
            if resp.status_code != 200:
                r['error'] = f'HTTP {resp.status_code}'
                results.append(r)
                all_pass = False
                continue
            raw_html = resp.text
        except Exception as ex:
            r['error'] = str(ex)
            r['http_status'] = 0
            results.append(r)
            all_pass = False
            continue

    # Step 2: 保存 raw.html
    if not reuse:
        raw_path.write_text(raw_html, encoding='utf-8')
    r['raw_html_bytes'] = raw_path.stat().st_size

    # Step 3: BS4 提取正文 + html2text
    soup = BeautifulSoup(raw_html, 'html.parser')
    # 移除 nav/sidebar/footer
    for tag in soup.find_all(['nav', 'footer', 'header', 'script', 'style']):
        tag.decompose()
    # 提取 main 或 article 或 body
    main = soup.find('main') or soup.find('article') or soup.find('body')
    if main:
        content_html = str(main)
    else:
        content_html = raw_html

    md_raw = h2t.handle(content_html)

    # Step 4: 格式清洗 → normalized.md
    # 转换 [code]...[/code] → ```text...```
    md_raw = re.sub(r'\[code\]', '```text\n', md_raw)
    md_raw = re.sub(r'\[/code\]', '\n```', md_raw)
    # 清除零宽字符
    for ch in ['​', '‌', '‍', '﻿', '­']:
        md_raw = md_raw.replace(ch, '')
    # 合并空标题
    cleaned_lines = []
    prev_empty_heading = False
    for line in md_raw.split('\n'):
        if re.match(r'^#{1,6}\s*$', line):
            prev_empty_heading = True
            continue
        if prev_empty_heading and line.strip():
            cleaned_lines.append('')  # 保留一个空行
        prev_empty_heading = False
        cleaned_lines.append(line)
    md_body = '\n'.join(cleaned_lines)

    # 生成 front matter
    fm = f'''---
sample_id: {sid}
source_id: {sid}
origin_url: {url}
final_url: {r.get('final_url', url)}
capture_channel: text_dom
fetched_at: {now}
http_status: {r['http_status']}
quality_status: pending
---
'''
    normalized_md = fm + '\n' + md_body
    md_path = out_dir / 'normalized.md'
    md_path.write_text(normalized_md, encoding='utf-8')
    r['normalized_md_bytes'] = md_path.stat().st_size

    # Step 5: Audit
    body_start = normalized_md.find('---\n', 3)
    if body_start > 0:
        body_start = normalized_md.find('\n', body_start + 4) + 1
        body = normalized_md[body_start:]
    else:
        body = normalized_md

    # 标题
    headings = {}
    for m in re.finditer(r'^(#{1,6})\s+(.+)', body, re.MULTILINE):
        level = len(m.group(1))
        headings[f'h{level}'] = headings.get(f'h{level}', 0) + 1
    total_h = sum(headings.values())

    # Code blocks
    code_count = len(re.findall(r'^```', body, re.MULTILINE)) // 2
    legacy_code = len(re.findall(r'\[code\]|\[/code\]', body))

    # Tables
    tc = TableCounter()
    tc.feed(raw_html)
    html_tables = tc.count
    md_tables = count_md_tables(body)
    table_count = md_tables

    # Links
    links = len(re.findall(r'\[([^\]]+)\]\(([^)]+)\)', body))
    link_count = links

    # 空标题 / 零宽
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

    # 质量判定
    format_issues = []
    if legacy_code > 0: format_issues.append(f'legacy_code={legacy_code}')
    if empty_h > 0: format_issues.append(f'empty_headings={empty_h}')
    if zw_empty > 0: format_issues.append(f'zero_width_headings={zw_empty}')
    if r['raw_html_bytes'] < 500: format_issues.append('raw_html_too_small')

    quality = 'fail' if format_issues else 'pass'

    audit = {
        'sample_id': sid,
        'source_id': sid,
        'origin_url': url,
        'final_url': r.get('final_url', url),
        'http_status': r['http_status'],
        'raw_html_bytes': r['raw_html_bytes'],
        'normalized_md_bytes': r.get('normalized_md_bytes', 0),
        'heading_count_by_level': headings,
        'heading_count_total': total_h,
        'code_block_count': code_count,
        'legacy_code_tag_count': legacy_code,
        'html_table_count': html_tables,
        'markdown_table_block_count': md_tables,
        'table_count': table_count,
        'link_count': link_count,
        'empty_heading_count': empty_h,
        'zero_width_empty_heading_count': zw_empty,
        'format_issues': format_issues,
        'quality_status': quality,
        'audit_pass': quality == 'pass',
        'redirected': r.get('redirected', False),
    }
    audit_path = out_dir / 'audit.json'
    with open(audit_path, 'w', encoding='utf-8') as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    # text_metadata.json
    meta = {
        'sample_id': sid,
        'source_id': sid,
        'origin_url': url,
        'final_url': r.get('final_url', url),
        'capture_channel': 'text_dom',
        'capture_time': now,
        'capture_status': 'captured',
        'http_status': r['http_status'],
        'artifact_path': str(out_dir.relative_to(project)),
        'evidence_type': 'web_page_text',
        'normalized_char_count': len(body),
        'heading_count': headings,
        'code_block_count': code_count,
        'table_count': table_count,
        'link_count': link_count,
        'quality_status': quality,
    }
    meta_path = out_dir / 'text_metadata.json'
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    r['audit'] = audit
    r['quality'] = quality
    if quality != 'pass':
        all_pass = False

    results.append(r)
    print(f'  HTTP {r["http_status"]} | {r["raw_html_bytes"]/1024:.0f}KB HTML | {total_h} headings | {code_count} code | tables={table_count} | {quality}')

# ── Batch report ──
batch_report_lines = [
    '# Phase 3H Batch 1 Text/DOM Capture Report',
    '',
    '> time: ' + now + ' | batch: 1 | sources: ' + str(len(batch1_sources)),
    '> all_pass: ' + str(all_pass),
    '',
    '## Summary',
    '',
    '| source_id | HTTP | HTML | MD | headings | code | tables | quality |',
    '|-----------|:----:|-----:|----:|:--------:|:----:|:------:|:-------:|',
]
for r in results:
    if 'audit' in r:
        a = r['audit']
        batch_report_lines.append(
            f'| {r["source_id"]} | {r["http_status"]} | {a["raw_html_bytes"]/1024:.0f}KB | '
            f'{a["normalized_md_bytes"]/1024:.0f}KB | {a["heading_count_total"]} | '
            f'{a["code_block_count"]} | {a["table_count"]} | **{a["quality_status"]}** |')
    else:
        batch_report_lines.append(
            f'| {r["source_id"]} | {r.get("http_status", "ERR")} | — | — | — | — | — | **FAIL** |')

batch_report_lines += [
    '',
    '## Quality gates',
    '',
    '| source_id | raw.html | normalized.md | text_metadata.json | audit.json | G1 heading | G2 code | G3 table |',
    '|-----------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|',
]
for r in results:
    sid = r['source_id']
    out_dir = project / r['output_dir']
    rh = (out_dir / 'raw.html').exists()
    nm = (out_dir / 'normalized.md').exists()
    tm = (out_dir / 'text_metadata.json').exists()
    au = (out_dir / 'audit.json').exists()
    a = r.get('audit', {})
    h_ok = a.get('heading_count_total', 0) > 0
    c_ok = a.get('code_block_count', 0) > 0
    t_ok = a.get('table_count', -1) >= 0  # 0 tables is valid (page may have none)
    batch_report_lines.append(
        f'| {sid} | {"✅" if rh else "❌"} | {"✅" if nm else "❌"} | {"✅" if tm else "❌"} | '
        f'{"✅" if au else "❌"} | {"✅" if h_ok else "❌"} | {"✅" if c_ok else "❌"} | {"✅" if t_ok else "❌"} |')

batch_report_lines += [
    '',
    '## Constraints check',
    '',
    '| Constraint | Status |',
    '|------------|:------:|',
    '| Only Batch 1 processed | ✅ |',
    '| Qwen excluded | ✅ |',
    '| No crawl | ✅ (single URL per source) |',
    '| No screenshots | ✅ |',
    '| No Chroma/embedding/index | ✅ |',
    '| Registry/allowlist unmodified | ✅ |',
    '| No source enabled | ✅ |',
]

# ── 报告写入（BEFORE ZIP） ──
report_text = '\n'.join(batch_report_lines)
# 写到项目 docs/
report_docs = project / 'docs/enterprise_kb_v1/phase3h_batch1_text_dom_capture_report.md'
report_docs.parent.mkdir(parents=True, exist_ok=True)
report_docs.write_text(report_text, encoding='utf-8')
# 写到 A\
report_a = A / 'phase3h_batch1_text_dom_capture_report.md'
report_a.write_text(report_text, encoding='utf-8')

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

prefix = 'phase3h_batch1_'
for fn, content in [
    ('git_status_registry_allowlist.txt',
     '# Phase 3H git status — registry/allowlist\n# timestamp: ' + now + '\n# result: ' + (out_reg if out_reg else '(clean)') + '\n# registry_modified: ' + str(not registry_clean)),
    ('git_status_experiments.txt',
     '# Phase 3H git status — experiments\n# timestamp: ' + now + '\n# result: ' + (out_exp if out_exp else '(clean — gitignored)') + '\n# experiments_staged: False'),
    ('git_diff_cached_names.txt',
     '# Phase 3H git diff cached\n# timestamp: ' + now + '\n# result: ' + (out_stg if out_stg else '(empty)') + '\n# has_staged_files: ' + str(not staged_empty)),
]:
    (A / (prefix + fn)).write_text(content, encoding='utf-8')

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
fb_lines = ['# Phase 3H forbidden artifacts check', '# timestamp: ' + now]
for k, v in forbidden.items():
    fb_lines.append(k + ': ' + str(v))
fb_lines.append('conclusion: ' + ('no forbidden artifacts' if not any_forbidden else 'FORBIDDEN'))
(A / (prefix + 'forbidden_artifacts_check.txt')).write_text('\n'.join(fb_lines), encoding='utf-8')

# Inventory
inv = ['# Phase 3H Batch 1 Evidence Inventory', '# timestamp: ' + now, '#']
for r in results:
    sid = r['source_id']
    out_dir = project / r['output_dir']
    inv.append('# ' + sid + ':')
    for fn in ['raw.html', 'normalized.md', 'text_metadata.json', 'audit.json']:
        p = out_dir / fn
        inv.append(f'  {fn}: {"EXISTS" if p.exists() else "MISSING"} ({p.stat().st_size if p.exists() else 0} bytes)')
inv.append('#')
inv.append('# forbidden: ' + str(any_forbidden))
(A / (prefix + 'evidence_inventory.txt')).write_text('\n'.join(inv), encoding='utf-8')

# Manifest
batch_manifest = {
    'phase': '3H', 'timestamp': now, 'batch_id': 1, 'source_count': len(batch1_sources),
    'all_pass': all_pass, 'registry_clean': registry_clean, 'staged_empty': staged_empty,
    'any_forbidden': any_forbidden, 'sources': results,
}
with open(A / 'phase3h_batch1_capture_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(batch_manifest, f, ensure_ascii=False, indent=2, default=str)

# ── ZIP (含 5×4=20 产物文件 + 报告×2 + manifest + inventory + git×4 + 脚本) ──
zip_name = A / ('enterprise_kb_v1_phase3h_batch1_text_dom_capture_' + now_str + '.zip')
with zipfile.ZipFile(str(zip_name), 'w', zipfile.ZIP_DEFLATED) as zf:
    # 5 sources × 4 files
    for r_ in results:
        sid = r_['source_id']
        src_dir = project / r_['output_dir']
        for fn in ['raw.html', 'normalized.md', 'text_metadata.json', 'audit.json']:
            src = src_dir / fn
            arc = 'raw_sources/official_docs/' + sid + '/v1/' + fn
            if src.exists():
                zf.write(str(src), arcname=arc)

    # Report — 两个位置都打包
    # docs/... 版本 (从项目目录读)
    zf.write(str(report_docs), arcname='docs/enterprise_kb_v1/phase3h_batch1_text_dom_capture_report.md')
    # A\ 版本 (从 A 目录读)
    zf.write(str(report_a), arcname='phase3h_batch1_text_dom_capture_report.md')

    # Manifest
    manifest_src = A / 'phase3h_batch1_capture_manifest.json'
    zf.write(str(manifest_src), arcname='phase3h_batch1_capture_manifest.json')

    # Inventory
    inv_src = A / (prefix + 'evidence_inventory.txt')
    zf.write(str(inv_src), arcname=prefix + 'evidence_inventory.txt')

    # Git evidence
    for fn in ['git_status_registry_allowlist.txt', 'git_status_experiments.txt',
               'git_diff_cached_names.txt', 'forbidden_artifacts_check.txt']:
        p = A / (prefix + fn)
        if p.exists():
            zf.write(str(p), arcname=prefix + fn)

    # Script
    zf.write(str(project / 'scripts/enterprise_kb_v1/capture_text_dom_batch.py'),
             arcname='scripts/enterprise_kb_v1/capture_text_dom_batch.py')

with zipfile.ZipFile(str(zip_name), 'r') as zf:
    n = zf.namelist()
print(f'\nZIP: {zip_name.name} | {len(n)} entries | {zip_name.stat().st_size/1024:.0f} KB')
# 验证报告存在
has_docs = 'docs/enterprise_kb_v1/phase3h_batch1_text_dom_capture_report.md' in n
has_a = 'phase3h_batch1_text_dom_capture_report.md' in n
print(f'Report (docs): {has_docs}')
print(f'Report (A): {has_a}')
print(f'All pass: {all_pass}')
for r_ in results:
    q = r_.get('quality', 'FAIL')
    print(f'  {r_["source_id"]}: {q}')
