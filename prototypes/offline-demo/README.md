# 可选离线原型

先前搭建的合成示例，当前以根目录README和docs/project-plan.md为准，不要求继续开发此原型。

在本目录运行，需要Python 3.11+，无第三方依赖：

```bash
python -m app.server
python -m unittest discover -s tests -v
python scripts/export_demo.py
```

浏览器打开http://127.0.0.1:8000。120位旅客、事件、价格与余位均为合成，截点为2026-09-27 UTC，文案与SVG为模板，没有真实模型调用，触达和转化均为模拟，不代表真实业务效果。

runtime/及output/不提交Git。无企业身份认证，不可公网部署。固定演示频控重启保留，新会话使用新的`--database runtime/session-2.sqlite3`。API见根目录docs/api.md。
