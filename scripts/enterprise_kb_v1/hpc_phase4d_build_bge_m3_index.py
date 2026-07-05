#!/usr/bin/env python3
"""Phase 4D: Adopt bge-m3 as default. Rebuild official_docs index, run eval."""
import json, time, sys, shutil
from pathlib import Path
from datetime import datetime

import torch
if not torch.cuda.is_available():
    print('FATAL: CUDA not available.'); sys.exit(1)

from sentence_transformers import SentenceTransformer
import chromadb

now = datetime.now().isoformat()
PROJECT = Path.home() / 'jupyterlab' / 'RAG' / 'agent-service-toolkit-clean'
A_DIR = Path.home() / 'jupyterlab' / 'RAG' / 'A'
RESULTS = A_DIR / 'phase4c_hpc_results'
STORAGE = PROJECT / 'storage'
MODEL_ROOT = Path.home() / 'jupyterlab' / 'models'

COLLECTION_NAME = 'enterprise_kb_v1_official_docs_bge_m3'
PERSIST_DIR = 'storage/chroma_enterprise_kb_v1_bge_m3'

# Load data
chunks = []
with open(PROJECT / 'data' / 'phase4c_clean_chunks.jsonl') as f:
    for line in f:
        if line.strip(): chunks.append(json.loads(line))

eval_cases = []
eval_path = PROJECT / 'data' / 'phase4d_eval_gold_official_docs.jsonl'
if not eval_path.exists():
    eval_path = PROJECT / 'data' / 'phase4c_eval_gold_official_docs.jsonl'
with open(eval_path) as f:
    for line in f:
        if line.strip(): eval_cases.append(json.loads(line))

print(f'Chunks: {len(chunks)} | Cases: {len(eval_cases)}')
print(f'Collection: {COLLECTION_NAME}')

# Load bge-m3
model = SentenceTransformer(str(MODEL_ROOT / 'bge-m3'), device='cuda')
dim = model.get_sentence_embedding_dimension() if hasattr(model, 'get_sentence_embedding_dimension') else model.get_embedding_dimension()
print(f'bge-m3 loaded: dim={dim}')

# Build index
t0 = time.time()
torch.cuda.reset_peak_memory_stats()

persist_dir = str(STORAGE / 'chroma_enterprise_kb_v1_bge_m3')
client = chromadb.PersistentClient(path=persist_dir)
try:
    client.delete_collection(COLLECTION_NAME)
except:
    pass
col = client.create_collection(COLLECTION_NAME, metadata={'hnsw:space': 'cosine'})

for i in range(0, len(chunks), 100):
    batch = chunks[i:i+100]
    embeddings = model.encode([c['text'] for c in batch], show_progress_bar=True).tolist()
    col.add(
        ids=[c['chunk_id'] for c in batch],
        documents=[c['text'] for c in batch],
        metadatas=[{'source_id': c['source_id'], 'heading_path': c['heading_path'], 'chunk_id': c['chunk_id']} for c in batch],
        embeddings=embeddings,
    )

build_time = time.time() - t0
gpu_mem = round(torch.cuda.max_memory_allocated() / 1e9, 2)
indexed_count = col.count()
print(f'Index built: {indexed_count} chunks | build={build_time:.1f}s | GPU={gpu_mem}GB')

# Retrieval context eval
per_k = {}; case_debug = []
for k in [3, 5, 10]:
    hits = 0; mrr_sum = 0; total = 0
    for c in eval_cases:
        expected = c['expected_source_ids']
        if not expected: total += 1; continue
        q_emb = model.encode([c['query']], show_progress_bar=False).tolist()
        res = col.query(query_embeddings=q_emb, n_results=k, include=['metadatas', 'distances'])
        sids = [m.get('source_id', '') for m in res['metadatas'][0]] if res['metadatas'] else []
        cids = [m.get('chunk_id', '') for m in res['metadatas'][0]] if res['metadatas'] else []
        hpaths = [m.get('heading_path', '') for m in res['metadatas'][0]] if res['metadatas'] else []
        dists = res.get('distances', [[]])[0] if res.get('distances') else []

        hit = any(es in sids for es in expected)
        if hit:
            hits += 1
            best_rank = min((sids.index(es) + 1) for es in expected if es in sids)
            mrr_sum += 1.0 / best_rank
        total += 1

        if k == 10:
            case_debug.append({
                'model_name': 'bge-m3',
                'case_id': c.get('case_id', ''),
                'query': c['query'][:80],
                'expected_source_ids': expected,
                'retrieved_source_ids': sids,
                'retrieved_chunk_ids': cids,
                'distances': [round(d, 6) for d in dists] if dists else [],
                'heading_paths': hpaths,
                'hit_at_3': any(es in sids[:3] for es in expected),
                'hit_at_5': any(es in sids[:5] for es in expected),
                'hit_at_10': hit,
            })

    per_k[str(k)] = {
        'hit_rate': round(hits / max(total, 1), 4),
        'mrr': round(mrr_sum / max(total, 1), 4),
        'hits': hits, 'total': total,
    }

# Check core_001 specifically
core001 = next((c for c in case_debug if c['case_id'] == 'core_001'), None)
if core001:
    print(f'core_001: expected={core001["expected_source_ids"]} retrieved={core001["retrieved_source_ids"][:3]} hit@3={core001["hit_at_3"]}')

# Write results
index_manifest = {
    'phase': '4D',
    'timestamp': now,
    'default_embedding': 'bge-m3',
    'high_precision_candidate': 'qwen3-embedding-0.6b',
    'lightweight_fallback': 'bge-small-zh-v1.5',
    'collection_name': COLLECTION_NAME,
    'persist_dir': PERSIST_DIR,
    'embedding_dimension': dim,
    'indexed_chunk_count': indexed_count,
    'indexed_source_count': len(set(c['source_id'] for c in chunks)),
    'build_time_seconds': round(build_time, 1),
    'gpu_memory_used_gb': gpu_mem,
    'per_k': per_k,
}

RESULTS.mkdir(parents=True, exist_ok=True)

with open(RESULTS / 'phase4d_bge_m3_index_manifest.json', 'w') as f:
    json.dump(index_manifest, f, indent=2)

with open(RESULTS / 'phase4d_retrieval_context_eval_results.json', 'w') as f:
    json.dump({'model': 'bge-m3', 'per_k': per_k, 'cases': case_debug}, f, indent=2)

# Report
report = [
    '# Phase 4D bge-m3 Retrieval Context Eval Report',
    '',
    '> GPU: NVIDIA L40 | Collection: ' + COLLECTION_NAME,
    '> Chunks: ' + str(indexed_count) + ' | Eval cases: ' + str(len(eval_cases)),
    '',
    '## Retrieval Results',
    '',
    '| k | hit_rate | MRR |',
    '|:--:|:---:|:---:|',
]
for k in ['3', '5', '10']:
    report.append(f'| {k} | {per_k[k]["hit_rate"]:.4f} | {per_k[k]["mrr"]:.4f} |')

report += [
    '',
    '## core_001 Fix Verification',
]
if core001:
    report.append(f'- Expected: {core001["expected_source_ids"]}')
    report.append(f'- Retrieved: {core001["retrieved_source_ids"][:3]}')
    report.append(f'- hit@3: {core001["hit_at_3"]}')
    report.append(f'- hit@5: {core001["hit_at_5"]}')

report += [
    '',
    '## Config Status',
    '- default_embedding: **bge-m3** (adopted)',
    '- high_precision_candidate: qwen3-embedding-0.6b (retained)',
    '- lightweight_fallback: bge-small-zh-v1.5 (retained)',
    '- reranker: NOT enabled (deferred to next phase)',
    '- production answer pipeline: NOT entered',
]
with open(RESULTS / 'phase4d_retrieval_context_eval_report.md', 'w') as f:
    f.write('\n'.join(report))

# Failure cases
failures = []
for c in case_debug:
    if not c['hit_at_3']:
        failures.append(f'{c["case_id"]}: {c["query"][:60]} — expected={c["expected_source_ids"]}, got={c["retrieved_source_ids"][:3]}')
with open(RESULTS / 'phase4d_failure_cases.md', 'w') as f:
    f.write('# Phase 4D Failure Cases\n\n' + now + '\n\n')
    if failures:
        for fail in failures:
            f.write('- ' + fail + '\n')
    else:
        f.write('No failures at hit@3.\n')

# Run log
with open(RESULTS / 'phase4d_hpc_run_log.txt', 'w') as f:
    f.write(f'Phase 4D HPC Run Log\n{now}\n')
    f.write(f'Model: bge-m3 (dim={dim})\n')
    f.write(f'Collection: {COLLECTION_NAME}\n')
    f.write(f'Indexed: {indexed_count} chunks\n')
    f.write(f'Build time: {build_time:.1f}s\n')
    f.write(f'GPU memory: {gpu_mem}GB\n')
    for k, v in per_k.items():
        f.write(f'k={k}: hit_rate={v["hit_rate"]:.4f} MRR={v["mrr"]:.4f}\n')

# Package
import zipfile
zip_path = A_DIR / 'enterprise_kb_v1_phase4d_bge_m3_default_index.zip'
with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
    for fn in ['phase4d_bge_m3_index_manifest.json',
               'phase4d_retrieval_context_eval_results.json',
               'phase4d_retrieval_context_eval_report.md',
               'phase4d_failure_cases.md',
               'phase4d_hpc_run_log.txt']:
        p = RESULTS / fn
        if p.exists():
            zf.write(str(p), arcname='results/' + fn)

print(f'\nZIP: {zip_path} ({zip_path.stat().st_size/1024:.0f} KB)')
print(f'k=3: {per_k["3"]["hit_rate"]:.4f} | k=5: {per_k["5"]["hit_rate"]:.4f} | k=10: {per_k["10"]["hit_rate"]:.4f}')
print('DONE')
