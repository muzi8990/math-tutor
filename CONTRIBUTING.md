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

## Git 发布

发布目录已初始化本地 Git，尚未提交或配置远端。创建自己的空 GitHub 仓库后执行：

```bash
git status --short
git add .
git diff --cached --stat
git commit -m "Initial math tutor backend portfolio"
git branch -M main
git remote add origin <YOUR_REPOSITORY_URL>
git push -u origin main
```

将占位符替换为自己的仓库地址，仓库名和作者信息由你决定。推送后查看 Actions 是否通过，再将真实仓库链接添加到简历。
