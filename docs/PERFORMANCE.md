# 本地运行的提速配置

## 已实施的优化

- 默认嵌入模型恢复为这个 fork 原来使用的 `avsolatorio/GIST-small-Embedding-v0`。
  它是小型英文嵌入模型；替换模型可能改变推荐排序，但按 Zotero 添加时间加权的规则不变。
- RSS 阶段只处理标题、摘要等元数据。先排序、截取需要发送的篇数，再为入选论文获取
  TeX/HTML/PDF 正文。没有入选的论文不再下载正文，也不再逐篇无条件等待一秒。
- 本地嵌入向量缓存到 `.cache/embeddings`。缓存键包含模型、编码选项、最大输入长度和
  文本的 SHA-256；摘要修改或更换模型时自动重新计算。文件保存哈希和向量，不保存摘要原文。
  不变的 Zotero 文献不用每天重算；缓存不可用时仍可正常计算。
- 本地摘要与机构信息合并为一次请求，并使用 JSON 约束输出。仍保留原来的 Qwen 3B、
  `n_ctx=8192`、`max_tokens=512`，默认输入预算为 4000 个模型 token，分别为摘要、方法、
  实验和结论节选保留空间。更多信息见 [每日产出与恢复机制](DAILY_RELIABILITY.md)。
- 每日与手动任务的运行上限为 300 分钟；日志记录排序、正文/生成和总耗时。

GitHub Actions 会缓存模型与计算得到的向量。首次运行仍需下载模型、计算向量；后续
运行的效果取决于缓存是否命中和新增文献数量。自定义 `cache_dir` 时也需要自行调整
工作流的缓存路径。自定义 `CUSTOM_CONFIG` 中显式指定的模型仍会覆盖新的默认值。

## 保留推荐质量的基本配置

以下是可合并到完整 `CUSTOM_CONFIG` 的片段，不是独立的完整配置。

```yaml
reranker:
  local:
    model: avsolatorio/GIST-small-Embedding-v0
    max_seq_length: 512
    batch_size: 32
    cache_dir: .cache/embeddings
    encode_kwargs: {}
executor:
  fetch_full_text: true
  combine_llm_requests: true
llm:
  backend: local
  local:
    input_tokens: 4000
    n_ctx: 8192
    max_tokens: 512
```

如果显式选择 Jina 等其他模型，请使用该模型需要的编码参数。GIST 不使用 Jina 的
`task: retrieval` 和 `prompt_name: document`。可将 `cache_dir` 设为 null 禁用向量缓存。
把 `combine_llm_requests` 设为 false 可恢复单独生成摘要和机构信息的方式。

## 进一步加速的取舍

| 方法 | 如何配置 | 取舍 |
| --- | --- | --- |
| 减少发送篇数 | 原 Secret `MAX_PAPER_NUM=5`，或 YAML `executor.max_paper_num: 5` | 减少生成和正文下载次数；会少发论文 |
| 仅使用摘要 | `executor.fetch_full_text: false` | 跳过正文下载；无法可靠获得正文中的作者机构，摘要细节更少 |
| 缩短嵌入输入 | `reranker.local.max_seq_length: 256` | 对长摘要会截断更多内容，可能改变排序 |
| 更长上下文 | `llm.local.input_tokens: 4000` | 可提供更多正文，速度会下降；不是单纯提高 n_ctx 就会读入更多正文 |
| 更小的本地 GGUF | 修改 `llm.local.repo_id` 和 `filename`，或 `model_path` | 通常减少内存和计算，但需要验证摘要与 JSON 输出质量 |
| 嵌入或 LLM API | `executor.reranker: api` 或 `llm.backend: api`，再设置对应凭据 | 可将计算移到服务端；可能收费，会向服务提供方发送相应文本 |
| 自有 GPU runner/本地服务 | 在自己的 GPU 机器运行任务，或连接其兼容 API | 需要维护设备、驱动和运行环境；不需要购买外部 LLM API |
| ONNX/OpenVINO | 按 Sentence Transformers 文档另行配置导出与推理后端 | CPU 上有进一步优化空间，需增加依赖并验证结果；本次没有启用 |

你的非空旧 Secret `MAX_PAPER_NUM` 仍优先于 YAML。本次优化没有擅自缩减已配置的篇数。
GitHub 上的普通 `ubuntu-latest` 任务在 CPU 上运行，不会自动使用你的电脑或 GPU。

## 如何看测量结果

CI 的真实模型任务会执行 `scripts/check_performance.py`，在 runner CPU 上为 350 篇
合成候选摘要和 456 篇合成库摘要计算嵌入，再读取缓存重算相似度。结果显示在 CI Summary
和 `CPU embedding benchmark` Notice 中。首次计时包含模型加载；第二次会验证缓存结果
与首次结果一致。这是同规模的合成数据基准，不能视为你的真实文献库完整耗时保证。

参考：[GIST 模型说明](https://huggingface.co/avsolatorio/GIST-small-Embedding-v0)、
[Sentence Transformers CPU 推理优化](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)、
[GitHub runner 文档](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
