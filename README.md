# UI/UX 规范规则生成工具

`uiux-rule-tool` 用来读取本地 Markdown 文件或目录，并把抽取出的原子化 UI/UX 规范写入 `data/` 目录下的 CSV 文件。

## 生成结果

生成后的 CSV 是唯一事实来源：

| 文件 | 覆盖范围 | 前缀 |
| --- | --- | --- |
| `data/foundation-rules.csv` | 基础令牌规范，如颜色、字体、间距、圆角、阴影等 | `FDN` |
| `data/component-rules.csv` | 组件规范，包含 hover、focus、active、disabled、error、open、selected 等状态完整性 | `CMP` |
| `data/global-layout-rules.csv` | 全局布局与交互断言，包含响应式行为和页面类型前缀 | `LAY` / `DET` / `LST` / `CRE` / `APV` |

CSV 中每一行都必须是原子规则，只描述一个属性。

为兼容 Excel 等表格工具中的中文显示，生成的 CSV 会使用带 BOM 的 `UTF-8` 编码。

## 输出字段

每条 CSV 规则包含以下字段：

- `rule_id`
- `prefix`
- `layer`
- `page_type`
- `subject`
- `component`
- `state`
- `property_name`
- `condition_if`
- `then_clause`
- `else_clause`
- `default_value`
- `preferred_pattern`
- `anti_pattern`
- `evidence`
- `source_ref`

和需求直接对应的关键字段有：

- `rule_id`
- `default_value`
- `preferred_pattern`
- `anti_pattern`

## 主要能力

- 仅支持本地 Markdown 文件 / 目录作为输入。
- 支持混合抽取流程：Python 负责编排与落盘，未知输入可按需调用 OpenAI 模型做语义抽取。
- 当 Markdown 输入目录中包含 `foundation-rules/`、`component-rules/`、`global-layout-rules/` 子目录时，会自动路由到对应 CSV。
- 会把 `padding`、`margin`、`border` 等 CSS 简写自动展开为原子规则。
- 会把规则分层为 foundation、component、global 三层。
- 会从选择器中识别组件状态，并在必要时补出缺失状态规则。
- 会把显式条件文本和响应式媒体查询转换成 `If / Then / Else` 断言。
- 会识别 `禁止`、`不得`、`avoid`、`must not` 等禁止项表达，并写入 `anti_pattern`。

## 快速开始

```bash
python3 ./tool.py --input ./examples/sample-guidelines.md --output-dir ./data
```

所有运行时配置都集中在 [config/ai.toml](config/ai.toml) 中，包括输入源、输出目录、抽取策略和 OpenAI 设置。

最小配置示例：

```toml
[input]
sources = ["./examples/sample-guidelines.md"]

[output]
directory = "./data"

[openai]
api_key = ""
base_url = "https://api.openai.com/v1"
model = "gpt-5.4-mini"
api_style = "auto"

[extraction]
strategy = "auto"
```

当 `config/ai.toml` 里已经配置好 `input.sources` 和 `output.directory` 后，可以直接无参运行：

```bash
python3 ./tool.py
```

`[openai].api_style` 当前支持以下枚举值：

- `auto`
  默认值。优先尝试 `Responses API`；如果当前服务端不支持该接口，或只兼容 OpenAI 的 `Chat Completions API`，则自动切换到 `chat/completions`。在 `chat/completions` 下，会先尝试 `response_format + json_schema`，失败后再自动回退到纯文本 JSON 模式。
- `responses`
  强制使用 `Responses API`，请求路径为 `/responses`。
- `chat_completions`
  强制使用兼容 OpenAI 的 `Chat Completions API`，请求路径为 `/chat/completions`。会先尝试结构化 `json_schema` 输出，若服务端不支持，则自动再试一次纯文本 JSON 兜底。

`[extraction].strategy` 当前支持以下枚举值：

- `auto`
  优先尝试 LLM 抽取；当 `config/ai.toml` 中存在非空 `openai.api_key` 时，会调用 OpenAI 结构化抽取；如果未配置 key，或 LLM 抽取失败，则自动回退到内置启发式抽取。
- `heuristic`
  强制使用内置启发式抽取，不调用 LLM，适合离线、低成本或追求可复现性的场景。
- `llm`
  强制使用 LLM 抽取；如果没有配置 `openai.api_key`，或调用失败，会直接报错，不会自动回退。

## LLM 抽取逻辑

当输入走 LLM 抽取时，代码里的提示词会要求模型遵守以下规则：

1. 规则必须原子化，每条规则只描述一个属性。
2. 规则必须分到 `foundation`、`component`、`global` 三层之一。
3. 只要规则带条件，`condition_if`、`then_clause`、`else_clause` 就必须使用 `If / Then / Else` 结构。
4. `component` 层必须关注不同交互状态下的视觉参数。
5. `global` 层必须把动态行为转换成逻辑断言，例如触发条件、关闭逻辑、反馈位置。
6. 必须主动寻找禁止项，并写入 `anti_pattern`。
7. 只输出有明确证据支持的规则，没有证据不要猜。
8. 所有字段都必须返回字符串；不适用时返回空字符串。
9. `source_ref` 必须使用输入文档的 `location`；`evidence` 必须是简短证据摘要，不能长段复制原文。
10. 如果输入文档已经限定了层级，就只输出对应层级数组，其余层级返回空数组。
11. 文档里只要出现具体的颜色值、像素值、百分比、字号、行高、圆角、阴影、间距等明确数值，就优先总结成规则。
12. 文档里如果出现 `必须`、`禁止`、`避免`、`建议`、`应该`、`最多只能`、`当...时`、`少于或等于`、`不超过`、`间距`、`等分` 等措辞或同义表达，就优先总结成规则。
13. 遇到 Markdown 表格时，必须结合表头和单元格内容一起理解；表头定义字段语义，单元格值必须和对应表头配对后再总结规则。
14. 规则内容必须用中文描述；只有 `If / Then / Else`、原始颜色值、原始像素值、组件名、技术字段名等必须保留的字面量可以直接保留。
15. 如果文档里有很多同类型的颜色值、像素值、百分比等罗列值一起出现，且没有涉及用途、使用场景、适用场景，这会被视为一个“枚举值集合”；模型需要把这组同类型原始值汇总成一条“只能从这些枚举值中选择其一”的规则，并保留完整原始枚举值。
16. 如果文档里涉及用途、适用场景、使用场景等描述，模型必须按每个用途或场景分别总结规则，并把对应的用途或场景写进 `condition_if` 的 `If` 条件里。

当 `Chat Completions API` 进入纯文本 JSON 兜底模式时，还会额外要求模型：

1. 只返回一个合法 JSON 对象，不附加解释。
2. 不要输出 Markdown 代码块，不要输出前后说明文字。
3. 顶层字段必须是 `foundation_rules`、`component_rules`、`global_rules`。

## 输入模式

本地输入示例：

```toml
[input]
sources = [
  "./examples/sample-guidelines.md",
  "./examples/routing-demo/mixed.md",
]
```

输入规则有以下约束：

- 支持传入一个或多个本地 Markdown 文件 / 目录。
- 不支持网站 URL；如果需要处理网页内容，请先整理为本地 Markdown 再运行。
- 如果输入的 Markdown 根目录名就是 `foundation-rules`、`component-rules`、`global-layout-rules` 之一，则该目录下遍历到的文件会全部强制写入对应的同名 CSV。
- 如果目录名未命中上述目标名，则系统会逐个文件按内容语义判断，分别生成到 foundation、component、global 对应的 CSV 中。
- 如果同一个文件被重复传入，或者既传了目录又传了该目录中的文件，系统会自动去重，避免重复解析。

## 目录命名路由规则

当输入源是本地 Markdown 目录时，系统会先遍历目录中的文件，再决定每个文件应该落到哪个 CSV：

1. 如果输入根目录名命中目标文件名：
   例如输入目录是 `component-rules/`，则该目录下所有 Markdown 文件都会强制写入 `component-rules.csv`。
2. 如果输入根目录名没有命中目标文件名：
   则会继续看子目录名。像 `foundation-rules/`、`component-rules/`、`global-layout-rules/` 这样的子目录，会把目录中的文件强制路由到对应 CSV。
3. 如果某个文件既不在命名目录下，输入根目录名也未命中：
   则这个文件会按内容语义自动判断该写入 `foundation-rules.csv`、`component-rules.csv` 还是 `global-layout-rules.csv`。

可以直接用仓库里的示例目录验证：

```text
examples/routing-demo/
  foundation-rules/
    tokens.md
  component-rules/
    button.md
  global-layout-rules/
    layout.md
  mixed.md
```

这个示例目录的行为是：

- `foundation-rules/tokens.md` 会强制写入 `foundation-rules.csv`
- `component-rules/button.md` 会强制写入 `component-rules.csv`
- `global-layout-rules/layout.md` 会强制写入 `global-layout-rules.csv`
- `mixed.md` 不在命名目录下，因此会按内容语义自动分流

对应命令：

```bash
python3 ./tool.py --input ./examples/routing-demo --output-dir ./data
```

如果你只输入某个命名目录本身，也会全部强制写到对应 CSV：

```bash
python3 ./tool.py --input ./examples/routing-demo/component-rules --output-dir ./data
```

## 常用运行方式

安装为本地可执行命令：

```bash
python3 -m pip install -e .
uiux-rule-tool --input ./examples/sample-guidelines.md --output-dir ./data
```

以本地 Markdown 目录为输入：

```bash
uiux-rule-tool --input ./examples/routing-demo --output-dir ./data
```

以多个本地 Markdown 文件为输入：

```bash
python3 ./tool.py \
  --input ./examples/sample-guidelines.md \
  --input ./examples/routing-demo/mixed.md \
  --output-dir ./data
```

以单个本地 Markdown 文件为输入：

```bash
python3 ./tool.py --input ./examples/sample-guidelines.md --output-dir ./data
```

显式使用 LLM 抽取：

```bash
python3 ./tool.py \
  --config ./config/ai.toml \
  --extractor llm \
  --llm-model gpt-5.4-mini
```

如果保持 `auto` 模式，那么只有当 `config/ai.toml` 中存在非空的 `openai.api_key` 时，才会优先走 LLM 抽取；否则会自动回退到内置启发式抽取：

```bash
python3 ./tool.py
```

## 调试排查

当使用 LLM 抽取时，程序会自动把每个文档的中间结果写到输出目录下的 `debug/llm/` 中，便于排查“模型明明返回了 JSON，但规则没有写进 CSV”的情况。

目录结构示例：

```text
data/
  debug/
    llm/
      doc-001/
        meta.json
        request.json
        raw-response.json
        payload.json
        dropped-rules.json
        output-text.txt
```

排查时可以重点看：

- `payload.json`
  模型最终返回并被程序解析后的 JSON。
- `dropped-rules.json`
  被过滤掉的规则及原因，例如缺少 `subject`、`property_name`。
- `meta.json`
  当前文档保留了多少条规则、丢弃了多少条规则，以及是否发生了接口回退。

补充说明：

- `default_value` 允许为空，系统会优先保留规则本身，不会因为 `default_value` 为空就直接过滤掉该规则。

结构化 Markdown 目录示例：

```text
docs/
  foundation-rules/
    tokens.md
  component-rules/
    button.md
  global-layout-rules/
    layout.md
```

## 说明

- `--input`、`--output-dir` 都是可选覆盖项；如果不传，会从 `config/ai.toml` 中读取 `input.sources`、`output.directory`。
- 当前版本只支持本地 Markdown 文件和目录输入，不支持网站 URL。
- 为了兼容旧配置，`input.source` 仍然可用，但推荐统一使用 `input.sources`。
- 在 `auto` 模式下，如果 `config/ai.toml` 中配置了 `openai.api_key`，会优先使用 OpenAI Responses API 的结构化输出；否则自动回退到启发式抽取器。
- `openai.api_style = "auto"` 时，会优先走 `Responses API`，失败后自动尝试兼容 OpenAI 的 `Chat Completions API`。
- OpenAI 集成同时支持 `Responses API` 和兼容 OpenAI 的 `Chat Completions API`；其中 `chat_completions` 模式会在 `json_schema` 不可用时自动回退到纯文本 JSON。
- 当前版本不会执行浏览器中的 JavaScript，动态行为主要通过文本、CSS 状态选择器和交互描述进行推断。
- `examples/` 目录自带一个最小示例 Markdown，便于端到端验证整条流水线。
