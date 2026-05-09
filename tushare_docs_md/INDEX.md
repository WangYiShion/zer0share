# tushare_docs_md 索引说明

机器学习/检索请优先读取同目录下的 **`INDEX.json`**。

## 快速字段

| 用途                               | JSON 字段                             |
| ---------------------------------- | ------------------------------------- |
| 官方文档 `doc_id` → 本地 `data.md` | `by_doc_id`                           |
| 遍历全部条目                       | `entries`                             |
| 层级浏览（嵌套字典）               | `category_tree`，叶节点键 `__pages__` |
| 结构与生成时间                     | `_meta`                               |

## 人机用法提示

- **唯一定位文件**：`_meta.usage_for_llm_zh`
- **正文标题 ≠ 菜单名**：查「股票列表」时同时看 `menu_leaf_zh` 与 `markdown_first_heading`。
