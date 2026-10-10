# 开发约定

## 本地环境

使用 Python 3.11 或 3.12，建议在独立虚拟环境中运行：

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

依赖声明在 `pyproject.toml`，仓库保留 `uv.lock`，`.python-version` 指定默认 Python 3.12。使用 uv 时可执行 `uv sync --frozen --extra dev`，再运行 `uv run --frozen --extra dev python -m pytest -q`。修改依赖后更新锁文件，不提交本地虚拟环境。

模型集成测试使用注入的客户端与模拟 HTTP 响应。不要在测试中使用真实密钥，也不要依赖运行中的 API 或 Gemini 服务。

## 修改范围

- API 参数或结果有变更时同步更新 `docs/API_GUIDE.md`。
- 新增数据库迁移文件，保留已发布迁移，不通过改旧 SQL 迁移现有数据库。
- 模型输出先通过 Pydantic 校验；知识点引用和状态约束不能仅依赖提示词。
- 业务状态变更保持事务边界，后台提交需检查租约、题目版本和所有权。
- 日志不得包含密钥、图片、原始题干、学生作答或完整模型输出。
- 对行为变更增加有意义的回归测试；纯文档调整无需新增测试。

## 提交前检查

```bash
python -m pytest -q
python -m compileall -q src
python -m pip install 'hatchling>=1.25,<2'
python -m hatchling build -t wheel
```

在项目根目录执行。确认 `.env`、数据、日志及本地缓存未进入暂存区。提交说明应描述具体问题、最终行为及验证结果。项目当前没有统一格式化工具，修改时保持所在模块的风格，避免无关批量改写。

## 文档与 Git 发布

对外保留 README、API 指南、使用说明、架构、项目讲解和题目案例。设计草稿、实施计划、代码审查记录及本地验证报告仅在本地保存，相关路径已加入 `.gitignore`。业务中的复习逻辑、教师更正审计以及可复现测试仍属于产品代码和使用说明。

`.gitignore` 不会删除已经提交的历史文件。准备发布时，除检查当前文件列表，也需检查将要推送的提交历史；内部文档出现在未推送的历史中时，保留原开发分支，从已发布基线制作不包含内部文档的发布提交，不通过强制推送改写已有公共历史。

本次功能已准备 `release/daily-learning` 发布分支，使用已发布的 `origin/main` 为父提交，包含最终代码和公开文档，不包含新的内部设计、实施计划或审查报告。推送前先同步远端并确认没有新的冲突；仅在明确决定发布后执行推送。

```bash
git fetch origin
git log --oneline origin/main..release/daily-learning
git diff --stat origin/main..release/daily-learning
git ls-tree -r --name-only release/daily-learning
```

不要直接推送仍带有内部工作记录的开发分支。测试使用真实 Google SDK 配合模拟 HTTP 响应及临时 SQLite 数据库，不调用真实 Gemini；三个学段的实际教学质量、人工目录的学术完整性和生产负载仍需单独评估。
