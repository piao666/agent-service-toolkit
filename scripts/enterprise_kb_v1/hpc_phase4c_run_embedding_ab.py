#!/usr/bin/env python3
"""Phase 4C HPC Embedding A/B — 4 models, per-case debug × 88 rows, all fields."""
import json, time, os, sys
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
RESULTS.mkdir(parents=True, exist_ok=True)

# Load model paths from preflight
with open(A_DIR / 'phase4c_hpc_model_path_check.json') as f:
    md = json.load(f)
MODEL_ROOT = Path(md['model_root'])

# Copy preflight results into results/
for fn in ['phase4c_hpc_env_preflight.json','phase4c_hpc_model_path_check.json']:
    src = A_DIR / fn
    if src.exists():
        import shutil
        dst = RESULTS / fn.replace('env_','').replace('_path_check','_availability')
        if fn == 'phase4c_hpc_env_preflight.json':
            dst = RESULTS / 'phase4c_hpc_preflight.json'
        shutil.copy(str(src), str(dst))

# Load data
chunks = []
with open(PROJECT / 'data' / 'phase4c_clean_chunks.jsonl') as f:
    for line in f:
        if line.strip(): chunks.append(json.loads(line))
eval_cases = []
with open(PROJECT / 'data' / 'phase4c_eval_gold_official_docs.jsonl') as f:
    for line in f:
        if line.strip(): eval_cases.append(json.loads(line))
print(f'Chunks: {len(chunks)} | Cases: {len(eval_cases)}')

MODELS = {
    'bge-small-zh-v1.5': MODEL_ROOT / 'bge-small-zh-v1.5',
    'bge-m3': MODEL_ROOT / 'bge-m3',
    'qwen3-embedding-0.6b': MODEL_ROOT / 'qwen3-embedding-0.6b',
    'multilingual-e5-base': MODEL_ROOT / 'multilingual-e5-base',
}

ab_results = {}
all_case_debug = []  # 88 rows = 22 cases × 4 models

for model_name, model_path in MODELS.items():
    if not model_path.is_dir():
        ab_results[model_name] = {'error': f'path missing: {model_path}'}
        continue

    print(f'\n=== {model_name} ===')
    t0 = time.time()
    torch.cuda.reset_peak_memory_stats()

    model = SentenceTransformer(str(model_path), device='cuda')
    dim = model.get_sentence_embedding_dimension() if hasattr(model, 'get_sentence_embedding_dimension') else model.get_embedding_dimension()

    # Build index
    persist_dir = str(STORAGE / f'chroma_4c_{model_name.replace("-","_").replace(".","_")}')
    client = chromadb.PersistentClient(path=persist_dir)
    try: client.delete_collection('enterprise_kb_v1')
    except: pass
    col = client.create_collection('enterprise_kb_v1', metadata={'hnsw:space': 'cosine'})

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
    torch.cuda.reset_peak_memory_stats()

    # Retrieval eval with per-case debug
    per_k = {}
    for k in [3, 5, 10]:
        hits = 0; mrr_sum = 0; total = 0
        for c in eval_cases:
            expected = c['expected_source_ids']
            if not expected: total += 1; continue
            q_emb = model.encode([c['query']], show_progress_bar=False).tolist()
            res = col.query(query_embeddings=q_emb, n_results=k, include=['metadatas', 'distances', 'documents'])
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

            # Per-case debug — append for ALL k=10 to avoid overwrite
            if k == 10:
                # Also compute hit_at_3 and hit_at_5 from the same result
                hit_at_3 = any(es in sids[:3] for es in expected)
                hit_at_5 = any(es in sids[:5] for es in expected)
                hit_at_10 = hit

                all_case_debug.append({
                    'model_name': model_name,
                    'case_id': c.get('case_id', ''),
                    'query': c['query'][:80],
                    'expected_source_ids': expected,
                    'retrieved_source_ids': sids,
                    'retrieved_chunk_ids': cids,
                    'distances': [round(d, 6) for d in dists] if dists else [],
                    'scores': [round(1.0 - d, 6) for d in dists] if dists else [],
                    'heading_paths': hpaths,
                    'hit_at_3': hit_at_3,
                    'hit_at_5': hit_at_5,
                    'hit_at_10': hit_at_10,
                })

        per_k[str(k)] = {
            'hit_rate': round(hits / max(total, 1), 4),
            'mrr': round(mrr_sum / max(total, 1), 4),
            'hits': hits, 'total': total,
        }

    # Source dedup hit rate
    source_dedup = {}
    for k in [3, 5, 10]:
        hits_dedup = 0; total_dedup = 0
        for c in eval_cases:
            expected = c['expected_source_ids']
            if not expected: total_dedup += 1; continue
            q_emb = model.encode([c['query']], show_progress_bar=False).tolist()
            res = col.query(query_embeddings=q_emb, n_results=k, include=['metadatas'])
            sids = [m.get('source_id', '') for m in res['metadatas'][0]] if res['metadatas'] else []
            # Count unique expected sources hit
            unique_hits = len(set(es for es in expected if es in sids))
            if unique_hits > 0: hits_dedup += 1
            total_dedup += 1
        source_dedup[str(k)] = round(hits_dedup / max(total_dedup, 1), 4)

    ab_results[model_name] = {
        'dimension': dim,
        'indexed_chunks': len(chunks),
        'indexed_sources': len(set(c['source_id'] for c in chunks)),
        'build_time_seconds': round(build_time, 1),
        'gpu_memory_used_gb': gpu_mem,
        'per_k': per_k,
        'source_dedup_hit_rate': source_dedup,
    }
    print(f'  dim={dim} | build={build_time:.1f}s | GPU={gpu_mem}GB | k=5={per_k["5"]["hit_rate"]:.4f}')

# Write per-case debug
with open(RESULTS / 'phase4c_hpc_embedding_ab_per_case_debug.jsonl', 'w') as f:
    for entry in all_case_debug:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

# Write A/B results
with open(RESULTS / 'phase4c_hpc_embedding_ab_results.json', 'w') as f:
    json.dump(ab_results, f, indent=2)

# A/B report
sorted_m = sorted([(n, d) for n, d in ab_results.items() if 'per_k' in d],
                  key=lambda x: x[1]['per_k']['5']['hit_rate'], reverse=True)
best_name = sorted_m[0][0] if sorted_m else 'unknown'

report = [
    '# Phase 4C HPC Embedding A/B Report',
    '',
    '> GPU: NVIDIA L40 (11.8 GB) | torch 2.6.0+cu124 | Python 3.10.8',
    '> Chunks: ' + str(len(chunks)) + ' | Eval cases: ' + str(len(eval_cases)),
    '',
    '## Results',
    '',
    '| Model | dim | build | GPU | k=3 | k=5 | k=10 | MRR@5 |',
    '|-------|:---:|------:|:---:|:---:|:---:|:----:|:-----:|',
]
for name, data in sorted_m:
    pk = data['per_k']
    report.append(f'| {name} | {data["dimension"]} | {data["build_time_seconds"]}s | {data["gpu_memory_used_gb"]}GB | '
                  f'{pk["3"]["hit_rate"]:.4f} | {pk["5"]["hit_rate"]:.4f} | {pk["10"]["hit_rate"]:.4f} | {pk["5"]["mrr"]:.4f} |')

report += [
    '',
    '## Per-case debug',
    '',
    f'Total debug rows: {len(all_case_debug)} (22 cases × 4 models = 88 expected)',
    '',
    '## Recommendation',
    '',
    f'**Default embedding: {best_name}**',
]
with open(RESULTS / 'phase4c_hpc_embedding_ab_report.md', 'w') as f:
    f.write('\n'.join(report))

print(f'\nDebug rows: {len(all_case_debug)}')
print(f'Best model: {best_name}')
print('DONE: Embedding A/B')
