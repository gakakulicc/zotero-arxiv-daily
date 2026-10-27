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
    max_tokens: 768
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

当前仅保留每日推送、原有手动 Test 和 Keep Alive 三个工作流。临时 CI、模型验证及
选文对比工作流已移除；本地回归测试仍可通过 `uv run pytest` 执行。

可在 **Actions → Test → Run workflow → main** 手动运行完整流程。
这个任务会读取你的 Secrets，并真实发送测试邮件；即使没有新论文也会发送一封确认邮件。
每日任务手动运行时，默认勾选 `force_send_empty`，同样可以确认发信。
定时运行仍遵循旧 `SEND_EMPTY` 设置；false 且没有新论文时正常跳过发送。

不再设置 300 分钟任务限制或 240 分钟生成预算，旧 `generation_budget_minutes` 不再生效。
GitHub 托管运行器每个 job 仍有 6 小时平台上限；网络及单篇解析的超时保留，防止个别请求卡死。
当前以信息充分和每日稳定产出为目标，说明见 [每日产出与恢复机制](DAILY_RELIABILITY.md)。

每日任务使用 `0 21 * * *`，即北京时间次日 05:00；`0 2 * * *` 为北京时间 10:00 补跑。
GitHub 实际调度可能延迟；补跑会检查当天前次定时处理的实际开始时间，不满 5 小时则等待。
等待计入平台运行额度。若当天的正式日报已获 SMTP 接受，补跑进入执行器后会跳过发信。
工作流默认在无新论文时也发确认邮件；如果已有 `SEND_EMPTY=false` Variable，仍尊重该设置。

## 更新后如何运行最新代码

已经排队或执行中的任务不会因推送更新自动换成新提交；旧任务页面的 **Re-run jobs**
也会重跑该任务原来的提交。要验证更新，请回到 **Actions → Send emails daily →
Run workflow → main** 创建一次新运行。需要少量论文的完整发信验证时可选择 **Test**。

新运行的 **Show code version** 步骤和 Summary 会显示实际检出的完整提交号。
请用它与仓库 main 的最新提交核对，而不要仅凭任务开始时间判断版本。
当前流程先排序后获取入选论文正文、缓存向量，摘要与机构分别调用本地模型。
如果日志仍然在排序前为几百篇候选逐一下载正文，或仍在 90/180/300 分钟被取消，应先核对提交号。
