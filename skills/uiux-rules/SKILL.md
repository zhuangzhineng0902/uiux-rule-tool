---
name: uiux-rules
description: 检索并应用本地 UI/UX 规范规则 CSV，用于 Web UI 开发。当前端代码生成前需要根据组件清单获取 UIUX 规范，或需要审查已有前端工程并输出违规规则与代码位置时使用。该 skill 默认加载全部基础规范和全局布局规范，并根据实际组件按需从 data/component-rules.csv 检索组件规范。
---

# UIUX 规范规则

## 概览

以 `data/` 目录下的三个 CSV 文件作为唯一事实来源：

- `foundation-rules.csv`：始终加载全部规则，作为颜色、字体、间距、圆角、阴影、透明度、边框等基础令牌规范。
- `global-layout-rules.csv`：始终加载全部规则，作为页面全局布局和交互行为断言。
- `component-rules.csv`：只加载用户请求或工程中实际检测到的组件规则。

使用 `scripts/uiux_rules.py` 执行确定性的规则检索和高置信度静态扫描。脚本输出是第一轮结果；对于无法通过正则或静态 CSS 完全证明的语义规则，需要继续结合代码上下文判断。

## 组件规则检索

当输入是组件清单时，运行：

```bash
python3 skills/uiux-rules/scripts/uiux_rules.py \
  --rules-dir data \
  rules-for-components \
  --components "button,input,table"
```

将筛选出的规则返回给用户，或作为前端代码生成任务的约束输入。输出必须包含：

1. 全部基础规范规则。
2. 全部全局布局规范规则。
3. 与组件清单匹配的组件规范规则。

如果组件名称有歧义，先检查 `data/component-rules.csv`，把用户侧组件名映射到最接近的 `component` 字段，再生成代码。

## 前端工程审查

当输入是前端代码工程时，运行：

```bash
python3 skills/uiux-rules/scripts/uiux_rules.py \
  --rules-dir data \
  scan-project \
  --project /absolute/path/to/frontend
```

扫描器会检查 `.css`、`.scss`、`.less`、`.html`、`.vue`、`.svelte`、`.jsx`、`.tsx`、`.js` 和 `.ts` 文件中的类 CSS 声明，并跳过构建产物和依赖目录。

扫描逻辑按规则层级处理：

- 基础规范：按基础令牌属性族检查，例如颜色、字体、间距、圆角、阴影、透明度、边框；`padding`、`margin`、`border` 等简写会先展开后比较。
- 组件规范：按组件名、状态和属性检查，并检查已使用组件是否缺少必需交互状态。
- 全局规范：只对页面全局布局类 CSS 规则做静态等值检查；`toast`、`skeleton`、二次确认、遮罩点击关闭等交互断言需要结合代码语义人工复核，不应被当作普通 CSS 值误报。
- 基础规范和全局规范允许 `property_name` 为空；这类规则用于检索和人工审查提示，不进入 CSS 属性等值比较。

将扫描结果作为高置信度问题清单。最终审查输出时：

- 每条违规都要包含规则 ID、文件、行号、实际值、期望值和原因。
- 当基础规范或全局规范属于语义规则，且代码中能明确看到违规但扫描器未捕获时，可以补充人工判断的问题。
- 不要在缺少具体规则和代码位置的情况下臆造违规项。
- 如果是缺失组件状态，把组件默认态定义所在行作为问题位置。

## 输出要求

组件规则检索结果优先按层级分组，用简洁 Markdown 输出。前端工程审查结果应先列出按严重程度或置信度排序的问题，再说明静态扫描无法证明的剩余限制，例如运行时动态样式。
