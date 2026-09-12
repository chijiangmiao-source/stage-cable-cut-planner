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

`verify` 会经由 web 的 nginx 代理与 api 直连分别检查：非法输入返回 422 且定位到字段、不写入记录、锯口计入卷容量、决胜规则输出唯一方案、每卷可逐段复算、方案持久化并可回查。

## 输入边界

| 字段 | 约束 |
| --- | --- |
| 卷长 `roll_length` | 1 至 100000 的整数（毫米） |
| 锯口宽度 `kerf_width` | 1 至 100000 的整数（毫米） |
| 线段条数 | 1 至 12 条 |
| 线段编号 `id` | 1–32 字符，字母数字开头，可含 `-`、`_`（`^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$`），同单内唯一 |
| 线段长度 `length` | 1 至 100000 的整数（毫米），且不得超过卷长（单卷可用长度） |

其他规则：

- 卷内相邻两段之间消耗一次锯口，卷首卷尾不消耗；`m` 段的卷消耗 `m - 1` 次锯口。
- 任何线段不得拆分；每段必须完整放进某一卷。
- 一卷可行 ⟺ 段长合计 + 锯口宽 ×（段数 − 1）≤ 卷长。

## 目标与决胜规则

求解器按严格字典序优化：

1. **最少线卷数**；
2. **总余料最小**（卷数确定后总余料 = 卷数 × 卷长 − 段长总和 − 锯口宽 ×（段数 − 卷数），随之确定）；
3. **唯一决胜**：每卷内编号升序排列，各卷按编号序列字典序排序，取整体字典序最小的方案。

实现为子集 DP（≤ 12 段 → 4096 个子集）求最少卷数，再用贪心规范化构造：含最小编号的卷必然排在最前，按字典序枚举其可行段集合并保证剩余段可装入剩余卷数。结果唯一、确定，不调用任何外部优化服务。`api/tests/test_solver.py` 用暴力枚举所有集合划分做对拍验证。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查（含数据库连通） |
| POST | `/api/plans` | 创建方案：校验 → 求解 → 持久化，返回完整方案（201） |
| GET | `/api/plans` | 方案列表（摘要，新的在前） |
| GET | `/api/plans/{id}` | 方案详情：每卷裁切顺序、锯口次数、余料 |

请求示例：

```json
{
  "roll_length": 1000,
  "kerf_width": 10,
  "segments": [
    {"id": "A", "length": 600},
    {"id": "B", "length": 590},
    {"id": "C", "length": 400}
  ]
}
```

非法长度、重复编号或某段超过单卷可用长度时返回 **422**，错误定位到具体字段或线段，且不写入任何记录：

```json
{
  "detail": [
    {"loc": ["segments", 2, "id"], "msg": "duplicate segment id 'A'", "type": "value_error"},
    {"loc": ["segments", 0, "length"], "msg": "segment length 600 exceeds usable roll length 500", "type": "value_error"}
  ]
}
```

（Pydantic 自身的字段错误 `loc` 会带 `"body"` 前缀，前端已兼容。）前端收到 422 后把错误标回对应输入框，**原输入全部保留**。

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
