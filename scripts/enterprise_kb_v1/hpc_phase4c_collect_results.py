#!/usr/bin/env python3
"""Phase 4C HPC: Collect all results into downloadable ZIP."""
import json, zipfile, subprocess
from pathlib import Path
from datetime import datetime

now = datetime.now().isoformat()
A_DIR = Path.home() / 'jupyterlab' / 'RAG' / 'A'
RESULTS = A_DIR / 'phase4c_hpc_results'

# GPU snapshot
try:
    r = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=10)
    gpu_snap = r.stdout
except:
    gpu_snap = 'nvidia-smi not available'
(RESULTS / 'phase4c_hpc_gpu_snapshot.txt').write_text(gpu_snap)

# Environment info
with open(RESULTS / 'phase4c_hpc_preflight.json') as f:
    env = json.load(f)
env_txt = 'Phase 4C HPC Environment\n'
env_txt += now + '\n'
env_txt += 'Host: ' + env.get('env', {}).get('hostname', 'unknown') + '\n'
env_txt += 'Python: ' + env.get('env', {}).get('python', '')[:80] + '\n'
env_txt += 'GPU: ' + str(env.get('gpu', {})) + '\n'
(RESULTS / 'phase4c_hpc_environment.txt').write_text(env_txt)

# Failure cases
with open(RESULTS / 'phase4c_hpc_embedding_ab_results.json') as f:
    ab = json.load(f)
failures = []
for name, data in ab.items():
    if 'error' in data:
        failures.append(f'MODEL_FAIL: {name} - {data["error"]}')
    elif 'per_k' in data:
        for k, v in data['per_k'].items():
            if v['hit_rate'] < 0.5:
                failures.append(f'LOW_HIT_RATE: {name} k={k} hit_rate={v["hit_rate"]:.4f}')

with open(RESULTS / 'phase4c_hpc_failure_cases.md', 'w') as f:
    f.write('# Phase 4C HPC Failure Cases\n\n' + now + '\n\n')
    if failures:
        for fail in failures:
            f.write('- ' + fail + '\n')
    else:
        f.write('No failures detected.\n')

# Check per-case debug row count
debug_count = 0
debug_path = RESULTS / 'phase4c_hpc_embedding_ab_per_case_debug.jsonl'
if debug_path.exists():
    with open(debug_path) as f:
        debug_count = sum(1 for _ in f)
print(f'Debug rows: {debug_count} (expected 88)')

# Package ZIP
zip_path = A_DIR / 'enterprise_kb_v1_phase4c_hpc_results.zip'
required = [
    'phase4c_hpc_preflight.json',
    'phase4c_hpc_model_availability.json',
    'phase4c_hpc_embedding_ab_results.json',
    'phase4c_hpc_embedding_ab_per_case_debug.jsonl',
    'phase4c_hpc_embedding_ab_report.md',
    'phase4c_hpc_retrieval_context_eval_results.json',
    'phase4c_hpc_retrieval_context_eval_report.md',
    'phase4c_hpc_failure_cases.md',
    'phase4c_hpc_gpu_snapshot.txt',
    'phase4c_hpc_environment.txt',
]

with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
    for fn in required:
        p = RESULTS / fn
        if p.exists():
            zf.write(str(p), arcname='results/' + fn)
        else:
            print(f'MISSING from ZIP: {fn}')

size_kb = zip_path.stat().st_size / 1024
print(f'ZIP: {zip_path} ({size_kb:.1f} KB)')
print(f'Required files: {sum(1 for fn in required if (RESULTS/fn).exists())}/{len(required)}')
print('Download to local E:\\RAG\\A\\')
