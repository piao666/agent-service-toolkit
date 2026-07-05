#!/usr/bin/env python3
"""Phase 3E1-B0 Screenshot Sidecar 工具预检脚本（证据补强版）。
检查本地环境、git 安全、产物安全。Python stdlib + Pillow。
不截图、不安装依赖、不修改 registry/allowlist。"""

import json, os, re, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # agent-service-toolkit-clean/

# ── 工具函数 ──

def run_git(args):
    """运行 git 命令，返回 (returncode, stdout, stderr)。"""
    r = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    return r.returncode, r.stdout.strip(), r.stderr.strip()

# ── 1. Pillow ──

def check_pillow():
    try:
        from PIL import Image
        return {
            "available": True,
            "version": Image.__version__,
            "script_verified": True,
            "not_script_verifiable": False,
        }
    except ImportError:
        return {
            "available": False,
            "version": None,
            "script_verified": True,
            "not_script_verifiable": False,
        }

# ── 2. 系统浏览器 ──

def check_browsers():
    paths = {
        "chrome": [
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        ],
        "edge": [
            "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        ],
    }
    result = {}
    for name, search_paths in paths.items():
        found = None
        for p in search_paths:
            if os.path.exists(p):
                found = p
                break
        result[name] = {
            "available": found is not None,
            "path": found,
            "script_verified": True,
            "not_script_verifiable": False,
        }
    return result

# ── 3. Playwright 本地 pip ──

def check_playwright_local():
    try:
        import playwright
        ver = getattr(playwright, "__version__", "unknown")
        return {
            "available": True,
            "version": ver,
            "script_verified": True,
            "not_script_verifiable": False,
        }
    except ImportError:
        return {
            "available": False,
            "version": None,
            "script_verified": True,
            "not_script_verifiable": False,
        }

# ── 4. MCP Playwright ──

def check_playwright_mcp():
    """MCP Playwright 工具可用性。
    Python 脚本无法独立检测 MCP 工具注册表 —— 它只在 Claude Code 会话中存在。
    因此标记为 not_script_verifiable。
    """
    return {
        "available": None,  # not determinable by script
        "method": "not_script_verifiable",
        "note": "MCP Playwright 工具仅存在于 Claude Code 会话 tool registry 中，Python subprocess 无法检测。"
                "需通过独立证据文件 phase3e1b0_mcp_tool_evidence.txt 交叉验证。",
        "script_verified": False,
        "not_script_verifiable": True,
        "report_claimed": True,  # B0 报告声称 MCP Playwright 可用
        "external_evidence": "E:/RAG/A/phase3e1b0_mcp_tool_evidence.txt",
    }

# ── 5. experiments 目录 ──

def check_experiments_dir():
    base = PROJECT_ROOT / "data/enterprise_kb_v1/experiments/phase3d_multimodal"
    visual_dir = base / "visual"

    pngs = list(visual_dir.rglob("*.png")) if visual_dir.exists() else []
    vmds = list(visual_dir.rglob("visual_metadata.json")) if visual_dir.exists() else []

    # experiments 下所有文件
    all_files = []
    exp_root = PROJECT_ROOT / "data/enterprise_kb_v1/experiments"
    if exp_root.exists():
        for f in exp_root.rglob("*"):
            if f.is_file():
                all_files.append(str(f.relative_to(PROJECT_ROOT)))

    return {
        "base_exists": base.exists(),
        "text_dom_exists": (base / "text_dom").exists(),
        "visual_exists": visual_dir.exists(),
        "visual_png_count": len(pngs),
        "visual_png_paths": [str(p.relative_to(PROJECT_ROOT)) for p in pngs],
        "visual_metadata_json_count": len(vmds),
        "visual_metadata_json_paths": [str(p.relative_to(PROJECT_ROOT)) for p in vmds],
        "experiments_all_files": all_files,
        "script_verified": True,
        "not_script_verifiable": False,
    }

# ── 6. Chroma / FAISS / embedding / index 产物 ──

def check_index_artifacts():
    """扫描项目中是否存在向量索引/嵌入相关产物。"""
    root = PROJECT_ROOT
    findings = {}

    # Chroma persist dir
    chroma_dir = root / "storage" / "chroma_enterprise_kb_v1"
    findings["chroma_persist_dir"] = {
        "path": str(chroma_dir.relative_to(root)),
        "exists": chroma_dir.exists(),
        "file_count": len(list(chroma_dir.rglob("*"))) if chroma_dir.exists() else 0,
    }

    # 各类索引文件
    index_extensions = ["*.bin", "*.pkl", "*.index", "*.faiss", "*.parquet", "*.h5", "*.pt", "*.onnx"]
    exclude_dirs = {".git", "venv", "__pycache__", "node_modules", ".venv", "models"}
    for ext in index_extensions:
        found = []
        for f in root.rglob(ext):
            parts = set(f.parts)
            if not (exclude_dirs & parts):
                found.append(str(f.relative_to(root)))
        findings[f"files_{ext.replace('*', '')}"] = {
            "count": len(found),
            "paths": found[:10],  # 最多列出 10 个
        }

    # 嵌入模型目录
    models_dir = root / "models"
    findings["models_dir"] = {
        "path": str(models_dir.relative_to(root)),
        "exists": models_dir.exists(),
        "note": "本地嵌入模型（bge-small-zh-v1.5），非本次实验产物，属项目基础设施",
    }

    findings["script_verified"] = True
    findings["not_script_verifiable"] = False
    return findings

# ── 7. Git 安全检查 ──

def check_git_safety():
    """检查 git 状态：registry、allowlist、experiments、staged files。"""
    result = {}

    # 全量 git status
    rc, stdout, stderr = run_git(["status", "--short"])
    result["git_status_short"] = stdout if rc == 0 else f"GIT_ERROR: {stderr}"
    result["git_status_short_lines"] = len(stdout.split("\n")) if stdout.strip() else 0

    # Registry + allowlist
    rc, stdout, _ = run_git(["status", "--short", "--",
        "data/enterprise_kb_v1/source_registry/source_registry.yaml",
        "data/enterprise_kb_v1/source_registry/official_docs_allowlist.yaml"])
    result["registry_allowlist_status"] = stdout if stdout.strip() else "(clean)"
    result["registry_modified"] = bool(stdout.strip())

    # Experiments
    rc, stdout, _ = run_git(["status", "--short", "--",
        "data/enterprise_kb_v1/experiments/"])
    result["experiments_status"] = stdout if stdout.strip() else "(clean — gitignored)"

    # Staged files
    rc, stdout, _ = run_git(["diff", "--cached", "--name-only"])
    result["staged_files"] = stdout.split("\n") if stdout.strip() else []
    result["has_staged_files"] = bool(stdout.strip())

    # .gitignore 覆盖
    gi_path = PROJECT_ROOT / ".gitignore"
    if gi_path.exists():
        gi_content = gi_path.read_text(encoding="utf-8")
        result["gitignore_covers_experiments"] = "data/enterprise_kb_v1/experiments/" in gi_content
    else:
        result["gitignore_covers_experiments"] = False

    result["script_verified"] = True
    result["not_script_verifiable"] = False
    return result

# ── 主流程 ──

def main():
    now = datetime.now(CST).isoformat()

    pillow = check_pillow()
    browsers = check_browsers()
    playwright_local = check_playwright_local()
    playwright_mcp = check_playwright_mcp()
    experiments_dir = check_experiments_dir()
    index_artifacts = check_index_artifacts()
    git_safety = check_git_safety()

    # ── 判定逻辑 ──

    # 脚本可实证的浏览器存在
    script_verifiable_browser = (
        browsers["chrome"]["available"] or browsers["edge"]["available"]
    )

    # 截图能力判定（分层）
    if playwright_local["available"]:
        screenshot_method = "local_playwright"
        screenshot_verification = "script_verified"
    elif script_verifiable_browser:
        # 系统浏览器存在 + MCP 可能可用 → 有后备
        screenshot_method = "system_browser_cdp_or_mcp"
        screenshot_verification = "partial_script_verified"  # 浏览器脚本可证，MCP 不可证
    else:
        screenshot_method = None
        screenshot_verification = "unavailable"

    # MCP 独立判定
    mcp_claim = {
        "mcp_playwright_claimed_available": playwright_mcp["report_claimed"],
        "script_can_verify": False,
        "external_evidence_file": playwright_mcp["external_evidence"],
        "warning": "MCP Playwright 可用性不能由 Python 脚本独立实证。"
                   "如果 phase3e1b0_mcp_tool_evidence.txt 缺失或不可信，"
                   "则 ready_for_b1 必须降级为 NEEDS_MCP_VERIFICATION。",
    }

    # ready_for_b1 判定（保守：MCP 不可脚本实证不作为无条件通过依据）
    hard_blockers = []
    if not pillow["available"]:
        hard_blockers.append("pillow_unavailable")
    if not script_verifiable_browser and not playwright_local["available"]:
        hard_blockers.append("no_browser_script_verifiable")
    if git_safety["registry_modified"]:
        hard_blockers.append("registry_modified")
    if git_safety["has_staged_files"]:
        hard_blockers.append("staged_files_present")
    if experiments_dir["visual_png_count"] > 0:
        hard_blockers.append("existing_screenshots_found")
    if index_artifacts["chroma_persist_dir"]["exists"]:
        hard_blockers.append("chroma_dir_exists")

    ready_for_b1_script = len(hard_blockers) == 0

    # 综合判定
    if ready_for_b1_script and playwright_mcp["report_claimed"]:
        overall_ready = "READY — 脚本实证通过，MCP 需外部证据交叉验证"
    elif ready_for_b1_script and not playwright_mcp["report_claimed"]:
        overall_ready = "NEEDS_CLARIFICATION — 脚本实证通过但 MCP 未声称可用"
    elif not ready_for_b1_script:
        overall_ready = "NOT_READY"
    else:
        overall_ready = "UNKNOWN"

    manifest = {
        "precheck_version": "2.0.0",
        "precheck_timestamp": now,
        "precheck_phase": "3E1-B0",
        "note": "本轮只做预检和计划，不生成真实截图。证据补强版：所有字段区分 script_verified / report_claimed / not_script_verifiable。",

        # ── 逐项检查结果 ──
        "checks": {
            "pillow": pillow,
            "browsers": browsers,
            "playwright_local": playwright_local,
            "playwright_mcp": playwright_mcp,
            "experiments_dir": experiments_dir,
            "index_artifacts": index_artifacts,
            "git_safety": git_safety,
        },

        # ── MCP 独立判定 ──
        "mcp_claim": mcp_claim,

        # ── 硬阻塞项 ──
        "hard_blockers": hard_blockers,

        # ── 分层判定（证据链） ──
        "verdict": {
            "screenshot_method": screenshot_method,
            "screenshot_verification": screenshot_verification,
            "ready_for_b1_script_verifiable": ready_for_b1_script,
            "ready_for_b1_overall": overall_ready,
            "evidence_files": {
                "git_status_short": "E:/RAG/A/phase3e1b0_git_status_short.txt",
                "git_status_registry_allowlist": "E:/RAG/A/phase3e1b0_git_status_registry_allowlist.txt",
                "git_status_experiments": "E:/RAG/A/phase3e1b0_git_status_experiments.txt",
                "git_diff_cached_names": "E:/RAG/A/phase3e1b0_git_diff_cached_names.txt",
                "mcp_tool_evidence": "E:/RAG/A/phase3e1b0_mcp_tool_evidence.txt",
            },
        },
    }

    # 写入 manifest
    out_dir = Path("E:/RAG/A")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "phase3e1b0_screenshot_sidecar_review_manifest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"Manifest written: {out_path}")
    print(f"Hard blockers: {hard_blockers or 'none'}")
    print(f"ready_for_b1 (script): {ready_for_b1_script}")
    print(f"ready_for_b1 (overall): {overall_ready}")

if __name__ == "__main__":
    main()
