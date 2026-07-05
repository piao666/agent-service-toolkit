#!/usr/bin/env python3
"""Phase 4C HPC Preflight — auto-detect paths on HPC."""
import json, os, sys
from pathlib import Path
from datetime import datetime

now = datetime.now().isoformat()
PROJECT = Path.home() / 'jupyterlab' / 'RAG' / 'agent-service-toolkit-clean'
A_DIR = Path.home() / 'jupyterlab' / 'RAG' / 'A'
MODEL_ROOT = Path.home() / 'jupyterlab' / 'models'

# GPU check
import torch
gpu = {
    'cuda_available': torch.cuda.is_available(),
    'device_name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A',
    'gpu_memory_gb': round(torch.cuda.get_device_properties(0).total_mem / 1e9, 1) if torch.cuda.is_available() else 0,
    'torch_version': torch.__version__,
}
print('GPU: ' + str(gpu))

# Model check
MODEL_NAMES = [
    ('bge-small-zh-v1.5', 'embedding'),
    ('bge-m3', 'embedding'),
    ('qwen3-embedding-0.6b', 'embedding'),
    ('multilingual-e5-base', 'embedding'),
    ('bge-reranker-base', 'reranker'),
    ('Qwen3-Reranker_0.6B', 'reranker'),
]

models = []
for name, mtype in MODEL_NAMES:
    p = MODEL_ROOT / name
    entry = {'model_name': name, 'found': p.is_dir(), 'path': str(p), 'type': mtype}
    if entry['found']:
        entry['config_exists'] = (p / 'config.json').exists()
        if mtype == 'embedding':
            try:
                from sentence_transformers import SentenceTransformer
                m = SentenceTransformer(str(p), device='cuda')
                d = m.get_sentence_embedding_dimension() if hasattr(m, 'get_sentence_embedding_dimension') else m.get_embedding_dimension()
                emb = m.encode(['test'], show_progress_bar=False)
                entry['can_load'] = True
                entry['dimension'] = d
                entry['encode_smoke_ok'] = len(emb.shape) == 2
                print('  ' + name + ': dim=' + str(d) + ' smoke=OK')
            except Exception as e:
                entry['can_load'] = False
                entry['error'] = str(e)[:200]
                print('  ' + name + ': LOAD FAILED - ' + str(e)[:100])
    else:
        print('  ' + name + ': MISSING')
    models.append(entry)

# Env info
env = {
    'timestamp': now,
    'hostname': os.uname().nodename,
    'python': sys.version[:50],
    'project_root': str(PROJECT),
    'model_root': str(MODEL_ROOT),
    'gpu': gpu,
}

# Write outputs
A_DIR.mkdir(parents=True, exist_ok=True)
(PROJECT / 'logs').mkdir(exist_ok=True)
(PROJECT / 'hpc_results').mkdir(exist_ok=True)

with open(A_DIR / 'phase4c_hpc_model_path_check.json', 'w') as f:
    json.dump({'models': models, 'model_root': str(MODEL_ROOT)}, f, indent=2)

with open(A_DIR / 'phase4c_hpc_env_preflight.json', 'w') as f:
    json.dump({'gpu': gpu, 'env': env}, f, indent=2)

txt = 'Phase 4C HPC Preflight\n'
txt += now + '\n'
txt += 'GPU: ' + gpu['device_name'] + ' (' + str(gpu['gpu_memory_gb']) + ' GB, CUDA=' + str(gpu['cuda_available']) + ')\n'
txt += 'Model root: ' + str(MODEL_ROOT) + '\n'
txt += 'Models: ' + str(sum(1 for m in models if m['found'])) + '/6 found\n'
for m in models:
    txt += '  ' + m['model_name'] + ': ' + ('dim=' + str(m.get('dimension', '?')) + ' smoke=' + str(m.get('encode_smoke_ok', False)) if m.get('can_load') else 'MISSING/FAIL') + '\n'

with open(A_DIR / 'phase4c_hpc_env_preflight.txt', 'w') as f:
    f.write(txt)

embed_count = sum(1 for m in models if m.get('can_load') and m['type'] == 'embedding')
ready = gpu['cuda_available'] and embed_count >= 4
print('\nPreflight complete. Results in ' + str(A_DIR))
print('Embedding models loadable: ' + str(embed_count) + '/4')
print('READY for Embedding A/B' if ready else 'BLOCKERS exist')

# Directory tree
import subprocess as sp
try:
    tree = sp.run(['find', str(A_DIR), '-type', 'f'], capture_output=True, text=True, timeout=10).stdout
except:
    tree = '(find failed)'
with open(A_DIR / 'phase4c_hpc_directory_tree.txt', 'w') as f:
    f.write('# HPC RAG Directory Tree\n# ' + now + '\n\n' + tree)

sys.exit(0 if ready else 1)
