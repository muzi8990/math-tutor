# 验证范围与限制

## 已执行验证

发布整理时在 Python 3.12 下执行全量离线测试：142 项通过。使用真实 Google SDK 配合 `httpx.MockTransport`，通过 FastAPI `TestClient` 验证 HTTP 契约，不需要运行服务或真实 API Key。

| 范围 | 测试文件示例 | 关注的问题 |
| --- | --- | --- |
| 配置与 CLI | `test_settings.py`, `test_cli.py` | 优先级、非法值、密钥隐藏、参数行为 |
| 模型与分析契约 | `test_tutor.py`, `test_analysis.py` | 请求 schema、结果引用、状态一致性、会话隔离 |
| API 与日志 | `test_api.py`, `test_logging.py` | 输入限制、图片处理、状态码、日志脱敏 |
| 质量检查 | `test_quality.py` | 精确计算、危险表达式拒绝、有限修复、复核失败及公式删除绕过 |
| 持久化与任务 | `test_mistake_database.py`, `test_analysis_worker.py`, `test_mistake_recovery.py` | SQL 迁移、租约、重试、版本和恢复 |
| 作答与复习 | `test_mistake_attempts.py`, `test_review_transactions.py`, `test_review_policy.py` | 幂等、提示次数、事务、跨日与教师修正 |

测试集合会随功能更新；实际结果以运行输出为准。CI 配置 Python 3.11 / 3.12，但本次本地验证只覆盖 Python 3.12。存在第三方 Starlette / AnyIO 的弃用警告，不影响本次通过结果。

## 如何复现

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

测试模拟外部响应，验证程序如何处理响应，并不能验证 Gemini 在真实题目上的识题或解题质量。

## 依赖安装验证

`uv lock --check --offline` 已通过。当前环境禁止联网，离线 `uv sync --frozen --extra dev` 因缓存缺少锁定的 `pydantic-core` wheel 未能完成；因此本次测试使用已有 Python 3.12 开发环境，不声称已验证全新环境安装。正常联网安装以及 GitHub Actions 的结果仍需首次运行确认。

## 尚未完成的评测

未调用真实 Gemini 完成本次评测，也没有公布真实准确率、成本均值、P95 延迟、吞吐量或学生学习提升数据。质量复核采用模型与有限本地规则，不能声称答案绝对正确。

若继续开发，建议建立经人工核对的题集，覆盖图片清晰度、题干完整性、年级、题型和学生错误。分别记录识别准确性、答案与步骤正确性、知识点关联、提示是否泄露答案、应澄清时是否澄清，以及每题费用与耗时；保留模型名称、提示词版本和质量策略版本。该评测集目前尚未实现。
