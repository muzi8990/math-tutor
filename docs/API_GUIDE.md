# 数学辅导 Agent 接口使用说明

适用版本：当前 `math-tutor-python` 实现。默认服务地址：`http://127.0.0.1:8000`。

- 在线调试：<http://127.0.0.1:8000/docs>
- OpenAPI 描述：<http://127.0.0.1:8000/openapi.json>
- 本文中的 UUID 和响应都是示例；请使用接口实际返回的 ID。

## 1. 先选择调用流程

| 你的目的 | 入口 | 是否保存到错题本 | 是否需要分析 worker |
| --- | --- | --- | --- |
| 上传图片，立即获得知识点与完整解题步骤 | `POST /v1/analyze/image` | 否 | 否 |
| 文字题或已有 base64 图片，立即分析 | `POST /v1/analyze` | 否 | 否 |
| 保存一张错题图片，后续重做和复习 | `POST /v1/mistakes` | 是 | 是 |
| 连续追问、启发式提示、检查过程 | 先 `POST /v1/sessions`，再发送消息 | 否 | 否 |
| 从错题本开始练习，记录是否独立完成 | 创建 `practice-sessions`，再提交 `attempts` | 保存作答历史 | 题目分析需要；提交判题同步执行 |

直接分析不会自动加入错题本；普通辅导会话也不会自动写入错题历史。错题练习的提示次数只通过错题练习提示接口记录，不会与普通会话自动关联。

## 2. 启动与身份

在项目目录执行安装：

```bash
python -m pip install -e .
```

配置 `.env` 中的 `GOOGLE_API_KEY` 或 `GEMINI_API_KEY`，以及账号可用的 `GEMINI_MODEL`。不要把密钥放到前端代码中。

启动 HTTP 服务：

```bash
python -m uvicorn math_tutor.api:app --host 127.0.0.1 --port 8000
```

使用错题本时，在另一个终端、相同工作目录启动分析 worker：

```bash
python -m math_tutor.mistakes.cli
```

worker 未启动时，错题仍能保存，但分析停留在 `pending`。服务与 worker 必须使用相同数据库和图片目录；路径默认相对于启动时的工作目录。

### 本地测试身份

错题管理、图片资源、复习、统计及学习接口要求学生身份。当前没有账号注册、登录或发放 Token 的接口；也没有内置 `Bearer` Token 校验。

本地调试可在 `.env` 添加：

```dotenv
TUTOR_ENABLE_LOCAL_IDENTITY=true
TUTOR_LOCAL_STUDENT_ID=11111111-1111-4111-8111-111111111111
```

这两个配置均需设置；测试身份仅接受回环地址请求。未开启时，错题相关接口返回 401。调用方不传 `student_id`；通过请求体指定学生身份无效。

多人部署时，需要覆盖 `math_tutor.mistakes.identity.get_student` 依赖，由已验证的登录上下文返回 `StudentContext(student_id, timezone)`。本文 curl 示例使用本地测试模式，不携带认证头。`/health`、独立分析和普通会话接口当前没有这一学生认证依赖，部署时需按业务要求统一保护。

## 3. 通用规则

| 项目 | 约定 |
| --- | --- |
| `grade` | 统一年级 1–12，1–6 小学、7–9 初中、10–12 高中，均可选；不要传 0 或空字符串，未知时省略 |
| 图片格式 | PNG、JPEG、WebP；建议拍清单道题及完整条件 |
| 单张图片大小 | 不超过 10 MiB；不超过 1600 万像素；不支持多帧图片 |
| 整个请求体 | 不超过 14 MiB，包含 JSON 或 multipart 开销 |
| 文字长度 | 单次 `text` 最多 20000 字符；错题备注 `note` 最多 2000 字符 |
| 上传文件 | 使用 `multipart/form-data`，字段名为 `image`；curl 的 `@` 表示读取文件 |
| JSON 图片 | `image_data_url` 必须为 `data:image/png;base64,...` 等完整 data URL，不能传文件路径或远程 URL |
| 时间 | 响应时间存 UTC，日期筛选必须包含时区；复习跨日默认按 `Asia/Shanghai` 判断 |
| 请求关联 | 响应头 `X-Request-ID` 可用于查询 Loguru 日志 |
| 返回类型 | 一般为 JSON；图片接口返回二进制；204 响应没有内容，不要调用 JSON 解析 |

curl 使用 `-F` 时，不要自行设置 `Content-Type`，curl 会生成带 boundary 的 multipart 头。浏览器使用 `FormData` 时也让浏览器设置这个头。

错题上传和作答表单拒绝未知或重复字段，JSON 请求拒绝未定义字段。JSON 可选 `grade` 接受 `null`；multipart 中未知年级应省略字段。

独立分析和普通辅导会话不传 grade 时，沿用服务端 `TUTOR_GRADE` 配置，未配置则按未知年级处理。错题收录不传 grade 时保存 null；后台分析、提示和判答优先使用题目年级，未知时使用学习偏好的当前年级，两者均未知时不推断学段。

## 4. 全部业务接口一览

| 方法 | 路径 | 作用 | 通常成功状态 |
| --- | --- | --- | --- |
| GET | `/health` | 检查 HTTP 服务存活 | 200 |
| POST | `/v1/analyze` | JSON 题目即时分析 | 200 |
| POST | `/v1/analyze/image` | 图片即时分析 | 200 |
| POST | `/v1/mistakes` | 保存图片错题并排队分析 | 201 |
| GET | `/v1/mistakes` | 分页、筛选错题 | 200 |
| GET | `/v1/mistakes/stats` | 当前学生的错题与作答统计 | 200 |
| GET | `/v1/mistakes/{mistake_id}` | 详情、分析、作答历史、复习日程 | 200 |
| GET | `/v1/mistakes/{mistake_id}/assets/{asset_id}` | 获取原题或作答图片 | 200 |
| PATCH | `/v1/mistakes/{mistake_id}` | 修正题干、年级、备注 | 200 |
| DELETE | `/v1/mistakes/{mistake_id}` | 删除错题和关联记录 | 204 |
| POST | `/v1/mistakes/{mistake_id}/analyze` | 创建或复用分析任务 | 202 |
| POST | `/v1/mistakes/{mistake_id}/practice-sessions` | 创建一次重做练习 | 201 |
| POST | `/v1/mistakes/{mistake_id}/practice-sessions/{practice_id}/hints` | 获取并记录提示 | 200 |
| POST | `/v1/mistakes/{mistake_id}/attempts` | 提交学生作答并判定 | 201 / 200 / 202 |
| GET | `/v1/reviews/today` | 获取已到期、逾期复习题 | 200 |
| GET | `/v1/learning/abilities` | 知识点表现与证据 | 200 |
| GET | `/v1/learning/preferences` | 读取学习偏好 | 200 |
| PUT | `/v1/learning/preferences` | 完整替换学习偏好 | 200 |
| POST | `/v1/learning/daily-tasks` | 幂等生成今天任务 | 201 |
| GET | `/v1/learning/daily-tasks/today` | 获取今天任务 | 200 |
| GET | `/v1/learning/daily-tasks/{task_id}` | 获取自己的历史任务 | 200 |
| POST | `/v1/sessions` | 创建普通多轮辅导会话 | 201 |
| POST | `/v1/sessions/{session_id}/messages` | JSON 发送文字或 base64 图片 | 200 |
| POST | `/v1/sessions/{session_id}/messages/image` | 上传图片并继续辅导 | 200 |
| POST | `/v1/sessions/{session_id}/reset` | 清空普通会话历史 | 200 |
| DELETE | `/v1/sessions/{session_id}` | 关闭普通会话 | 204 |

`mistake_id`、`practice_id`、`session_id` 是三种不同 ID，不要混用。

## 5. 即时题目分析

### 5.1 图片分析：POST /v1/analyze/image

请求为 multipart：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `image` | 是 | 题目图片文件 |
| `text` | 否 | 补充要求，默认空字符串 |
| `grade` | 否 | 1–12 |

```bash
curl http://127.0.0.1:8000/v1/analyze/image \
  -F 'image=@./question.jpg' \
  -F 'text=请分析题目中的知识点和解题步骤' \
  -F 'grade=3'
```

只上传图片也可以：

```bash
curl http://127.0.0.1:8000/v1/analyze/image \
  -F 'image=@./question.jpg'
```

### 5.2 JSON 分析：POST /v1/analyze

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `text` | 与图片至少提供一个 | 题干或补充要求，默认空字符串 |
| `image_data_url` | 与文字至少提供一个 | 完整 base64 图片 data URL，默认 null |
| `grade` | 否 | 1–12 或 null |

```bash
curl http://127.0.0.1:8000/v1/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text":"24块饼干平均放入6个袋子，每袋几块？","grade":3}'
```

这两个接口返回相同的 `ProblemAnalysis`。示例：

```json
{
  "status": "solved",
  "problem_text": "24块饼干平均放入6个袋子，每袋几块？",
  "core_knowledge_points": [
    {"id": "K1", "name": "除法的意义", "description": "把总量平均分成若干份。"}
  ],
  "detailed_knowledge_points": [
    {"id": "K1.1", "parent_id": "K1", "name": "平均分求每份数量", "description": "每份数量等于总数量除以份数。"}
  ],
  "steps": [
    {"index": 1, "description": "把24块平均分成6份，求每份数量。", "formula": "24÷6=4", "knowledge_point_ids": ["K1", "K1.1"], "knowledge_application": "用除法计算平均分后的每份数量。"}
  ],
  "answer": "每袋4块。",
  "clarifications": []
}
```

- `solved`：有答案和解题步骤。
- `needs_clarification`：需要补充或确认条件；`answer=null`、`steps=[]`，查看 `clarifications`。
- `unsupported`：暂不支持；同样不返回解答，查看原因。
- `K1`、`K1.1` 是本次分析的局部编号，不是全局知识点或教材编码。

即时分析同步等待 Gemini 返回，不需要轮询，也不会写入错题本。

## 6. 错题收录、查询和维护

### 6.1 收录：POST /v1/mistakes

请求为 multipart：

| 字段 | 必填 | 默认 / 说明 |
| --- | --- | --- |
| `image` | 是 | 原题图片 |
| `text` | 否 | 空字符串；题干补充或已有题干 |
| `grade` | 否 | 未指定 |
| `note` | 否 | 空字符串，最多 2000 字符 |
| `allow_duplicate` | 否 | false；明确允许重复收录时传 true |

```bash
curl http://127.0.0.1:8000/v1/mistakes \
  -F 'image=@./question.jpg' \
  -F 'note=这道平均分的题需要复习'
```

返回 201。以下为响应关键字段节选：

```json
{
  "id": "22222222-2222-4222-8222-222222222222",
  "problem_text": "",
  "grade": null,
  "analysis_status": "pending",
  "learning_status": "new",
  "content_version": 1,
  "analysis": null,
  "assets": [
    {"id": "33333333-3333-4333-8333-333333333333", "purpose": "question", "mime": "image/jpeg", "size": 12345, "url": "/v1/mistakes/22222222-2222-4222-8222-222222222222/assets/33333333-3333-4333-8333-333333333333"}
  ],
  "attempts": [],
  "review": null
}
```

保留返回的 `id`。图片识别完成后，空的 `problem_text` 会填入识别题干。响应可能在创建后立即被 worker 更新，后续以详情查询为准。

相同学生上传完全相同原图，返回：

```json
{
  "detail": {
    "code": "duplicate_image",
    "mistake_id": "已有错题ID",
    "message": "已收录相同图片，可明确选择继续收录。"
  }
}
```

若确实要另建一条，重新上传时加 `-F 'allow_duplicate=true'`。这只检测原图字节完全相同，裁剪或重新拍摄后的同一道题不保证识别为重复。

### 6.2 查详情与等待分析：GET /v1/mistakes/{mistake_id}

```bash
curl http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID
```

前端建议间隔 2–3 秒查一次，离开页面或到达明确终态时停止轮询；达到等待上限时提示稍后查看，不自动删除记录。

| `analysis_status` | 含义 | 后续操作 |
| --- | --- | --- |
| pending | 等待 worker | 确认 worker 正在运行，继续查询 |
| processing | 分析中 | 继续查询 |
| ready | 已完成可用分析 | 可以创建练习 |
| needs_confirmation | 图片或条件需要确认，或题型暂不支持 | 查看 `analysis.clarifications`，修正题干 |
| failed | 本次分析失败 | 查看服务/worker 日志，再决定重试 |

默认 `include_solution=false`，`analysis` 中不含 `answer`、`steps`。需要显示解析时：

```bash
curl 'http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID?include_solution=true'
```

详情还包含原题和作答 `assets`、`attempts` 历史、`review` 日程，以及已有分析的 `analysis_id`、`knowledge_mappings`。`mapping_status=unmapped` 表示尚未映射到内部知识点目录。

### 6.3 列表：GET /v1/mistakes

| 查询参数 | 说明 |
| --- | --- |
| `learning_status` | new / practicing / reviewing / mastered |
| `analysis_status` | 上述五种分析状态 |
| `knowledge_point_id` | 内部知识点 UUID；不能用 K1 |
| `created_from`、`created_to` | 含时区的 ISO 8601 时间，筛选收录时间，包含边界 |
| `limit` | 默认 20，1–100 |
| `cursor` | 上一页返回的 next_cursor，最长 1000 字符 |

```bash
curl -G http://127.0.0.1:8000/v1/mistakes \
  --data-urlencode 'learning_status=new' \
  --data-urlencode 'limit=20' \
  --data-urlencode 'created_from=2026-10-01T00:00:00+08:00'
```

返回 `{"items": [...], "next_cursor": "..."}`，按创建时间倒序排列。`next_cursor=null` 表示没有下一页。查询下一页时保留原筛选条件，使用 `--data-urlencode` 传 cursor，不自行解析或拼接。列表是摘要，解析和图片 URL 从详情获取。

### 6.4 图片：GET /v1/mistakes/{mistake_id}/assets/{asset_id}

使用详情中返回的 `assets[].url`，拼到服务地址后请求，返回图片二进制。

```bash
curl http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/assets/ASSET_ID -o question.jpg
```

接口校验学生归属，不提供服务器磁盘路径；响应带 `Cache-Control: no-store`。

### 6.5 编辑：PATCH /v1/mistakes/{mistake_id}

JSON 字段：`text`、`grade`、`note`，全部可选。只传要修改的字段。

```bash
curl -X PATCH http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID \
  -H 'Content-Type: application/json' \
  -d '{"text":"24块饼干平均放入6个袋子，每袋几块？","grade":3,"note":"已确认题干"}'
```

- `text` 真正变化时增加 `content_version`，取消旧活动任务，重新分析，学习状态重置为 new、当前日程清除；历史作答保留。
- 只改 `grade` 或 `note` 不自动重新分析。需要适配新年级时再调用 `/analyze`。
- `grade=null` 清空年级；`text` 和 `note` 不能传 null，可传空字符串。
- 当前没有替换原题图片的编辑接口；需要另一张原图时重新收录。

### 6.6 重试 / 重新分析：POST /v1/mistakes/{mistake_id}/analyze

不需要请求体：

```bash
curl -X POST http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/analyze
```

返回 202 和任务记录，其中 `id` 是分析任务 ID，不是错题 ID。已有同版本活动任务时复用，不重复入队；完成状态仍通过错题详情查询，当前没有单独的任务查询接口。

网络错误、429、5xx 最多自动重试 3 次，等待间隔 2、10、30 秒。400、权限错误和结构校验失败不会自动重试。分析失败不会丢失错题。

### 6.7 删除：DELETE /v1/mistakes/{mistake_id}

```bash
curl -X DELETE http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID
```

返回 204、无响应体。关联作答和日程被删除，图片立即不能再通过 API 访问；实际文件由 worker 清理。

## 7. 重做、提示与错因诊断

推荐调用顺序：详情确认 ready → 创建一次练习 → 可选获取提示 → 提交作答 → 查看反馈与复习日程。

### 7.1 创建练习：POST /v1/mistakes/{mistake_id}/practice-sessions

不需要请求体，题目必须为 ready：

```bash
curl -X POST http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/practice-sessions
```

返回 201：

```json
{
  "id": "44444444-4444-4444-8444-444444444444",
  "mistake_id": "22222222-2222-4222-8222-222222222222",
  "content_version": 1,
  "hint_count": 0
}
```

保存这里的 `id` 为 `practice_id`。一次练习只对应一次有效作答；下次重做创建新的练习。

### 7.2 获取提示：POST /v1/mistakes/{mistake_id}/practice-sessions/{practice_id}/hints

```bash
curl -X POST http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/practice-sessions/PRACTICE_ID/hints
```

返回 `{"hint":"先找总数量和份数。","hint_count":1,"practice_id":"..."}`。

提示次数由服务端记录，单次练习最多 10 次。已提交的练习不能再取提示。提示调用一开始就记一次使用，模型调用失败后也不会恢复为“未使用提示”。

### 7.3 提交作答：POST /v1/mistakes/{mistake_id}/attempts

请求头：`Idempotency-Key` 必填，长度 1–128；用于防止网络重试产生重复判题和重复记录。

请求为 multipart：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `text` | 与 image 至少一个 | 学生答案或步骤，最多 20000 字符 |
| `image` | 与 text 至少一个 | 学生作答图片，不是重新上传原题 |
| `practice_id` | 否，推荐传 | 当前练习的 UUID |

文字作答：

```bash
curl http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/attempts \
  -H 'Idempotency-Key: attempt-001' \
  -F 'practice_id=PRACTICE_ID' \
  -F 'text=24÷6=4，每袋4块'
```

图片作答：

```bash
curl http://127.0.0.1:8000/v1/mistakes/MISTAKE_ID/attempts \
  -H 'Idempotency-Key: attempt-002' \
  -F 'practice_id=NEW_PRACTICE_ID' \
  -F 'image=@./answer.png'
```

上面是两种独立示例：如果已经用某次练习提交了文字答案，上传另一份作答时需要新的练习和新的键。一次请求也可同时传文字和作答图片。

成功响应关键字段节选：

```json
{
  "id": "55555555-5555-4555-8555-555555555555",
  "status": "incorrect",
  "hint_count": 0,
  "independent": true,
  "evidence": "学生写了24÷6=5，计算结果不匹配。",
  "diagnoses": [
    {"category":"calculation","evidence":"24÷6=5","explanation":"这一步计算结果错误。","step_index":1,"knowledge_point_ids":["K1.1"]}
  ],
  "provenance": "model_inferred"
}
```

判定状态：

| 状态 | 含义 |
| --- | --- |
| correct | 可以确定答案正确 |
| incorrect | 可以确定答案错误，并提供证据诊断 |
| undetermined | 条件、参考分析或学生作答不够明确，不算答错，不推进复习状态 |

错因类别：concept 概念、reading 审题、method 方法、calculation 计算、unit 单位、missing_step 步骤遗漏、unknown 证据不足以定位具体原因。没有学生过程时不能臆造错误步骤。

`provenance=model_inferred` 是模型推测；老师授权内部修正后可为 `human_confirmed`。目前没有面向学生的人工修正 HTTP 接口。

独立完成必须使用可信的 practice_id 且本次提示次数为 0。不传 practice_id 仍可判题，但 `independent=false`；客户端不能自报独立完成或提示次数。这仅表示系统内未使用提示，不能证明学生没有获得系统外帮助。

#### 幂等和重试

| 返回状态 | 说明 | 客户端行为 |
| --- | --- | --- |
| 201 | 首次判题成功并保存 | 展示反馈，查详情获取新日程 |
| 200 | 相同键、相同内容已经完成 | 使用原作答结果 |
| 202 | 相同提交仍在处理 | 稍后用相同键、相同内容重试 |
| 409 | 同键不同内容，练习已被其他提交使用，或题目状态/版本变化 | 核对题目、练习与键，必要时重新练习 |
| 502 | 模型判题失败，没有有效作答记录 | 可用原键、原内容重试 |

每次新的作答用新键；网络失败后的同一作答保持文字、图片、practice_id 和键不变。当前没有独立 submission 查询接口，通过重复同一请求获取结果。作答响应本身不包含复习日程，需要再查错题详情的 `review`。

## 8. 今日复习与统计

### 8.1 GET /v1/reviews/today

```bash
curl 'http://127.0.0.1:8000/v1/reviews/today?limit=20'
```

返回 `{"items":[...],"next_cursor":null,"timezone":"Asia/Shanghai"}`。包含现在已到期及逾期的题目，不包含今天晚些时候尚未到期的题目；按到期时间升序排列，不返回解析。

支持 `limit` 默认 20、最大 100，及 `cursor` 分页。选中题目后，沿用第 7 节练习与作答接口；没有另一个“提交复习答案”接口。

学习状态：new 新收录、practicing 练习中、reviewing 复习中、mastered 按当前规则已掌握。

规则：默认间隔 `[1,3,7]` 天，同日重复独立正确不晋级；至少两个不同学生当地日期独立答对，且通过一次已到期复习，才掌握。掌握后安排 7 天巩固。答错或辅助完成回到 practicing、安排 1 天后重试；无法确定的作答不改变状态。间隔由 `TUTOR_REVIEW_INTERVALS` 配置。

### 8.2 GET /v1/mistakes/stats

```bash
curl http://127.0.0.1:8000/v1/mistakes/stats
```

示例：

```json
{
  "learning_counts": {"new":2,"practicing":1,"reviewing":3,"mastered":1},
  "mistake_count": 7,
  "due_review_count": 2,
  "determined_independent_attempts": 10,
  "independent_accuracy": 0.8
}
```

`independent_accuracy` 为 0–1，表示独立且能确定判定的历史作答中答对的比例；辅助完成和 undetermined 不计入分母，无有效分母时为 null。它是作答正确率，不是掌握题目比例。

## 9. 普通多轮辅导会话

普通会话用于连续追问，保存在 HTTP 进程内存。服务重启、reload 或请求落到另一进程后，原会话可能找不到；首期应单进程运行。会话不属于错题练习记录，不自动更新掌握状态。

### 9.1 创建：POST /v1/sessions

JSON 请求体必需；未知年级可传 `{}`：

```bash
curl http://127.0.0.1:8000/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"grade":3}'
```

返回 201，`{"session_id":"...","turn_count":0}`。保留 session_id。

### 9.2 图片消息：POST /v1/sessions/{session_id}/messages/image

```bash
curl http://127.0.0.1:8000/v1/sessions/SESSION_ID/messages/image \
  -F 'image=@./question.jpg' \
  -F 'text=先给我一个提示' \
  -F 'mode=hint'
```

image 必填，text 默认空字符串，mode 默认 hint。返回文字 `answer`、`session_id`、`turn_count`。

### 9.3 JSON 消息：POST /v1/sessions/{session_id}/messages

```bash
curl http://127.0.0.1:8000/v1/sessions/SESSION_ID/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"为什么要用除法？","mode":"hint"}'
```

支持 `text`、`image_data_url`，至少一个；mode 可逐轮切换：

| mode | 用途 |
| --- | --- |
| hint | 启发式提示，默认 |
| solve | 完整解答 |
| check | 检查学生答案或步骤 |
| read | 识别题干与笔迹 |

年级只能在创建时指定，消息中不要再传 grade。响应示例：

```json
{"session_id":"66666666-6666-4666-8666-666666666666","answer":"你可以先想：总共有多少块，需要分成几份？","turn_count":2}
```

这里的 answer 是辅导文字，不是结构化 `ProblemAnalysis`。需要知识点和步骤 JSON 时调用第 5 节接口。

### 9.4 重置和关闭

```bash
curl -X POST http://127.0.0.1:8000/v1/sessions/SESSION_ID/reset
curl -X DELETE http://127.0.0.1:8000/v1/sessions/SESSION_ID
```

reset 保留 ID、清空历史，返回 turn_count=0。DELETE 返回 204 并释放资源。默认最多 30 轮、100 个同时保存的会话，分别由 `TUTOR_MAX_TURNS`、`TUTOR_SERVICE_MAX_SESSIONS` 配置。

## 10. 健康检查、错误与排查

```bash
curl http://127.0.0.1:8000/health
```

返回 `{"status":"ok"}` 只表示 HTTP 进程存活，不证明 Gemini、worker 或分析任务可用。

| HTTP 状态 | 常见原因 | 如何处理 |
| --- | --- | --- |
| 401 | 错题接口缺少已验证身份 | 本地配置测试身份并重启；多人环境接入认证 |
| 404 | ID 不存在、已删除、会话已关闭，或资源不属于当前学生 | 使用真实响应 ID；检查是否重启丢失会话 |
| 409 | 图片重复、题目未 ready、版本变化、重复使用练习、幂等冲突、提示/会话达到上限 | 读取 detail，根据具体原因处理 |
| 413 | 图片超过 10 MiB，或请求体超过 14 MiB | 缩小/裁剪图片 |
| 415 | 上传 MIME 类型不是支持的图片格式 | 使用实际有效 PNG/JPEG/WebP |
| 422 | 必填参数缺失、无效 UUID/年级/data URL/日期、未知字段、损坏图片 | 对照请求格式；表单与 JSON 不要混用 |
| 502 | 同步分析、提示或判题的模型请求/输出失败 | 用 X-Request-ID 查日志，核对模型配置与实际错误 |
| 503 | 模型配置缺失，或普通会话容量已满 | 补充配置，或关闭不再使用的会话 |

错误体一般为 `{"detail":"说明"}`；FastAPI 参数错误的 detail 为数组，重复图片的 detail 为对象，客户端不要假设 detail 永远是字符串。

错题异步分析失败不会把已成功的上传改成 HTTP 502；应通过分析状态 failed 和 worker 日志排查。一直 pending 首先检查 worker 和数据库路径。当前业务 API 没有直接返回供应商原始错误信息的接口。

日志默认 `logs/math-tutor.log`，由 Loguru 记录。HTTP 请求与模型调用可按 X-Request-ID 关联；后台任务按 mistake_id/job_id 关联。不要在前端展示完整服务器日志。

## 11. Swagger 和前端调用

Swagger 操作：打开 `/docs` → 展开接口 → Try it out → 填参数/选图片 → Execute。路径参数替换为真实 UUID。作答接口需要填 `idempotency-key` 请求头字段；不确定年级时不填写可选 grade。

浏览器上传图片示例：

```javascript
const form = new FormData();
form.append('image', fileInput.files[0]);
// 可选：form.append('grade', '3');

const response = await fetch('/v1/mistakes', {
  method: 'POST',
  body: form
});
const result = await response.json();
if (!response.ok) throw new Error(JSON.stringify(result.detail));
console.log('错题ID', result.id);
```

该示例要求前端和 API 同源或通过同源代理访问。当前服务未配置 CORS，中小程序/网页跨域接入需要另行配置；实际认证头或 Cookie 由部署时采用的认证方式决定。

建议前端完整流程：

1. 上传 `/v1/mistakes`，保存 mistake_id。
2. 查详情，等到 ready；需要确认时引导修正题干，失败时显示重试操作。
3. 创建 practice-sessions，保存 practice_id，先隐藏解析。
4. 学生需要帮助时调用 hints；服务端记录提示次数。
5. 生成并保存本次 Idempotency-Key，提交 attempts，按 201/200/202/错误分支处理。
6. 展示证据和错因，需要时查 include_solution=true；重新查询详情获取复习日程。
7. 下一次进入“今日复习”时获取 daily-tasks/today；未生成时 POST daily-tasks，练习时关联 daily_task_item_id。需要完整实时到期列表时仍可调用 reviews/today。

## 12. 当前实现边界

- 全局知识点目录的维护、映射和老师人工纠错目前是内部调用，没有对外 HTTP 管理接口。
- 无自动保存普通聊天为错题、无替换原题图片、无题目语义合并、无变式生成接口。
- 模型判定经过结构校验与有限确定性检查，真实教学准确性仍需真实 Gemini 联调和人工样本验证。
- 当前文档依据代码与 OpenAPI 核对；示例响应不代表已向真实 Gemini 请求这些题目。

## 分析结果的质量检查

即时题目分析和错题后台分析共用质量检查，接口返回字段保持不变。先用本地精确数值运算核验可解析的等式，并检查部分分式定义域遗漏、数值答案不一致和计算步骤缺少公式的情况。符号公式无法解析时不直接判错；默认交给模型复核，含参数、分式、不等式等题目以及没有可核验等式的解答也会触发复核。

```dotenv
TUTOR_QUALITY_MODEL_REVIEW=on_risk
TUTOR_QUALITY_MAX_REPAIRS=1
```

`on_risk` 为默认模式；`always` 对通过本地检查的解答也进行模型复核；`off` 关闭模型复核，但保留本地检查。修复次数仅允许 `0` 或 `1`，默认最多修复一次。原解答需要复核时，修复后仍须复核，不能通过删掉公式绕过检查。

无法确认、修复后仍有问题或复核/修复请求失败时，返回 `status="needs_clarification"`、空步骤及空答案，并在 `clarifications` 中说明需要核对。即时分析仍返回 HTTP 200；错题后台标记 `needs_confirmation`。首次模型调用失败仍沿用原有错误处理。普通聊天和学生作答判定不进入这一检查流程。

最多发生四次应用层模型调用（首次分析、复核、一次修复、再次复核），SDK 内部网络重试不计入此上限，因此复杂题目会增加成本与延迟。模型复核不是数学正确性的证明；本地检查也无法覆盖全部公式或知识点。Loguru 记录检查状态、问题代码、核验数量和修复次数，不记录原始题目、完整解答或图片。

修改配置或更新代码后，需重启 API 和错题 worker。已有错题分析不会自动重新检查，可调用 `POST /v1/mistakes/{mistake_id}/analyze` 重新分析。分析快照记录提示词及质量策略版本，便于追踪。

## 每日学习与能力评估

以下六个接口均要求已认证的学生身份，客户端不传 student_id。生成与查询不调用模型；只有练习提示、需要模型的作答判定及题目分析产生模型请求。原 `/v1/reviews/today` 继续返回实时到期列表，每日任务则保存当天选题及完成情况。

| 方法 | 路径 | 成功状态 | 用途 |
| --- | --- | --- | --- |
| GET | `/v1/learning/preferences` | 200 | 读取偏好，未设置返回默认值 |
| PUT | `/v1/learning/preferences` | 200 | 完整替换偏好；省略字段恢复默认值 |
| POST | `/v1/learning/daily-tasks` | 201 | 生成今天任务，已有任务返回原任务 |
| GET | `/v1/learning/daily-tasks/today` | 200 | 读取今天任务，未生成返回 404 |
| GET | `/v1/learning/daily-tasks/{task_id}` | 200 | 按 ID 读取自己的历史任务 |
| GET | `/v1/learning/abilities` | 200 | 知识点表现与证据摘要 |

### 设置偏好并开启定时生成

```bash
curl -X PUT http://127.0.0.1:8000/v1/learning/preferences \
  -H 'Content-Type: application/json' \
  -d '{"grade":8,"timezone":"Asia/Shanghai","daily_enabled":true,"generation_time":"19:00","daily_limit":5}'
```

| 字段 | 默认值 | 约束 |
| --- | --- | --- |
| grade | null | 当前学生年级，可选 1–12，与题目年级可以不同 |
| timezone | 首次读取采用认证上下文时区 | IANA 时区；PUT 省略则采用认证上下文时区 |
| daily_enabled | false | 是否开启定时生成，关闭不删除历史任务 |
| generation_time | 19:00 | 严格 HH:mm，当地时间 |
| daily_limit | 5 | 整数 1–10；修改不重抽已生成任务 |

响应返回保存后的五个字段。服务端时钟决定任务日期，不接受客户端指定日期。定时生成还需单独运行 `python -m math_tutor.learning.cli scheduler`，每 60 秒扫描一次。开启后当天已过生成时间时，下次扫描生成今天任务；重启只补当前日期，不补建过去的每日任务。重复夏令时取第一次有效时刻，缺失时刻顺延至首个有效时刻。此功能只生成任务，不发送短信或推送。

### 生成与查看任务

```bash
curl -X POST http://127.0.0.1:8000/v1/learning/daily-tasks
curl http://127.0.0.1:8000/v1/learning/daily-tasks/today
```

响应关键字段示例，UUID 需使用实际返回值：

```json
{
  "id": "TASK_UUID",
  "local_date": "2026-10-10",
  "timezone": "Asia/Shanghai",
  "source": "manual",
  "policy_version": "daily-v1",
  "created_at": "2026-10-10T11:00:00Z",
  "completed_count": 0,
  "available_count": 1,
  "message": null,
  "items": [{
    "id": "ITEM_UUID",
    "mistake_id": "MISTAKE_UUID",
    "mistake_id_snapshot": "MISTAKE_UUID",
    "content_version": 1,
    "reason": "due_review",
    "due_at": "2026-10-10T10:00:00Z",
    "status": "pending",
    "attempt_id": null,
    "outcome": null,
    "independent": null
  }]
}
```

`source` 为 manual 或 scheduled；`reason` 为 due_review（已到期）或 new_mistake（尚无复习计划的错题）。只选取当前版本 ready 且分析 solved 的题目，先到期复习，再补无计划错题，未来到期题不提前插入；在相同优先级内优先覆盖不同已映射细分知识点。无候选时仍创建空任务，items=[]，并返回“今日暂无待复习错题”。

同一天新增错题不会重新填充任务，可沿用普通错题练习流程。时区修改不改变已生成任务的快照；GET today 使用当前偏好时区计算日期，历史任务通过 ID 查询。任务不包含答案或步骤，题目内容通过原错题详情及图片接口获取。

### 关联任务项并提交真实作答

创建练习时增加可选 JSON 请求体；原来不传请求体的调用继续有效：

```bash
curl -X POST http://127.0.0.1:8000/v1/mistakes/MISTAKE_UUID/practice-sessions \
  -H 'Content-Type: application/json' \
  -d '{"daily_task_item_id":"ITEM_UUID"}'

curl http://127.0.0.1:8000/v1/mistakes/MISTAKE_UUID/attempts \
  -H 'Idempotency-Key: daily-practice-001' \
  -F 'text=学生实际答案或步骤' -F 'practice_id=PRACTICE_UUID'
```

practice_id 使用创建练习响应的 id。明确判答后，同一事务更新作答、复习日程和任务项；重复幂等提交不重复完成。未关联的自由练习仍更新复习日程，但不完成每日任务。

| 状态 | 含义 |
| --- | --- |
| pending | 尚未提交有效关联作答 |
| completed | 已完成一次明确判答的复习，可能答对或答错 |
| needs_confirmation | 已提交但无法明确判定，后续新关联练习可以再次作答 |
| invalidated | 题目删除、内容版本变化或重新分析等使原任务项失效 |

outcome 为 correct、incorrect 或 undetermined；independent 表示该次练习是否未使用提示。完成一次复习不代表掌握。客户端没有修改完成状态的接口；错误/其他学生的任务项不能关联。已完成、已失效或题目版本不符时创建关联练习返回 409，其他学生的任务项返回 404。人工更正会更新关联任务的判定。

失效项不补题，排除 completed_count 和 available_count。删题后 mistake_id 为 null，保留 ID/版本快照供历史任务解释，不保留已删除正文和图片；界面应提示“题目已删除”，不再请求原题。

### 查看知识点表现

```bash
curl http://127.0.0.1:8000/v1/learning/abilities
```

返回 `policy_version=ability-v1`、`window_days=30`、`as_of`、`items` 和 `core_summary`。细分节点包含 point_id、name、parent_id、适用年级范围、evidence_count、question_count、date_count、accuracy、state、recent_errors 及 evidence 引用。evidence 关联原 attempt_id、analysis_id、mistake_id、日期、正确性及来源；核心节点只汇总子节点 state_counts。

| state | 中文表现 | 首期规则 |
| --- | --- | --- |
| insufficient_evidence | 证据不足 | 少于 3 条证据或 2 道不同题目 |
| needs_practice | 需加强 | 证据充分后，正确率低于 60% 或最近两条均错误 |
| stable | 较稳定 | 至少 5 条、3 道题、2 个日期，正确率至少 80%，最近两条均正确 |
| basic | 初步掌握 | 其余证据充分的情况 |

只用最近 30 个当地自然日内当前版本、明确判定且未使用提示的独立作答，同题同日取最后一条有效记录。正确为已映射细分节点提供正向证据；错误只有实际错因明确指向该细分节点时才提供负向证据。unknown 或仅引用核心知识点的错误不扩大到所有细分节点。

只有经过目录维护确认映射的节点参与跨题统计；未映射时 items 可以为空，已映射但暂无证据的节点显示证据不足、accuracy=null。维护方式见 [使用说明](USAGE.md#每日学习服务)。这些状态是近期学习表现，不是标准化测评成绩；各学段规则与教学效果仍需真实数据验证。

新接口复用 401/404/409/422 约定；SQLite 暂时不可用返回 503 和 Retry-After=60，可稍后重试。
