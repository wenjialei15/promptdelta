# 参与 PromptDelta

欢迎贡献新的断言、兼容服务测试、文档或报告可访问性改进。较大的功能请先开 Issue，描述真实使用场景。

## 开发验证

核心为 Python 标准库实现：

```bash
python -m unittest discover -s tests -v
python -m promptdelta demo
```

测试使用临时文件和本地模拟 HTTP 服务，不调用真实模型。改动需要覆盖实际行为：配置有误时不调用接口、错误不会当作改善、报告不会执行输出中的 HTML 等。

## 报告浏览器测试

需要 Node.js 20+。依赖仅用于开发：

```bash
npm ci
npx playwright install chromium
npm test
```

测试会生成 `reports/browser/` 并启动只读 HTTP 服务，绑定本机端口 8766。目录用于测试，不要存入真实业务报告。

Windows 上可直接用已经安装的 Edge：

```powershell
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm test
```

设置 `UPDATE_SCREENSHOTS=1` 后运行，会更新 `docs/images/` 中的桌面和手机截图。提交前打开截图检查排版。正常测试不会改动文档图片。

## 提交 PR

说明具体输入、改动前后的行为以及验证方式。示例请使用虚构数据；不要提交 API 密钥、`.env` 或真实客户记录。维持核心运行零第三方依赖，避免为单个供应商引入默认配置或隐式网络调用。
