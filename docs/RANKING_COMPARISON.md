# Jina 与 GIST-small：历史真实选文对比

临时对比工作流、实验脚本和专用测试已经清理。此处仅保留已完成实验的结论，
每日默认继续使用 `avsolatorio/GIST-small-Embedding-v0`。

[历史运行记录](https://github.com/gakakulicc/zotero-arxiv-daily/actions/runs/40449532789)
使用同一份真实快照：766 篇候选论文、431 篇经原规则筛选后的 Zotero 文献，
快照时间为北京时间 2026-10-27 12:24:58。模型修订固定，排序公式与生产环境一致。

| 比较 | Top-5 重合 | Top-10 重合 | Top-20 重合 | 全部候选 Spearman |
| --- | --- | --- | --- | --- |
| GIST 512 / Jina 512 | 4/5 | 6/10 | 15/20 | 0.88469 |
| GIST 512 / Jina 8192 | 4/5 | 6/10 | 15/20 | 0.88479 |
| Jina 512 / Jina 8192 | 4/5 | 10/10 | 20/20 | 0.999995 |

Jina 使用 `jinaai/jina-embeddings-v5-text-nano-retrieval`，两侧均沿用上游的
`document` prompt 和 `retrieval` task。本批输入按 Jina tokenizer 均未超过 512 token；
不能据此推断不同 tokenizer 的 GIST 也绝无截断。长上下文组的复用一致性检查未通过，
实际重新计算了全部输入，不能将其耗时理解为增量验证耗时。

重合度不代表准确率。目前未完成两组差异论文的完整 VLA/WAM 人工标注，
不能据此认定任何一组的推荐质量更高。GIST 已观察到的前列论文包括潜在动作预训练、
VLA 适配与长时序记忆等相关工作；这支持继续作为生产基线，不构成胜出证明。

历史报告的公开 Notice 被 GitHub 截断，完整 `comparison.json` 在该次运行的
`real-paper-selection-comparison` Artifact 中（保留 14 天，需要仓库访问权限）。
尚未取得并逐篇审阅完整名单，不能将汇总指标冒充完整质量评测。

今后复核 VLA/WAM 时，应依据摘要和方法判断直接动作策略、未来状态/动作预测、
控制与泛化的实际内容；仅出现 vision、agent 或 world model 等词不足以算直接相关。
聊天中表达的新兴趣不会自动成为排序权重，排序仍由 Zotero 文献库及原有加权规则决定。

参考：[GIST 模型卡](https://huggingface.co/avsolatorio/GIST-small-Embedding-v0)、
[Jina 模型卡](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano-retrieval)。
