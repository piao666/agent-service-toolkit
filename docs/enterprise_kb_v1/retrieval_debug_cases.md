# 检索 Debug 案例集

本文档是检索系统排障的实战手册，覆盖 hit_rate 异常、Chroma 问题、embedding 配置错误、路径问题、metadata 缺失等常见故障的诊断和修复方法。

---

## 1. hit_rate 异常排查 Checklist

当 `hit_rate` 报告为异常值（0.0、远低于预期、或与上一轮评测差异 >0.1）时，按以下顺序逐项排查：

### 1.1 hit_rate = 0.0（全部 case 失败）

| 检查项 | 命令/方法 | 预期 |
|--------|-----------|------|
| `source_id` 字段名是否一致 | `grep "source_id" eval_cases.json` + 检查检索结果 metadata | eval 用的字段名与 retriever 输出的字段名必须一致 |
| Chroma collection 是否存在 | `collection.count()` | > 0 |
| embedding 维度是否匹配 | `collection.get(include=["embeddings"])` 检查 shape | 与 query embedding 维度一致 |
| query embedding 是否正常 | `print(embedding[:5])` | 非全 0、非 NaN |
| `where` 过滤条件是否过严 | 去掉 `where` 条件后重新检索 | 结果数量应增加 |

### 1.2 hit_rate 偏低但与预期不符（0.3-0.6）

| 检查项 | 方法 |
|--------|------|
| `k` 值是否过小 | 增大 `k`（默认 5），看 hit_rate 是否显著提升（如 k=10） |
| chunk 切分质量 | 抽查几个失败 case 的 chunk 内容，确认相关段落是否在 chunk 中 |
| embedding 模型质量 | 用 `model.similarity(q1, q2)` 测试同义句对，看相似度是否合理 |
| 评测数据质量 | 检查 `expected_source_ids` 是否合理、query 是否与 source 内容相关 |

### 1.3 hit_rate 比上一轮评测下降

| 检查项 | 方法 |
|--------|------|
| 代码是否有改动 | `git diff` 检查 retrievers、embeddings、schemas 相关文件 |
| 语料是否有新增/删除 | 对比 `collection.count()` 变化 |
| 评测数据集是否有变更 | `diff` 对比两次评测的 eval cases |
| 随机种子是否一致 | 检查 `torch.manual_seed()`、`random.seed()` 设置 |

---

## 2. Chroma Collection 不存在的诊断

### 症状
```
chromadb.errors.InvalidCollectionException: Collection xxx does not exist.
```

### 排查步骤

**步骤 1：确认 persist_dir 路径**
```python
import chromadb
client = chromadb.PersistentClient(path="./storage/chroma_enterprise_kb_v1")
print(client.list_collections())  # 列出所有 collection
```

**步骤 2：检查路径是绝对还是相对**
```python
import os
print(os.path.abspath("./storage/chroma_enterprise_kb_v1"))
# 相对路径依赖于当前工作目录（cwd），可能在不同调用方式下指向不同位置
```

**步骤 3：检查目录是否存在且有数据**
```bash
ls -la ./storage/chroma_enterprise_kb_v1/
# 应该包含 chroma.sqlite3 文件和多个 UUID 子目录
```

### 常见原因与修复

| 原因 | 修复 |
|------|------|
| persist_dir 路径拼写错误 | 核对配置中 `CHROMA_PERSIST_DIR` 的值 |
| 使用相对路径，cwd 不对 | 改用绝对路径：`os.path.join(project_root, "storage", "chroma_enterprise_kb_v1")` |
| 数据从未构建 | 运行 embedding 索引构建脚本 |
| Chroma 版本升级导致数据不兼容 | 删除旧数据，用同版本 Chroma 重建（Chroma 0.4.x 与 0.5.x 数据不兼容） |
| SQLite 文件损坏 | 删除 `chroma.sqlite3`，重建 collection |

### 预防措施

- 启动时在日志中打印 `persist_dir` 的绝对路径和 `collection.count()`
- 使用环境变量 `CHROMA_PERSIST_DIR` 统一管理路径
- 在 CI 中验证 collection 存在性

---

## 3. Embedding Dimension Mismatch

### 症状
```
chromadb.errors.InvalidDimensionException: Embedding dimension 768 does not match collection dimensionality 1024
```

### 根因
创建 Chroma collection 时使用了模型 A 的 embedding 维度，但检索时使用了模型 B 生成 query embedding。例如：collection 用 bge-m3 构建（1024 维），但 query 用 bge-small 编码（512 维）。

### 排查方法

```python
# 检查 collection 的维度
collection = client.get_collection("enterprise_kb_v1")
sample = collection.get(limit=1, include=["embeddings"])
print(f"Collection embedding dim: {len(sample['embeddings'][0])}")

# 检查 query embedding 的维度
from rag.embeddings import get_embeddings
model = get_embeddings()
query_emb = model.encode(["测试"])
print(f"Query embedding dim: {len(query_emb[0])}")
```

### 修复方案

1. **临时修复**：确保检索时使用的模型与构建 collection 时一致
2. **根本修复**：在 `RagSettings` 中固定 embedding 模型配置，禁止运行时切换
3. **防御性代码**：在检索前添加维度校验：
   ```python
   assert query_embedding.shape[-1] == collection_dim, \
       f"维度不匹配: query={query_embedding.shape[-1]}, collection={collection_dim}"
   ```

### 预防措施

- 在 Chroma collection 的 metadata 中记录 `embedding_model` 和 `embedding_dim`
- `collection.get()` 时验证维度
- 切换 embedding 模型时必须重建 collection

---

## 4. persist_dir 路径错误

### 症状
- 代码运行时没有报错，但检索结果为空或数量不对
- 重启服务后之前构建的 collection "消失"了

### 原因分析

最常见的原因是**相对路径依赖 cwd（当前工作目录）**：

```python
# 危险：依赖 cwd
chroma_client = chromadb.PersistentClient(path="./storage/chroma")

# cwd = /project/ → 数据在 /project/storage/chroma
# cwd = /project/src/ → 数据在 /project/src/storage/chroma（不同位置！）
```

不同启动方式导致 cwd 不同：
- `python -m uvicorn service.service:app` → cwd = 项目根目录
- `python src/service/service.py` → cwd = src/
- IDE 调试运行 → cwd 取决于 IDE 配置
- Streamlit 运行 → cwd 取决于启动命令

### 修复方案

```python
import os
from pathlib import Path

# 方案 A：相对于项目根目录的绝对路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # 假设代码在 src/rag/config.py
persist_dir = str(PROJECT_ROOT / "storage" / "chroma_enterprise_kb_v1")

# 方案 B：从环境变量读取（推荐）
persist_dir = os.environ.get("CHROMA_PERSIST_DIR", "./storage/chroma_enterprise_kb_v1")
persist_dir = os.path.abspath(persist_dir)  # 无论输入是什么，都转为绝对路径
```

### 预防措施

- 启动日志中打印 `persist_dir` 的绝对路径
- 所有路径配置项在加载后统一做 `os.path.abspath()` 处理
- 环境变量 `CHROMA_PERSIST_DIR` 应该在项目 `.env` 中定义为绝对路径

---

## 5. 相对路径 vs 绝对路径问题

### 问题全景

| 场景 | 相对路径 | 绝对路径 |
|------|----------|----------|
| **可移植性** | 项目目录移动到其他位置后仍可用 | 换机器后需修改 |
| **可预测性** | 依赖 cwd，不同调用方式行为不同 | 始终指向同一位置 |
| **配置简洁度** | `./storage/chroma` | `E:/RAG/agent-service-toolkit-clean/storage/chroma` |
| **推荐场景** | 开发环境，启动方式固定 | 生产环境，多个进程访问 |

### 本项目采用策略

**混合策略**：
1. 配置文件使用相对路径（可移植）
2. 代码加载后立即转为绝对路径（可预测）
3. 环境变量允许覆盖（灵活）

```python
# rag/config.py 中的路径处理模式
class RagSettings(BaseSettings):
    chroma_persist_dir: str = "./storage/chroma_enterprise_kb_v1"
    model_dir: str = "./models"

    def model_post_init(self, __context):
        # 统一转为绝对路径
        self.chroma_persist_dir = os.path.abspath(self.chroma_persist_dir)
        self.model_dir = os.path.abspath(self.model_dir)
```

---

## 6. Metadata 字段缺失

### 症状
- 检索结果中 `source_id` 为空或不存在
- heading_path 显示为 `null` 或空字符串
- origin_url 缺失导致无法生成 citation

### 排查方法

```python
# 检查 collection 中 metadata 字段的完整性
results = collection.get(limit=100, include=["metadatas"])
missing_source_id = sum(1 for m in results["metadatas"] if not m.get("source_id"))
missing_heading = sum(1 for m in results["metadatas"] if not m.get("heading_path"))
print(f"缺少 source_id: {missing_source_id}/{len(results['ids'])}")
print(f"缺少 heading_path: {missing_heading}/{len(results['ids'])}")
```

### 常见原因

| 原因 | 修复 |
|------|------|
| 文档加载时未提取 metadata | 检查 `document_loader.py` 中对应格式（DOCX/PDF/Markdown）的 metadata 提取逻辑 |
| chunk 切分时 metadata 丢失 | `splitter.py` 中切分后未将父文档 metadata 传递到子 chunk |
| 插入 Chroma 时 metadata 被过滤 | Chroma `add()` 的参数中 `metadatas` 未完整传入 |
| source_registry 中该 source 的 metadata 不完整 | 检查 `source_registry.yaml` 中对应 source 的字段 |

### 修复模板

```python
# 切分器：确保 metadata 继承
def split_document(doc: Document) -> list[Document]:
    chunks = text_splitter.split_text(doc.content)
    return [
        Document(
            content=chunk,
            metadata={
                **doc.metadata,  # 继承父文档全部 metadata
                "chunk_index": i,
                "chunk_id": f"{doc.metadata['source_id']}_{i:04d}",
            }
        )
        for i, chunk in enumerate(chunks)
    ]
```

---

## 7. source_id Mapping 问题

### 问题描述

`source_id` 是连接评测数据和检索结果的桥梁。如果这条桥断了，hit_rate 一定是 0。

### 常见断裂点

**断裂点 1：命名不一致**
```yaml
# eval case 中
expected_source_ids: ["chroma_getting_started"]

# 检索结果 metadata 中
source_id: "chroma_guide"  # 不匹配！
```

**断裂点 2：source_registry 中的 id 与 chunk metadata 中的不一致**
```yaml
# source_registry.yaml
- id: chroma-docs-getting-started  # 用连字符

# chunk metadata
source_id: "chroma_docs_getting_started"  # 用下划线
```

**断裂点 3：URL 作为 source_id 时的格式差异**
```
eval: "https://docs.trychroma.com/getting-started"
metadata: "https://docs.trychroma.com/getting-started/"  # 尾部多一个 /
```

### 修复方案

1. **`_resolve_source()` 兼容函数**：同时匹配多个可能的字段名和格式变体
2. **正则化**：在比较前统一做 `.strip("/")`、`.lower()`、移除 `www.` 前缀等处理
3. **source_id 注册表**：在 `source_registry.yaml` 中为每个 source 定义 `aliases` 字段，列举所有可能出现的变体名

```python
def _resolve_source(retrieved: list[str], expected: list[str]) -> bool:
    """检查检索结果是否命中任一期望 source。做多级回退匹配。"""
    retrieved_normalized = {_normalize(s) for s in retrieved}
    for exp in expected:
        normalized = _normalize(exp)
        if normalized in retrieved_normalized:
            return True
        # 检查 aliases（从 source_registry 加载）
        for alias in SOURCE_ALIASES.get(exp, []):
            if _normalize(alias) in retrieved_normalized:
                return True
    return False

def _normalize(s: str) -> str:
    return s.strip().lower().rstrip("/")
```

---

## 8. chunk_id 重复/冲突

### 症状
- 检索结果中出现重复内容
- `collection.get()` 返回的数量与 `collection.count()` 不一致
- Chroma 警告：`Duplicate ID detected`

### 根因

Chroma 的 `add()` 方法在传入重复 `id` 时默认行为是 **upsert**（覆盖），而非报错。如果两个不同的 chunk 恰好生成了相同的 `chunk_id`，后写入的会覆盖先写入的，导致内容丢失。

### 常见的 chunk_id 生成方式及风险

| 生成方式 | 示例 | 风险 |
|----------|------|------|
| `source_id + chunk_index` | `chroma_guide_001` | 如果两个 source 的 chunk_index 重置，可能冲突 |
| `source_id + 内容 hash` | `chroma_guide_a1b2c3` | 低风险（内容相同则 id 相同，去重合理） |
| `source_id + uuid4` | `chroma_guide_f3a1-...` | 无冲突但不可复现 |

### 修复方案

推荐 **`source_id + 内容前 8 位 MD5`**：
```python
import hashlib

def generate_chunk_id(source_id: str, content: str, chunk_index: int) -> str:
    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"{source_id}_{chunk_index:04d}_{content_hash}"
```

### 排查方法

```python
# 检查是否有重复 ID
all_ids = collection.get(include=[])["ids"]
from collections import Counter
duplicates = {k: v for k, v in Counter(all_ids).items() if v > 1}
if duplicates:
    print(f"发现 {len(duplicates)} 个重复 ID: {list(duplicates.keys())[:5]}...")
```

---

## 9. heading_path 为空

### 症状
- RAG 回答的 citation 中显示"来源：无标题"
- 检索 debug trace 中 `heading_path` 全部为 `null`

### 原因排查

**步骤 1：检查源文档是否有标题层级**
```python
# 检查原始 markdown 中 # 标题
with open("source.md") as f:
    headings = [line for line in f if line.startswith("#")]
    print(f"共 {len(headings)} 个标题")
```

**步骤 2：检查 splitter 是否提取了 heading_path**
```python
from rag.splitter import MarkdownSplitter
splitter = MarkdownSplitter()
chunks = splitter.split(markdown_content)
for c in chunks[:3]:
    print(c.metadata.get("heading_path"))  # 应该非空
```

**步骤 3：检查插入 Chroma 时是否携带了 heading_path**
```python
# 在 add() 调用处打印 metadata
for doc in docs:
    print(doc.metadata.keys())  # 应包含 "heading_path"
```

### 常见原因与修复

| 原因 | 修复 |
|------|------|
| 源文档没有 markdown 标题（纯文本） | heading_path 填入文件名作为默认值 |
| PDF 解析后丢失了标题信息 | PDF 解析器需提取字体大小信息推断标题层级 |
| 切分器只在 chunk 开头有标题时记录，中间 chunk 丢失 | 让切分器维护当前 heading_path 状态，传递给下一个 chunk |
| DOCX 解析未提取 heading 样式 | DOCX 解析时检查 `paragraph.style` 中的 heading 级别 |

---

## 10. 通用 Debug 流程

### 快速诊断脚本

```python
"""检索系统快速诊断脚本，放在项目根目录运行。"""
import os, sys
sys.path.insert(0, "src")

from rag.config import RagSettings
from rag.embeddings import get_embeddings
from rag.vector_store import get_vector_store

settings = RagSettings()
print(f"1. persist_dir: {settings.chroma_persist_dir} (exists: {os.path.exists(settings.chroma_persist_dir)})")

collection = get_vector_store().collection
print(f"2. collection count: {collection.count()}")

sample = collection.get(limit=1, include=["metadatas", "embeddings"])
if sample["ids"]:
    meta = sample["metadatas"][0]
    emb = sample["embeddings"][0]
    print(f"3. sample metadata keys: {list(meta.keys())}")
    print(f"4. embedding dim: {len(emb)}")
    print(f"5. source_id: {meta.get('source_id', 'MISSING')}")
    print(f"6. heading_path: {meta.get('heading_path', 'MISSING')}")

model = get_embeddings()
test_emb = model.encode(["测试"])
print(f"7. query embedding dim: {len(test_emb[0])}")
print(f"8. dimension match: {len(test_emb[0]) == len(emb)}")

results = collection.query(query_embeddings=test_emb.tolist(), n_results=3)
print(f"9. top-3 results: {len(results['ids'][0])} docs")
for i, (doc_id, dist) in enumerate(zip(results["ids"][0], results["distances"][0])):
    print(f"   [{i}] id={doc_id}, distance={dist:.4f}")
```

将此脚本保存为 `debug_retrieval.py`，任何检索问题先跑一遍。
