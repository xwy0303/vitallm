# Leader Chat Demo

这是面向阶段性汇报的静态前端 demo，用于直观展示最终系统形态：

- 用户输入酶名称或配方问题。
- 系统返回固定化剂推荐、条件建议和证据引用。
- 右侧展示 evidence、页码、质量标记和 review queue 概念。

当前 demo 使用 B10 smoke test 的样例 evidence 做本地展示，不调用真实 LLM API。后续接入向量数据库和 LLM gateway 时，可以保留 UI，把 `app.js` 中的本地规则替换为后端 `/chat` 接口。

本地打开：

```bash
open demo/leader_chat/index.html
```
