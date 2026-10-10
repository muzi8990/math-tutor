# Math Tutor Python

本项目使用 Gemini 直接读取题目图片并返回文字。

支持图片识题、文字问答、学生步骤检查、完整解答、启发式提示，以及内存中的多轮对话。默认使用简体中文，可指定小学年级。

支持 `analyze_problem()` 返回 Pydantic 类型 `ProblemAnalysis`：核心知识点、细分知识点、逐步解答、每步涉及的知识点及应用说明。

## 安装与配置

需要 Python 3.11 或以上；本项目在 Python 3.12 下完成离线测试。

```bash
cd math-tutor-python
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

编辑 `.env`，填入你自己的 `GOOGLE_API_KEY`。`GEMINI_MODEL` 默认沿用原项目的 `gemini-2.5-flash`；请改成你账号可用的模型名。模型可用性未通过真实服务验证，代码不绑定具体模型版本。

配置统一由 `pydantic-settings` 的 `Settings` 管理。命令行和 Python 库默认读取当前目录 `.env`，不向进程环境写入配置。优先级为：显式参数 > 环境变量 > `.env` > 默认值。同一来源内，`GOOGLE_API_KEY` 优先于兼容名称 `GEMINI_API_KEY`。

CLI 通过 `--env-file` 指定文件；Python 使用 `Settings(_env_file="custom.env")`，或用 `Settings(_env_file=None)` 禁用 dotenv 文件读取（仍读取环境变量）。共享 `.env` 中不属于本项目的字段会被忽略。

| Python 字段 | 环境变量 | 默认值 / 校验 |
| --- | --- | --- |
| `api_key` | `GOOGLE_API_KEY` / `GEMINI_API_KEY` | 无默认值，实际调用前必需，`SecretStr` 隐藏显示 |
| `model` | `GEMINI_MODEL` | `gemini-2.5-flash`，非空 |
| `grade` | `TUTOR_GRADE` | 未指定，指定时为 1–6 |
| `max_turns` | `TUTOR_MAX_TURNS` | 30，正整数 |
| `timeout_ms` | `TUTOR_TIMEOUT_MS` | 60000，正整数，毫秒 |
| `temperature` | `TUTOR_TEMPERATURE` | 0.1，范围 0–2 |
| `max_output_tokens` | `TUTOR_MAX_OUTPUT_TOKENS` | 4096，正整数 |

`Settings` 创建后不可修改；需要改变配置时创建新实例。传入 `MathTutor(settings=...)` 后，非 `None` 的兼容参数 `api_key`、`model`、`grade`、`max_turns` 可覆盖对应配置并重新校验；`None` 表示不覆盖。外部注入 `client` 时，客户端自身的密钥和网络超时设置由调用者负责。

## 命令行

```bash
# 文字提示
math-tutor '24块饼干平均分给6人，每人几块？' --grade 3

# 图片题目并继续多轮对话；把路径替换为实际图片
math-tutor --image '/绝对路径/题目.jpg' --grade 3 --chat

# 完整解答
math-tutor '请分步解答' --image '/绝对路径/题目.png' --mode solve

# 只识别图片文字与已有笔迹
math-tutor --image '/绝对路径/题目.png' --mode read

# 检查学生步骤
math-tutor '24÷6=5，我哪里错了？' --mode check

# 核心/细分知识点与关联解题步骤，输出 JSON
math-tutor '请分析这道题' --image '/绝对路径/题目.png' --grade 3 --analyze
```

也可以使用 `python -m math_tutor`。交互模式中 `/reset` 清空上下文，`/quit` 退出。`--mode` 在当前交互会话中保持不变；同一会话追加新图片或逐轮切换模式可使用 Python 接口。

## FastAPI 服务

完整接口调用顺序、参数、响应和错误处理见 [接口使用说明](API_GUIDE.md)。

更新安装依赖，然后在项目目录启动（确保 `.env` 中已填入 Gemini Key）：

```bash
python -m pip install -e .
python -m uvicorn math_tutor.api:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000/docs`，可在 Swagger 中直接上传图片和调用接口。开发时可追加 `--reload`，但重载会丢失内存会话。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 进程存活检查，不检查模型可用性 |
| POST | `/v1/analyze` | JSON 文字或 base64 图片，返回 `ProblemAnalysis` |
| POST | `/v1/analyze/image` | multipart 图片上传，返回 `ProblemAnalysis` |
| POST | `/v1/sessions` | 创建独立辅导会话，返回 `session_id` |
| POST | `/v1/sessions/{session_id}/messages` | JSON 作答，返回文字 `answer` 和 `turn_count` |
| POST | `/v1/sessions/{session_id}/messages/image` | 上传作答图片并继续辅导 |
| POST | `/v1/sessions/{session_id}/reset` | 清空会话历史 |
| DELETE | `/v1/sessions/{session_id}` | 关闭会话并释放资源 |

结构化文字分析：

```bash
curl http://127.0.0.1:8000/v1/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text":"24块饼干平均放进6个袋子，每袋几块？","grade":3}'
```

图片分析（替换图片路径）：

```bash
curl http://127.0.0.1:8000/v1/analyze/image \
  -F 'image=@/绝对路径/题目.jpg' \
  -F 'text=请分析这道题' \
  -F 'grade=3'
```

创建并继续辅导会话：

```bash
curl http://127.0.0.1:8000/v1/sessions \
  -H 'Content-Type: application/json' -d '{"grade":3}'

# 将 SESSION_ID 替换为上一步返回的 session_id
curl http://127.0.0.1:8000/v1/sessions/SESSION_ID/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"24块平均分成6份，我该怎么想？","mode":"hint"}'

curl http://127.0.0.1:8000/v1/sessions/SESSION_ID/messages/image \
  -F 'image=@/绝对路径/作答.jpg' -F 'text=检查我的步骤' -F 'mode=check'

curl -X POST http://127.0.0.1:8000/v1/sessions/SESSION_ID/reset
curl -X DELETE http://127.0.0.1:8000/v1/sessions/SESSION_ID
```

JSON 图片字段为 `image_data_url`；HTTP 接口不接受服务器本地文件路径。年级在分析请求或创建会话时指定，消息中不改变年级。请求体最多 14 MiB，图片最多 10 MiB，图片内容也经过格式与像素校验。模型调用在线程池执行，不阻塞异步事件循环。

错误码：输入校验 422，图片类型不支持 415，大小超限 413，会话不存在 404，轮数耗尽 409，上游模型错误 502，配置缺失或会话容量满 503。

会话目前仅在内存中保存，最多 `TUTOR_SERVICE_MAX_SESSIONS`（默认100）个，关闭会话后释放；没有自动过期机制，请调用 DELETE 清理。使用单个 Uvicorn worker，服务重启会丢失会话。当前是本地开发服务，没有用户鉴权；对外提供多人服务需要接入身份鉴权和持久化会话存储。

## Loguru 日志

FastAPI 启动时配置 Loguru：终端输出可读日志，文件输出 JSON 日志。默认文件为项目运行目录下的 `logs/math-tutor.log`，单文件 10 MB 轮转，保留 7 天。`diagnose` 和 `backtrace` 均关闭，不打印局部变量或原始异常载荷。

```dotenv
TUTOR_LOG_LEVEL=INFO
TUTOR_LOG_FILE=logs/math-tutor.log
```

修改配置后重启服务。需要更多模型请求起始信息时设为 `DEBUG`；使用 Python 的 `Settings(log_file=None)` 可关闭文件日志。CLI/库使用 Loguru 默认控制台日志；文件配置在 FastAPI 生命周期中启用。

记录的信息：

- `http.complete`：服务器生成的 `request_id`、请求方法、路由模板、HTTP 状态和耗时。
- `model.success`：模型名称、结构化输出模式、消息数量、耗时、响应字符数及供应商返回的 token 用量。
- `model.error`：Gemini HTTP 状态和经过脱敏、限制长度的具体错误消息，例如 JSON Schema 参数不支持。
- `model.network_error`、`model.incomplete`、`model.empty`：连接失败、截断/拦截、空响应。
- `analysis.invalid`：结构或知识点引用校验失败；只记录错误数量，不记录原始分析内容。
- 服务启动、关闭和配置缺失。

每个 HTTP 响应包含 `X-Request-ID`，可据此关联请求与模型日志。日志不主动记录请求正文、响应正文、图片、题目、学生对话、密钥或 URL 查询参数；对供应商错误消息里的已知密钥、完整输入文本和图片载荷做替换。供应商错误可能包含其他字段值，因此日志文件仍应限制访问。

查看日志：

```bash
tail -f logs/math-tutor.log
```

HTTP 400 的具体诊断信息放在服务端 `model.error` 日志中；客户端仍收到通用错误，避免把供应商内部信息直接暴露给用户。使用相同的请求编号查询即可定位。

测试使用本机已有 Loguru 0.6.0 完成，依赖声明支持 `>=0.6,<1`；本环境无法连接 PyPI，因此没有在线安装新版本或调用真实 Gemini。

## Python 调用

```python
from math_tutor import MathTutor, Settings

settings = Settings(grade=3)  # 自动读取环境变量及当前目录 .env
with MathTutor(settings=settings) as tutor:
    # 默认 hint：优先启发式提示
    print(tutor.chat('帮我理解题意', image='/绝对路径/题目.jpg'))
    print(tutor.chat('我认为应该用除法'))
    print(tutor.chat('这是我的步骤', image='/绝对路径/作答.jpg', mode='check'))
    print(tutor.chat('请完整解释', mode='solve'))
    tutor.reset()
```

`image` 接受 `str`/`pathlib.Path` 本地路径，或 PNG/JPEG/WebP 的 base64 data URL，不接受远程 URL。`analyze_image(image)` 独立识题，不修改当前对话。图片先做格式校验、EXIF 方向纠正并移除元数据，再发送至模型服务。

## 结构化知识点与解题步骤

```python
from math_tutor import MathTutor, Settings

with MathTutor(settings=Settings(grade=3)) as tutor:
    analysis = tutor.analyze_problem(
        "24块饼干平均放进6个袋子，每袋几块？"
        # 也可通过 image="/绝对路径/题目.jpg" 传入照片
    )
    print(analysis.model_dump_json(indent=2))
    points = {
        p.id: p.name for p in [
            *analysis.core_knowledge_points,
            *analysis.detailed_knowledge_points,
        ]
    }
    for step in analysis.steps:
        print(step.index, step.description, step.formula)
        print("涉及知识点：", [points[id_] for id_ in step.knowledge_point_ids])
        print("应用说明：", step.knowledge_application)
```

返回字段：

| 字段 | 内容 |
| --- | --- |
| `status` | `solved`、`needs_clarification` 或 `unsupported` |
| `problem_text` | 识别并整理的题干和条件 |
| `core_knowledge_points` | 核心概念或方法，包含 `id`、`name`、`description` |
| `detailed_knowledge_points` | 细分技能，额外包含指向核心知识点的 `parent_id` |
| `steps` | 连续步骤编号、文字解释、可选算式、知识点引用及应用说明 |
| `answer` | 最终答案，待确认或不支持时为 null |
| `clarifications` | 待确认问题或不支持的原因 |

模型通过 Gemini JSON schema 生成结构化输出，随后由 Pydantic 校验字段及跨对象引用。重复知识点编号、悬空引用、不连续步骤，以及待确认却给出答案的结果会抛出 `TutorError`；无法可靠关联的步骤可使用空引用列表并说明原因。

这是完整题目分析，可能包含最终答案。它不写入辅导会话历史；希望继续讨论时，使用 `chat()` 提供题目/图片，或明确传入已确认的分析内容。普通 `chat()` 和 `analyze_image()` 仍返回文字。

知识点 id 只在单次结果内有效，名称属于模型生成的候选标注，不是教材官方编码；需要跨题统计时，应映射到你们维护的知识点目录。结构校验不能证明数学答案和知识点分类一定正确。

每个学生会话创建独立实例，不要跨学生共用。历史及图片仅保存在进程内存中，`reset()` / `close()` 清除本地上下文；这不代表删除供应商端记录。一个实例内的调用串行执行。默认最多 30 轮，达到上限明确要求重置，避免静默丢失原题。网络错误、空响应、截断响应不进入历史。

图片原始及标准化后大小上限均为 10 MiB，像素上限 1600 万，仅接受单帧图片。建议裁剪到相关题目和作答。后续每轮会重发保留的图片与历史，需要计入模型调用费用和上下文预算。

## 迁移对应关系

| 原 TypeScript 文件 | Python 处理 |
| --- | --- |
| `main.ts` | `cli.py` 和 `__main__.py`，普通 Python 入口 |
| `agent.ts` | `agent.py`，Gemini 对话与会话管理 |
| `canvas_vision.ts` | `analyze_image()` 与 `images.py`，直接读取图片 |
| `canvas_solution.ts` | `chat(mode='solve')`，输出文字步骤 |
| `tutor.ts` | `prompts.py`，中文教学规则与任务模式 |
| `text_input.ts` | `chat()` 和 CLI 交互循环 |
| `pipeline.ts` / `canvas_bridge.ts` / `canvas_protocol.ts` | 已移除 |

原项目中依赖白板结构、目标 shape 和坐标的少数方程规则没有逐行移植；这一版统一由模型解题，不提供独立确定性验算器。这样避免把白板专用逻辑带入纯图片/文字接口。与原项目相比，看图和回答合并为一次模型请求；独立识题是可选操作。

这是可嵌入的 Python 模块、CLI 和 FastAPI 服务，不包含数据库、用户鉴权或长期学情管理。提示模式依赖模型遵循指令，并非答案泄露的强制保证；模型数学正确性与教学效果仍需实题评测。

## 测试与构建

```bash
python -m pytest
python -m pip wheel . --no-deps --wheel-dir dist
```

测试使用真实 Google SDK，并通过 HTTPX 的离线 transport 替换远程 HTTP 请求，验证图片载荷、多轮历史、失败回滚、重置、输入校验和 CLI。无需 API Key，不调用计费模型。

本次离线验证使用 `google-genai 2.29.0`、`Pillow 12.3.0`、`pydantic-settings 2.15.0`。配置测试覆盖来源优先级、密钥别名和隐藏显示、字段校验及 CLI 文件覆盖。未使用真实 API Key 进行联网生成测试，不能将离线测试视为模型效果验证。

## 错题管理

新增持久化错题本，复用 Gemini 分析。支持图片收录、列表详情、题干修正、删除、分析重试、作答历史、错因诊断、提示、今日复习和统计。错题与图片保存在本地 `data/`，服务重启后仍在。

### 启动

安装新版本后，在项目根目录执行：

```bash
python -m pip install -e .
```

首次本地调试，在 `.env` 中设置（不要直接复制覆盖已有密钥）：

```dotenv
TUTOR_ENABLE_LOCAL_IDENTITY=true
TUTOR_LOCAL_STUDENT_ID=11111111-1111-4111-8111-111111111111
```

这两个配置仅用于回环地址本地测试。默认关闭；多人部署必须覆盖 `math_tutor.mistakes.identity.get_student`，从已验证的登录上下文返回 `StudentContext`，不能相信客户端传来的学生 ID。本服务暂不提供账号注册和登录。

分别打开两个终端，保持相同工作目录和 `.env`：

```bash
# 终端一：HTTP 服务
python -m uvicorn math_tutor.api:app --host 127.0.0.1 --port 8000
```

```bash
# 终端二：图片分析与删除文件清理 worker
python -m math_tutor.mistakes.cli
```

也可使用安装后生成的 `math-tutor-worker` 命令。worker 未启动时，上传仍会成功，但分析状态停留在 `pending`。使用绝对数据库和图片目录路径，可以避免不同启动目录指向不同数据。

### 上传和查看

```bash
curl http://127.0.0.1:8000/v1/mistakes \
  -F 'image=@/绝对路径/题目.jpg' \
  -F 'grade=3' \
  -F 'note=这道平均分的题需要复习'
```

`grade`、`text`、`note` 都可省略。返回 `201` 和 `id`、`analysis_status=pending`。用返回的 ID 替换下方 `MISTAKE_ID`：

```bash
curl http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID
curl 'http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID?include_solution=true'
curl 'http://127.0.0.1:8000/v1/mistakes?learning_status=new&limit=20'
curl -X POST http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/analyze
```

详情默认隐藏答案和解题步骤；知识点局部编号仅在本题分析中有效，全局目录映射未经维护者确认时显示 `unmapped`。相同学生上传完全相同原图会返回 `409 duplicate_image`；明确需要另建记录时传 `allow_duplicate=true`。

状态：`pending` 待分析、`processing` 分析中、`ready` 可练习、`needs_confirmation` 题目需要澄清或暂不支持、`failed` 分析失败。失败不删除错题；网络、429、5xx 有限重试，400 不会盲目重试。

### 重做和提示

先创建一次练习，返回的 `id` 是 `PRACTICE_ID`：

```bash
curl -X POST http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/practice-sessions
```

需要启发式提示时调用：

```bash
curl -X POST http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/practice-sessions/PRACTICE_ID/hints
```

提交文本答案或作答图片，至少提供一种：

```bash
curl http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/attempts \
  -H 'Idempotency-Key: attempt-001' \
  -F 'practice_id=PRACTICE_ID' \
  -F 'text=每袋4块'

curl http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/attempts \
  -H 'Idempotency-Key: attempt-002' \
  -F 'practice_id=ANOTHER_PRACTICE_ID' \
  -F 'image=@/绝对路径/作答.png'
```

每次新的作答使用新幂等键；网络重试同一作答必须复用原键和原内容。相同键不同内容返回 409，同键仍在判题返回 202，已完成重试返回 200，首次完成返回 201。一份练习只对应一次有效提交；服务端记录提示次数。有提示或无可信练习上下文的作答，不计为独立完成。

判定为 `correct`、`incorrect` 或 `undetermined`；无法确定的不算答错。错因仅依据学生真实作答，模型推测记录为 `model_inferred`，不是老师确认的事实。正式使用前需要真实 Gemini 联调和人工样本核验。

### 复习与统计

```bash
curl http://127.0.0.1:8000/v1/reviews/today
curl http://127.0.0.1:8000/v1/mistakes/stats
```

复习列表包含已到期和逾期题目。独立正确按配置间隔 `[1,3,7]` 天安排后续复习；同日重复正确不晋级。至少两个不同学生当地日期独立答对，并通过一次已到期复习，才标记 `mastered`；随后仍安排 7 天巩固。答错或辅助完成回到练习阶段并缩短间隔，`undetermined` 不改变学习状态。默认时区 `Asia/Shanghai`。

统计中的 `independent_accuracy` 仅统计独立且判定确定的作答，分母为零返回 `null`。

### 编辑和删除

```bash
curl -X PATCH http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID \
  -H 'Content-Type: application/json' \
  -d '{"text":"修正后的题干","note":"再次检查条件"}'
curl -X DELETE http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID
```

修正题干创建新版本并自动重新分析，旧任务不能覆盖新结果。仅修改年级或备注不重新分析，需要时显式调用 `/analyze`。删除立即撤销访问、删除关联数据库记录，worker 最终清理文件。SQLite 和本地图片适用于单机首期；多实例部署应迁移共享存储和数据库。默认不运行后台任务于 HTTP 进程，避免 reload 或多 worker 重复执行。

维护者可在完成老师身份授权后，内部调用 `MistakeService.correct_attempt(..., reason=..., actor_id=...)` 修正模型判定；原判定与修正理由写入审计记录，并重算当前版本的复习日程。该操作没有开放学生 HTTP 接口，接入教师后台时必须额外实施角色权限校验。

API/worker 启动时及 worker 每小时检查异常退出遗留图片，仅删除超过 24 小时且未被数据库引用的文件。worker 收到停止信号后最多等待 30 秒；未完成任务在租约过期后恢复。交付已用真实 SDK + 模拟 HTTP 响应完成离线闭环验证，尚未调用真实 Gemini 验证判题质量。

## 解答质量检查

即时题目分析和错题后台分析共用质量检查，接口返回字段保持不变。先用本地精确数值运算核验可解析的等式，并检查部分分式定义域遗漏、数值答案不一致和计算步骤缺少公式的情况。符号公式无法解析时不直接判错；默认交给模型复核，含参数、分式、不等式等题目以及没有可核验等式的解答也会触发复核。

```dotenv
TUTOR_QUALITY_MODEL_REVIEW=on_risk
TUTOR_QUALITY_MAX_REPAIRS=1
```

`on_risk` 为默认模式；`always` 对通过本地检查的解答也进行模型复核；`off` 关闭模型复核，但保留本地检查。修复次数仅允许 `0` 或 `1`，默认最多修复一次。原解答需要复核时，修复后仍须复核，不能通过删掉公式绕过检查。

无法确认、修复后仍有问题或复核/修复请求失败时，返回 `status="needs_clarification"`、空步骤及空答案，并在 `clarifications` 中说明需要核对。即时分析仍返回 HTTP 200；错题后台标记 `needs_confirmation`。首次模型调用失败仍沿用原有错误处理。普通聊天和学生作答判定不进入这一检查流程。

最多发生四次应用层模型调用（首次分析、复核、一次修复、再次复核），SDK 内部网络重试不计入此上限，因此复杂题目会增加成本与延迟。模型复核不是数学正确性的证明；本地检查也无法覆盖全部公式或知识点。Loguru 记录检查状态、问题代码、核验数量和修复次数，不记录原始题目、完整解答或图片。

修改配置或更新代码后，需重启 API 和错题 worker。已有错题分析不会自动重新检查，可调用 `POST /v1/mistakes/{mistake_id}/analyze` 重新分析。分析快照记录提示词及质量策略版本，便于追踪。
