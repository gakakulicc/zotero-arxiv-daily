# GitHub Actions 设置与升级说明

本 fork 已恢复直接运行本地 GGUF 模型。每日任务和手动 `Test` 任务均安装
`local-llm` 依赖；不使用 LLM API 时，无需填写 OpenAI 相关 Secrets。

## 原有设置能否继续用

在仓库 **Settings → Secrets and variables → Actions** 中查看设置名称。
GitHub 不允许读取已保存 Secret 的值；需要修改时覆盖保存即可。

以下旧 Secrets 保持兼容，不需要因为本次升级重新创建：

| Secret | 用途与兼容行为 |
| --- | --- |
| `ZOTERO_ID`、`ZOTERO_KEY` | Zotero 用户 ID 与只读 API Key，继续使用 |
| `SENDER`、`SENDER_PASSWORD` | SMTP 发件账号与授权码，继续使用 |
| `RECEIVER` | 可使用一个邮箱，或用英文/中文逗号、分号、换行分隔多个邮箱；多余分隔符和重复地址会清理 |
| `SMTP_SERVER`、`SMTP_PORT` | 继续使用；未设置时默认 `smtp.qq.com` 和 `465`，465 直接使用 SSL |
| `ARXIV_QUERY` | 原 RSS 分类格式继续使用，例如 `cs.CV+cs.LG`；多个分类转换为新版列表 |
| `MAX_PAPER_NUM` | 继续使用；正整数限制篇数，`-1` 保留“全部论文”含义 |
| `USE_LLM_API` | `false`/`0` 使用本地模型；`true`/`1` 使用 LLM API；未设置默认本地 |
| `OPENAI_API_KEY`、`OPENAI_API_BASE`、`MODEL_NAME` | 仅 LLM API 模式使用；本地模式不读取这些 LLM API 配置 |

以下旧 Variables 继续兼容：

| Variable | 用途 |
| --- | --- |
| `LANGUAGE` | 摘要语言，例如 `Chinese` |
| `ZOTERO_IGNORE` | 原有多行 gitignore 规则，保留包括 `!` 在内的旧匹配语义 |
| `SEND_EMPTY` | `true`/`1` 无新论文也发邮件；`false`/`0` 不发 |

非空的旧环境设置会覆盖对应的 YAML 字段；空值不会覆盖 YAML。若决定完全使用
`CUSTOM_CONFIG`，清理不再使用的旧设置即可避免它们继续覆盖 YAML。

## 推荐检查的设置

1. 在 **Variables** 新增 `LLM_BACKEND=local`。它优先于旧 `USE_LLM_API`，明确选择直接本地推理。
2. 确认 `RECEIVER` 只包含邮箱地址，不要混入说明文字或 `To:`、`Bcc:` 等头部。多行邮箱现在可以直接沿用。
3. 确认 `SMTP_SERVER`、`SMTP_PORT` 是你的邮件服务配置；`SENDER_PASSWORD` 应为 SMTP 授权码。
4. `CUSTOM_CONFIG` 可以不设置或留空，这时保留仓库自带配置并应用以上旧设置。
5. 如果已经配置了完整 `CUSTOM_CONFIG`，请在其中包含 `llm.backend: local`，或者设置第 1 项的 Variable。

仓库的 `REPOSITORY`、`REF` Variables 不再用于每日任务。工作流始终检出当前仓库和
当前运行的分支，以免旧配置将代码切回上游或旧版本；这两个值留存也不会生效。

若旧 `ARXIV_QUERY` 不是分类组合（例如含 `cat:`、`AND` 或任意搜索表达式），程序会
在初始化时给出提示。请改成 `cs.AI+cs.CV` 这种 RSS 格式，或移除该 Secret 后在
`CUSTOM_CONFIG` 中设置 `source.arxiv.category: [cs.AI, cs.CV]`。本工作流仍是按 RSS
分类订阅，不提供任意 arXiv 搜索表达式。

## 自定义新版配置

如要完全改用 YAML，可将以下内容保存到 **Variables → CUSTOM_CONFIG**。按需修改
分类、语言、SMTP 和论文篇数；邮箱、授权码、Zotero Key 继续从 Secrets 读取。
不要把凭据直接写进 Variables 或仓库文件。

```yaml
zotero:
  user_id: ${oc.env:ZOTERO_ID}
  api_key: ${oc.env:ZOTERO_KEY}
email:
  sender: ${oc.env:SENDER}
  receiver: ${oc.env:RECEIVER}
  sender_password: ${oc.env:SENDER_PASSWORD}
  smtp_server: smtp.qq.com
  smtp_port: 465
llm:
  backend: local
  language: Chinese
  local:
    n_ctx: 8192
    max_tokens: 512
    n_threads: 4
source:
  arxiv:
    category: [cs.AI, cs.CV, cs.LG, cs.CL]
executor:
  source: [arxiv]
  reranker: local
  max_paper_num: 5
  send_empty: false
```

其余模型文件名等参数继承 `config/base.yaml`。首次运行会下载并缓存 Qwen GGUF
和本地嵌入模型，需要更多时间；后续任务优先复用 Hugging Face 缓存。

## 如何验证

推送后 **Actions → CI** 会执行回归测试及 `Verify real local Qwen inference`。
后者会在 Ubuntu runner 下载真实 Qwen GGUF 并生成摘要，不需要任何 Secrets，
不连接 Zotero、不发送邮件。测试失败会使该任务失败，不会用摘要原文掩盖错误。

CI 成功后，可在 **Actions → Test → Run workflow → main** 手动运行完整流程。
这个任务会读取你的 Secrets，并真实发送测试邮件；即使没有新论文也会发送一封确认邮件。
每日任务手动运行时，默认勾选 `force_send_empty`，同样可以确认发信。
定时运行仍遵循旧 `SEND_EMPTY` 设置；false 且没有新论文时正常跳过发送。

工作流时限已提高到 180 分钟，并使用嵌入向量缓存及先排序后取正文的流程。
更多提速选项见 [本地运行提速配置](PERFORMANCE.md)。

每日任务的时间保持 `0 22 * * *`，即北京时间次日 06:00，GitHub 实际调度可能延迟。
