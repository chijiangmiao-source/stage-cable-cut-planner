# 信号线裁切规划（Roll Cutting Planner）

舞台换景前，布线领班把若干条指定长度的信号线分配到标准线卷上。本仓库提供一个可复算、可回查的裁切方案系统：React 表单录入需求，FastAPI 精确求解并持久化到 PostgreSQL，详情页逐卷展示裁切顺序、锯口次数与余料。

## 架构

```
浏览器 ──► web (nginx, 静态资源 + /api 反向代理)
              │
              ▼
           api (FastAPI + 精确求解器)
              │
              ▼
           db (PostgreSQL)
```

- `api/` — FastAPI 应用与核心求解器（`api/app/solver.py`），pytest 测试在 `api/tests/`
- `web/` — React + Vite + TypeScript 前端，Vitest 测试在 `web/src/test/`
- `e2e/` — Playwright 端到端测试
- `verify/` — 一次性验收服务（对运行中的 Compose 栈做真实联调检查）

## 快速开始（Docker Compose）

```bash
docker compose up --build -d        # 启动 db / api / web
# 前端: http://localhost:8080   API: http://localhost:8000/api/health
```

宿主端口可用环境变量覆盖：

```bash
WEB_PORT=3000 API_PORT=9000 docker compose up --build -d
```

一次性验收（构建全部服务、跑完联调检查后以其退出码结束）：

```bash
docker compose up --build --exit-code-from verify verify
```

`verify` 会经由 web 的 nginx 代理与 api 直连分别检查：非法输入返回 422 且定位到字段、不写入记录、锯口计入卷容量、决胜规则输出唯一方案、每卷可逐段复算、方案持久化并可回查；还会验收来源调整关联、裁切进度的顺序完成与末段撤销，以及省略余量与旧行为一致、余量改变分卷、详情闭合和超限不落库；并验收省略套组与旧方案一致、可容纳套组不跨卷且容量复算闭合、不可容纳套组返回定位错误且不落库。最后验收用料复核单：从已完成裁切的多卷方案建单并刷新核对、临界偏差合格、超差整批异常、重复建单冲突且不改数据，以及各类非法录入定位到字段或卷行且不留半成品记录。

## 输入边界

| 字段 | 约束 |
| --- | --- |
| 卷长 `roll_length` | 1 至 100000 的整数（毫米） |
| 锯口宽度 `kerf_width` | 1 至 100000 的整数（毫米） |
| 线段条数 | 1 至 12 条 |
| 线段编号 `id` | 1–32 字符，字母数字开头，可含 `-`、`_`（`^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$`），同单内唯一 |
| 线段长度 `length` | 1 至 100000 的整数（毫米），且不得超过卷长（单卷可用长度） |
| 线段余量 `allowance` | 可选，0 至 10000 的整数（毫米），缺省为 0；交付长度 + 余量不得超过卷长 |
| 线段套组 `kit_id` | 可选，1–32 字符，字母数字开头，可含 `-`、`_`；留空（或 `null`）表示独立排卷 |

其他规则：

- 每条线段的实际下料长度 = 交付长度 + 端头加工余量；下料长度占用线卷。
- 卷内相邻两段之间消耗一次锯口，卷首卷尾不消耗；`m` 段的卷消耗 `m - 1` 次锯口。
- 任何线段不得拆分；每段必须完整放进某一卷。
- 一卷可行 ⟺ 段的下料长度合计 + 锯口宽 ×（段数 − 1）≤ 卷长。
- **套组（可选）**：填写相同 `kit_id` 的线段是不可跨卷的整体，必须全部落在同一卷；
  判定整组可装入单卷时计入每段余量与组内锯口（`m - 1` 次）。整组无法装入单卷时，
  创建请求返回 **422**，错误定位到该组**每条线段的 `kit_id` 输入**并标明超出毫米数，
  不产生任何方案。留空 `kit_id` 的线段仍按原方式独立排卷，旧客户端省略该字段时
  结果与历史完全一致（详情中 `kit_id` 为 `null`）。

## 目标与决胜规则

求解器按严格字典序优化：

1. **最少线卷数**；
2. **总余料最小**（卷数确定后总余料 = 卷数 × 卷长 − 下料长度总和 − 锯口宽 ×（段数 − 卷数），随之确定）；
3. **唯一决胜**：每卷内编号升序排列，各卷按编号序列字典序排序，取整体字典序最小的方案。

实现为子集 DP（≤ 12 段 → 4096 个子集）求最少卷数，再用贪心规范化构造：含最小编号的卷必然排在最前，按字典序枚举其可行段集合并保证剩余段可装入剩余卷数。套组线段只允许整组出现在同一卷（拆分集合的候选直接不可行），其余决胜规则不变。结果唯一、确定，不调用任何外部优化服务。`api/tests/test_solver.py` 用暴力枚举所有集合划分（含套组划分）做对拍验证。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查（含数据库连通） |
| POST | `/api/plans` | 创建方案：校验 → 求解 → 持久化，返回完整方案（201） |
| GET | `/api/plans` | 方案列表（摘要，新的在前，含可空 `source_plan_id`） |
| GET | `/api/plans/{id}` | 方案详情：每卷裁切顺序、锯口次数、余料、裁切进度（含可空 `source_plan_id`） |
| POST | `/api/plans/{id}/rolls/{r}/complete` | 完成该卷最前面的待切线段（体 `{"position": n}`） |
| POST | `/api/plans/{id}/rolls/{r}/undo` | 撤销该卷最后完成的一段（体 `{"position": n}`） |
| POST | `/api/review-sheets` | 建立用料复核单：校验 → 计算偏差与结论 → 持久化（201；重复建单 409） |
| GET | `/api/review-sheets/{id}` | 复核单详情：理论值、实测值、绝对偏差、逐卷结论与整批结论 |
| GET | `/api/plans/{id}/review-sheet` | 查询某方案的复核单（未建单返回 404） |

### 基于已有方案调整

方案详情页提供「基于此方案调整」入口（`/?from=<id>`），页面把原方案的卷长、锯口宽度与线段**原样带入**新建表单，领班可任意修改后按现有规则重新求解；原方案始终只读、不会被改动。

创建请求可携带可空的来源编号：

```json
{
  "roll_length": 1000,
  "kerf_width": 10,
  "source_plan_id": 7,
  "segments": [/* 修改后的线段 */]
}
```

- 服务端先确认来源方案存在，再把该编号作为**可空关联**与新方案一起保存；来源信息仅为溯源，不参与卷数、余料或决胜顺序——求解器只消费编辑后的卷长、锯口与线段。
- 未携带（或为 `null`）时按普通新建处理，既有响应字段语义不变；普通方案的 `source_plan_id` 为 `null`。
- 来源编号不存在返回 **422**，错误定位到 `source_plan_id` 字段；前端保留全部编辑内容并提示重新选择来源，不生成孤立关联或半成品记录。
- 详情页与历史列表对带溯源的方案显示「源自方案 #id」链接，可直接跳转；无来源时不显示。
- 既有数据库升级时自动补齐可空列（`ALTER TABLE ... ADD COLUMN`），既有方案来源为空，列表与详情访问方式不变。

### 裁切进度登记

换景开工后，领班在方案详情页逐卷登记实际裁切进度：

- 每卷只能按求解结果保存的规范顺序逐段完成；服务端在事务内锁定该卷记录，
  **只接受最前面的待切段**。成功后写入该段可空的完成时间 `completed_at`，
  并返回更新后的完整方案（含每卷 `completed_count` 与总计
  `completed_segment_count`）。
- 误点只能**撤销该卷最后完成的一段**。
- 过期页面、越序完成、对已完成段重复操作、非末段撤销均返回 **409 冲突**，
  数据保持不变；前端提示后重新拉取详情，按服务端真实进度展示，
  不会覆盖其他卷的记录。
- 进度只影响 `completed_at` 与完成数量；求解结果、卷序/段序、锯口与余料
  始终不变。历史方案的 `completed_at` 全为 `null`（视为未完成）。

### 用料复核单

每批裁切结束后，领班在方案详情页点「建立用料复核单」，从已保存方案建单：

- 页面按规范卷序带出每卷理论余料（来自方案求解结果），领班只为每卷录入
  一次整数毫米实测余料，并填写全批统一的允许偏差（0–10000 mm）。
- 系统以方案余料为基准计算每卷绝对偏差 `|实测 − 理论|`：偏差 ≤ 允许偏差
  该卷合格（临界值也算合格）；任何一卷超差即判定**整批用料异常**。
- 提交成功进入只读详情（`/review-sheets/{id}`），展示理论值、实测值、
  绝对偏差、逐卷结论与整批结论；复核单已持久化，刷新后仍能回查。
- 每个方案最多一张复核单：重复建单返回 **409**，原单、方案、线段与裁切
  进度都不受影响；前端提示并给出既有复核单链接，整单输入保留。
- 卷序缺失、重复或不属于所选方案时返回 **422**，错误定位到 `measurements`
  或对应卷行（`measurements.{i}.roll_position`）；实测值与允许偏差类型
  错误或越界（实测 0–100000 mm）时定位到对应字段。任何校验失败都不在
  数据库留下半成品记录。

请求示例：

```json
{
  "plan_id": 7,
  "tolerance_mm": 20,
  "measurements": [
    {"roll_position": 1, "measured_leftover": 380},
    {"roll_position": 2, "measured_leftover": 20}
  ]
}
```

响应（201）逐卷返回 `theoretical_leftover`、`measured_leftover`、`deviation`、
`ok`，以及整批复结论 `batch_ok`；复核单与卷测量记录分别存于
`review_sheets` 与 `review_measurements` 两表，输入与计算结果一起持久化。

数据库结构由 Alembic 管理（`api/migrations/`）：应用启动时自动迁移——
全新库按迁移链建表，旧库先标记到基线版本再补加可空的 `cuts.completed_at`
列（历史记录保持未完成）；启动兼容迁移同时补齐可空的 `plans.source_plan_id`
及索引（历史方案来源为空）、非空的 `cuts.allowance`（历史记录为 0），以及
可空的 `cuts.kit_id`（历史线段不属于任何套组）。`0004` 迁移新建
`review_sheets` / `review_measurements` 两表，历史方案无需任何变更即可
直接访问，只是尚未建单（按方案查复核单返回 404）。
已是最新时为空操作。也可手动执行：

```bash
alembic upgrade head     # 位于 api/ 目录，读取 DATABASE_URL
```


请求示例：

```json
{
  "roll_length": 1000,
  "kerf_width": 10,
  "segments": [
    {"id": "A", "length": 600},
    {"id": "B", "length": 590},
    {"id": "C", "length": 400, "allowance": 50},
    {"id": "D", "length": 200, "kit_id": "K1"},
    {"id": "E", "length": 300, "kit_id": "K1"}
  ]
}
```

上例中 `D`、`E` 同属套组 `K1`，求解器保证二者落在同一卷（计入两段下料长度与组内 1 次锯口）；
`A`、`B`、`C` 未填套组编号，仍独立排卷。若套组整体无法装入单卷，返回错误并定位到 `D`、`E`
的 `kit_id` 输入。

`allowance` 可省略，省略时按 0 处理，结果与旧版本完全一致。`kit_id` 同样可省略或为 `null`，
省略时该线段独立排卷；同单内若干线段填写相同 `kit_id` 即组成不可跨卷的套组。方案详情会为
每条线段返回交付长度 `length`、余量 `allowance`、套组编号 `kit_id` 与下料长度（前两者之和），
详情页在原裁切顺序旁展示套组编号，并按下料长度复算的每卷余料。

非法长度、重复编号或某段超过单卷可用长度时返回 **422**，错误定位到具体字段或线段，且不写入任何记录：

```json
{
  "detail": [
    {"loc": ["segments", 2, "id"], "msg": "duplicate segment id 'A'", "type": "value_error"},
    {"loc": ["segments", 0, "length"], "msg": "segment length 600 exceeds usable roll length 500", "type": "value_error"}
  ]
}
```

（Pydantic 自身的字段错误 `loc` 会带 `"body"` 前缀，前端已兼容。）余量越界（< 0 或 > 10000）由字段校验拒绝；交付长度 + 余量超过卷长时错误定位到对应线段的 `allowance` 输入。前端收到 422 后把错误标回对应输入框，**原输入全部保留**。

## 本地开发

### API（pytest）

```bash
cd api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

测试使用内存 SQLite；生产由 `DATABASE_URL` 指向 PostgreSQL（Compose 中已注入）。

```bash
# 本地直跑 API（可选）
DATABASE_URL=sqlite:///./plans.db uvicorn app.main:app --reload
```

### 前端（Vitest）

```bash
cd web
npm install
npm test          # Vitest
npm run dev       # 开发服务器，/api 代理到 localhost:${API_PORT:-8000}
npm run build     # tsc -b && vite build
```

### 端到端（Playwright）

先启动 Compose 栈，然后：

```bash
cd e2e
npm install
npx playwright install chromium
npm test                    # 默认打 http://localhost:8080，可用 WEB_URL 覆盖
```

## 目录结构

```
├── docker-compose.yml      # db / api / web / verify
├── api/                    # FastAPI + 求解器 + pytest
├── web/                    # React + Vite + Vitest
├── e2e/                    # Playwright
└── verify/                 # 一次性验收服务
```
