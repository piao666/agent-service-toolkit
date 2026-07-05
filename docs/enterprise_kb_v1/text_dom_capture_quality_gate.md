# Text/DOM 正式采集质量门禁

> 版本: v1 | 时间: 2026-07-05 | 适用阶段: Phase 3H+

---

## 一、门禁模型

Text/DOM 正式采集采用 **audit-driven** 模型：采集脚本产出 → audit 脚本复算 → manifest 从 audit 派生 → report 不得自述替代 evidence。

```
capture.py → raw.html + normalized.md + text_metadata.json
                  ↓
audit.py → audit.json (canonical, all stats from evidence)
                  ↓
rebaseline_generator.py → manifest.yaml + report.md + evidence_check.txt
```

---

## 二、文件存在性门禁 (G0)

| 编号 | 门禁 | 阈值 |
|------|------|------|
| G0.1 | raw.html 存在且 > 0 bytes | > 0 |
| G0.2 | normalized.md 存在且 > 0 bytes | > 0 |
| G0.3 | text_metadata.json 存在且 JSON 可解析 | JSON valid |

**FAIL**: 任一文件缺失或 JSON 不可解析 → `fetch_status=failed`

---

## 三、内容质量门禁 (G1)

| 编号 | 门禁 | 检测方法 | 阈值 |
|------|------|----------|------|
| G1.1 | raw.html 非空页面 | raw.html > 500 bytes | > 500 |
| G1.2 | normalized.md 非空 | 去除 front matter 后正文 > 100 chars | > 100 |
| G1.3 | 页面标题存在 | normalized.md 含 H1 或 front_matter.title | ≥ 1 |
| G1.4 | 非错误页面 | raw.html 不含 `<title>404` / `Error` / `Page not found` | 不含 |

---

## 四、结构完整性门禁 (G2)

| 编号 | 门禁 | 检测方法 |
|------|------|----------|
| G2.1 | 标题保留 | heading_count > 0 |
| G2.2 | 正文保留 | 段落文本 > 500 chars |
| G2.3 | 链接保留 | link_count > 0 (文档页必有链接) |
| G2.4 | 代码块保留 | 如 allowlist 声明含 code_api_config → code_block_count > 0 |

---

## 五、格式门禁 (G3)

| 编号 | 门禁 | 检测方法 |
|------|------|----------|
| G3.1 | front matter 存在 | `---` 包裹的 YAML header |
| G3.2 | 无 legacy [code] 标签 | `[code]` / `[/code]` count = 0 |
| G3.3 | 无空标题 | `^#{1,6}\s*$` count = 0 |
| G3.4 | 无零宽字符 | U+200B/U+200C/U+200D/U+FEFF 已 strip |

---

## 六、专项门禁 (G4)

| 编号 | 门禁 | 适用条件 | 检测方法 |
|------|------|----------|----------|
| G4.1 | 表格保留 | allowlist 声明含表格的页面 | table_count ≥ 1 (HTML table tag 计数) |
| G4.2 | Operator 保留 | Chroma metadata 页面 | `$eq`, `$gte`, `$in` exact token 存在 |
| G4.3 | 代码示例完整 | 所有声明含 code_api_config 的页面 | 代码块含 `import` / `from` / `def` 关键字 |

---

## 七、综合判定

| 判定 | 条件 |
|------|------|
| ✅ PASS | G0-G3 全部通过，G4 适用项通过 |
| ⚠️ PASS_WITH_LIMITATIONS | G0-G3 全通过，G4 部分适用项失败 |
| ❌ FAIL | 任一 G0 或 G1 失败 |

**FAIL 的 source 不进 Chroma。PASS_WITH_LIMITATIONS 的 source 可入库但标注 warning。**

---

## 八、禁止事项

| 禁止 | 理由 |
|------|------|
| Report 自述替代 evidence | 所有指标必须从 audit.json 复算 |
| 预写 PASS 结论 | 门禁判定必须来自 audit 脚本输出 |
| 人工修改 audit.json | audit.json 只能由 audit.py 生成 |
