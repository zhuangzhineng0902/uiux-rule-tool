# 示例说明

`examples/` 目录中的所有文件，都是给本工具使用的本地 Markdown 输入示例。

这里不包含网站 URL 输入示例，也不包含网页抓取示例。

你可以直接把这些 Markdown 文件或目录作为输入源传给 [tool.py](/Users/zhuangzhineng/Documents/ai_workspace/uiux-rule-tool/tool.py:1)：

```bash
python3 ./tool.py --input ./examples/sample-guidelines.md --output-dir ./data
python3 ./tool.py --input ./examples/routing-demo --output-dir ./data
```

目录说明：

- `sample-guidelines.md`
  单文件输入示例，包含基础令牌、组件规则、全局交互和禁止项。
- `routing-demo/`
  目录输入示例，演示 `foundation-rules/`、`component-rules/`、`global-layout-rules/` 子目录如何路由到对应 CSV。

如果你要接入自己的规范文档，可以直接参考这里的 Markdown 组织方式来准备输入数据。
