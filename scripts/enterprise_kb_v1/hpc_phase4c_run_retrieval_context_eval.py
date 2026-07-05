#!/usr/bin/env python3
"""Phase 4C HPC Retrieval Context Eval — top 2 models, no LLM answer generation."""
import json, sys
from pathlib import Path

import torch
if not torch.cuda.is_available():
    print('FATAL: CUDA not available.'); sys.exit(1)

from sentence_transformers import SentenceTransformer
import chromadb

PROJECT = Path.home() / 'jupyterlab' / 'RAG' / 'agent-service-toolkit-clean'
A_DIR = Path.home() / 'jupyterlab' / 'RAG' / 'A'
RESULTS = A_DIR / 'phase4c_hpc_results'
STORAGE = PROJECT / 'storage'

with open(A_DIR / 'phase4c_hpc_model_path_check.json') as f:
    md = json.load(f)
MODEL_ROOT = Path(md['model_root'])

with open(RESULTS / 'phase4c_hpc_embedding_ab_results.json') as f:
    ab = json.load(f)
sorted_m = sorted([(n, d) for n, d in ab.items() if 'per_k' in d],
                  key=lambda x: x[1]['per_k']['5']['hit_rate'], reverse=True)
top2 = sorted_m[:2]
print(f'Top 2: {top2[0][0]}, {top2[1][0]}')

eval_cases = []
with open(PROJECT / 'data' / 'phase4c_eval_gold_official_docs.jsonl') as f:
    for line in f:
        if line.strip(): eval_cases.append(json.loads(line))

MODEL_PATHS = {
    'bge-small-zh-v1.5': MODEL_ROOT / 'bge-small-zh-v1.5',
    'bge-m3': MODEL_ROOT / 'bge-m3',
    'qwen3-embedding-0.6b': MODEL_ROOT / 'qwen3-embedding-0.6b',
    'multilingual-e5-base': MODEL_ROOT / 'multilingual-e5-base',
}
COLLECTION_DIRS = {
    'bge-small-zh-v1.5': 'chroma_4c_bge_small_zh_v1_5',
    'bge-m3': 'chroma_4c_bge_m3',
    'qwen3-embedding-0.6b': 'chroma_4c_qwen3_embedding_0_6b',
    'multilingual-e5-base': 'chroma_4c_multilingual_e5_base',
}

eval_results = {}
for model_name, _ in top2:
    model = SentenceTransformer(str(MODEL_PATHS[model_name]), device='cuda')
    client = chromadb.PersistentClient(path=str(STORAGE / COLLECTION_DIRS[model_name]))
    col = client.get_collection('enterprise_kb_v1')

    cases_out = []
    for c in eval_cases[:10]:
        expected = c['expected_source_ids']
        q_emb = model.encode([c['query']], show_progress_bar=False).tolist()
        res = col.query(query_embeddings=q_emb, n_results=3, include=['metadatas', 'documents'])
        sids = [m.get('source_id', '') for m in res['metadatas'][0]] if res['metadatas'] else []
        cids = [m.get('chunk_id', '') for m in res['metadatas'][0]] if res['metadatas'] else []
        hpaths = [m.get('heading_path', '') for m in res['metadatas'][0]] if res['metadatas'] else []
        contexts = res.get('documents', [[]])[0] if res.get('documents') else []

        has_context = len(contexts) > 0 and any(len(ctx) > 50 for ctx in contexts)
        citation_valid = any(es in sids for es in expected) if expected else False
        context_chars = sum(len(ctx) for ctx in contexts)
        supported = context_chars > 100

        cases_out.append({
            'model_name': model_name,
            'case_id': c.get('case_id', ''),
            'query': c['query'][:80],
            'expected_source_ids': expected,
            'retrieved_source_ids': sids,
            'retrieved_chunk_ids': cids,
            'heading_paths': hpaths,
            'context_chars_total': context_chars,
            'has_context': has_context,
            'citation_source_valid': citation_valid,
            'context_sufficient': supported,
            'note': 'retrieval_context_eval — no LLM answer generated',
            'pass': has_context and citation_valid,
        })
    eval_results[model_name] = {
        'total': len(cases_out),
        'pass': sum(1 for r in cases_out if r['pass']),
        'cases': cases_out,
    }
    print(f'{model_name}: {eval_results[model_name]["pass"]}/{len(cases_out)} pass')

with open(RESULTS / 'phase4c_hpc_retrieval_context_eval_results.json', 'w') as f:
    json.dump(eval_results, f, indent=2)

report = [
    '# Phase 4C HPC Retrieval Context Eval Report',
    '',
    '> Note: retrieval_context_eval — no LLM answer generation.',
    '> Checks whether retrieved context contains expected source.',
    '',
    '| Model | Pass | Total |',
    '|-------|:----:|:-----:|',
]
for name, data in eval_results.items():
    report.append(f'| {name} | {data["pass"]} | {data["total"]} |')
report += [
    '',
    '## Methodology',
    '- Top 3 chunks retrieved per query',
    '- Pass = retrieved context contains expected source AND context > 50 chars',
    '- No LLM answer generation (retrieval-only evaluation)',
]
with open(RESULTS / 'phase4c_hpc_retrieval_context_eval_report.md', 'w') as f:
    f.write('\n'.join(report))

print('DONE: Retrieval Context Eval')
