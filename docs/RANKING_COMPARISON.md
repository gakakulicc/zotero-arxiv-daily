# 真实选文对比：Jina 与 GIST-small

本对比不会更改每日推送的默认模型，不发邮件，也不调用摘要 LLM。

## 实验条件

`Compare real paper selections` 在 GitHub runner 使用现有 Zotero Secrets，读取一次
真实文献库并应用生产环境的收藏夹包含/排除规则，同时获取一次当前订阅源的候选论文。
之后固定这份快照，避免两个模型因运行日期不同而比较了不同的论文。

三个实验组：

| 组 | 模型 | 最大输入 | 编码方式 |
| --- | --- | --- | --- |
| gist512 | avsolatorio/GIST-small-Embedding-v0 | 512 token | 原 fork 的 GIST 方式 |
| jina512 | jinaai/jina-embeddings-v5-text-nano-retrieval | 512 token | 原上游的 document prompt 与 retrieval task |
| jina8192 | 与 jina512 相同修订的 Jina | 8192 token | 与 jina512 相同，检查长摘要截断的影响 |

两个模型的 tokenizers 不同，512 是相同数值的预算，不代表逐字相同的截断。
两侧都使用文档编码，保持原上游的论文对论文计算方式；本次不额外调成 Query/Document
非对称检索，不引入新的排序公式。

为减少重复计算，jina8192 复用明显低于 512 上限的短输入向量，并抽样重算验证是否一致。
若验证失败会重算全部输入；较长输入全部按 8192 上限重算。报告会注明复用数量，因此
jina8192 的耗时是增量验证耗时，不能与两个完整冷启动耗时直接比较。

所有组使用相同的 Zotero 添加顺序权重和余弦相似度。模型修订号固定在快照中。

## 输出与判断范围

- Top-5、Top-10、Top-20 重合数量、比例和 Jaccard。
- 全部候选论文排序的 Spearman 相关系数（处理并列分数）。
- 三种配置的前 20 篇及其在其他组中的名次。
- 编码耗时、长于 512 个 Jina token 的摘要数量。
- `blind-review.csv`：不显示模型名和排名的人工评价表，0=不相关、1=部分相关、2=高度相关。

**重合度不是准确率。** 没有人工相关性标签时，不能凭分数更高、名单不同或模型更大
认定哪个更准确。不同模型的原始相似度分数也没有统一标尺。

先看差异论文是否符合研究兴趣，再依据人工标签比较 Precision@20、nDCG@20，才可以
更可靠地决定长期使用哪个模型。单日结果只能代表该批候选，不保证所有日期一致。

## 数据与报告

原始库摘要与临时向量仅保存在该次 runner 的临时目录，不上传到报告或缓存。
报告包含公开候选论文的标题、链接和排名，不包含 Zotero Key、库文献标题或摘要。
报告位于 Actions Summary 与名为 `real-paper-selection-comparison` 的 Artifact，保留 14 天。
如果订阅源当前为空，任务会明确报错并提示稍后重试，不会用合成数据替代选文验证。

## 模型定位

Jina nano retrieval 是约 239M 参数、多语言、768 维、8192-token 输入的检索模型；
GIST-small 是约 33M 参数、主要面向英文、384 维、512-token 输入的小型模型。
前者更值得检验多语言和长摘要的效果，后者更适合 CPU 预算严格的英文摘要场景。
这些是适配判断，不是本任务质量优劣的实测结论。

官方资料：[Jina 模型卡](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano-retrieval)、
[GIST 模型卡](https://huggingface.co/avsolatorio/GIST-small-Embedding-v0)、
[GISTEmbed 论文](https://arxiv.org/abs/2402.16829)、
[Jina v5 论文](https://arxiv.org/abs/2602.15547)。
