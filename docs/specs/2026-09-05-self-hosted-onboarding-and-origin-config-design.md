# EverLink 自托管上手清晰化 + origin 配置化 — 设计规格

- **状态**：设计已批准（第一性原理 + 对抗式审核自主通过），待实现
- **负责人**：yuya（owner）；执行：Qoder（boss/PM/视觉/UI/UX/架构/数据/开源管理 多角色自主推进）
- **日期**：2026-09-05
- **范围**：文档清晰化 + origin 配置化（env-only）+ board 原理页；不含可写配置管理与生产 DB 物理重命名（入 Backlog）

---

## 1. 背景与问题

EverLink 是一个**开源（MIT）、自托管、非 SaaS** 的链接腐烂巡检 agent。当前存在两类根本问题：

**(a) 上帝视角失真**——[`adapters.py`](../../../everlink/adapters.py) 用 `SITE_BASE_URL = {"sandcart": "https://flashdeals.today"}` 把"内部站点代号 ↔ 真实域名"的映射**硬编码进开源代码**。这只对 maintainer 自己的站点成立；任何人 clone 代码后，这段硬编码对他的站点毫无意义甚至会误拼 URL。诊断/修复依赖了"外界看不到的内部信息"，产品因此失真。

**(b) 清晰性缺失**——README 与 board 都没有把"这是什么、要不要托管、部署要准备什么、怎么跑"讲清楚，连 owner 本人有时都看不明白。对一个指望陌生人 clone 部署的开源项目，这是致命的。

派生问题：`data/slots_sandcart.csv` 里站内链接是裸相对路径 `/products/...`，未绝对化时被 SSRF 守卫拒绝（`scheme '' not allowed`），整站浮出为假的 `needs_human_recheck` 卡；`seed.py` 曾编造假 Amazon 联盟链接（已在 t2 修正工作区，生产库残留 1 槽）。

---

## 2. 第一性原理

剥掉惯例与"顺口建议"，本项目只需成立两件事：

1. **一个 clone 代码的陌生人能看懂并部署它**（清晰性）；
2. **它对任何人的站点都成立，而不只对 maintainer 的站成立**（消除上帝视角）。

凡不同时服务这两条的复杂度，都是候选删除项。

---

## 3. 目标 / 非目标

**目标**
- G1：README 顶部与 board 新页，让陌生开发者 30 秒内答出"是什么 / 非 SaaS / 要准备什么 / 怎么跑"。
- G2：origin 从硬编码改为**部署者填写的 env 配置**，代码不预设任何域名；文档与实现完全一致。
- G3：把三个站点（aethelgem/hotdeals/sandcart）明确定位为 **maintainer 的 dogfooding 示例键**，对外展示统一 FlashDeals。
- G4：诚实修复历史数据（正当重摄取让 URL 绝对化 + 退役误报卡），不手工篡改生产库。

**非目标（本 spec 明确不做，入 Backlog）**
- N1：可写的 web UI 配置管理（`site_configs` 表 + board 写配置）。
- N2：`sandcart` → `flashdeals` 的生产 DB 物理重命名 / env 变量改名 / CSV 改名。
- N3：任何新的对外 SaaS 化、多租户、计费能力。

---

## 4. 对抗式审核：记录关键决策

以 8 角色对初版 design 做对抗式攻击，收敛出 4 处修正（保留决策依据以备复核）：

| # | 初版设想 | 对抗结论 | 最终决策 |
|---|---|---|---|
| 1 | origin 存 DB `site_configs` 表，web UI 可写 | 架构师：违反 board "唯一写=决策 transition、从不 DDL" 铁律；origin 是部署配置，12-factor 天然载体是 env | **origin 走 env-only**，无 DB 配置表 |
| 2 | board `/setup` 可写配置表单 | 开源安全：扩大攻击面；PM：非 MVP | **降级为只读展示**，secret 绝不接收/存储/回显 |
| 3 | `sandcart`→`flashdeals` 物理重命名 | Boss/数据：10 天冲刺内动生产 DB + 改 env 变量名 + 同步 Railway，风险 > 收益 | **不做物理重命名**；改文档定位为"示例键"+ 对外统一 FlashDeals |
| 4 | board `/setup` 独立页显示实时接入状态 | 架构：board(Vercel) 与 agent(Railway) **env 不共享**，board 看不到 agent 的 origin/DSN，实时状态无源 | **`/setup` 并入 `/how-it-works`**，只做一个静态"原理 + 部署者契约"只读页 |

净效果：范围从"文档 + origin 配置化 + 可写 web UI + 物理重命名"收敛为"**文档清晰化 + origin env 配置化 + 一个只读原理页**"，聚焦、低风险、契合第一性。

---

## 5. 设计

### 5.1 【P0·C】origin 配置化（env-only，最小侵入）

**核心事实**：`cmd_scan` → `agents.run_scan(site)` → `extract_slots` → `load_slots` → `_row_to_slot` → `absolutize_slot_url`。origin 解析封装在 `adapters` 内部读 env，**`cli.py` / `agents.py` / `db.py` 不改**。

**`everlink/adapters.py` 改造**
- 删除 `SITE_BASE_URL` 常量（line 29-31）及其注释里对硬编码域名的描述。
- 新增 env resolver（对称于 `db.SOURCE_DSN_VARS` 的 `<SITE>_DATABASE_URL` 命名）：
  ```python
  import os
  def resolve_origin(site: str) -> str | None:
      """The site's public origin, as configured by whoever deploys EverLink.
      Symmetric with <SITE>_DATABASE_URL. Unset => the site's links are assumed
      already-absolute (no origin is ever hardcoded in this repo)."""
      return os.environ.get(f"{site.upper()}_PUBLIC_ORIGIN") or None
  ```
- `absolutize_slot_url` 改为接受**注入的 origin**（纯函数，便于测试），不再读硬编码表：
  ```python
  def absolutize_slot_url(url: str, origin: str | None) -> str:
      if not origin or not url:
          return url
      if url.startswith(("http://", "https://")):
          return url          # already absolute — no double-prefix
      return urljoin(origin, url)
  ```
- `_row_to_slot`（line 61）改为：`url=absolutize_slot_url(row["url"], resolve_origin(site))`。

**env 契约**：每站一个 `<SITE>_PUBLIC_ORIGIN`（如 `SANDCART_PUBLIC_ORIGIN=https://flashdeals.today`）。未设置时相对 URL 原样返回——诚实暴露"未配置"，绝不猜域名。

**`.env.example`**：新增 per-site origin 段，注释说明"填你自己的域名；与 `<SITE>_DATABASE_URL` 对称；链接本就绝对的站点可不设"。

### 5.2 【P0·B】清晰性：README 重写 + board `/how-it-works`

**README.md 顶部重构**（倒金字塔：先定位，再契约，最后深水区）
- 开篇 3 行讲清：**开源 · 自托管 · 非 SaaS**（MIT）；你 clone → 部署到自己的基础设施 → 填自己的配置 → 它巡检**你自己的站点**。
- 新增 **"What this is / What this is NOT"** 小节：明确没有注册/托管/月费/多租户；仓库里的 AethelGem/HotDeals/FlashDeals 是 **maintainer 的 dogfooding 示例**，部署时换成你自己的站。
- 新增 **"Deploy it — what you need"（部署者契约表）**：① 你站点的只读库 `<SITE>_DATABASE_URL` ② 你站点的公开域名 `<SITE>_PUBLIC_ORIGIN` ③ EverLink 自己的库 `EVERLINK_DATABASE_URL` ④ 一个 LLM（Bedrock）⑤ 一个 cron（`0 3 * * *`）。每行注明"用什么方式配 + 为什么需要"。
- 新增**双库模型 ASCII 图**：源库（只读，数据源）→ EverLink 读；EverLink 自己的库 ← 业务过程数据；强调"永不写你的源库"（`db._assert_writable`）。
- 修正 line 288：把 "absolutizes them against `https://flashdeals.today` (see `adapters.SITE_BASE_URL`)" 改为 "absolutizes them against the site's configured public origin (`<SITE>_PUBLIC_ORIGIN` env var — set your own; nothing is hardcoded)"。

**board 新增 `/how-it-works` 页**（`board/app/how-it-works/page.tsx`）
- 复用现有设计语言：zinc 卡片 / sky 强调 / lucide 图标；直接复用 `Pipeline`（六阶段流水线）与 `AutomationPanel`（cron）组件，不新造复杂交互。
- 信息架构（一屏看懂）：① 一句话定位 + "开源/自托管/非 SaaS" 三徽章 ② 双库模型图 ③ 六阶段流水线（`Pipeline`）④ 部署者契约 5 步卡片 ⑤ cron 怎么跑（`AutomationPanel`）⑥ "这是示例部署"说明（三站是 maintainer dogfooding）。
- **只读、静态**：不含任何写操作、不接收任何 secret。它是 DEPLOYMENT.md 核心的可视化，不是实时状态检测（后者需 `site_configs`，已入 Backlog）。
- `board/components/nav.tsx` 的 `LINKS` 数组新增一项：`{ href: "/how-it-works", label: "How it works", icon: <lucide> }`（置于 Home 之后）。

### 5.3 【P1·E】文档清理 + sandcart 定位为示例键

- **对外展示层**统一 FlashDeals：`board/lib/utils.ts` 的 `SITE_LABEL`（sandcart→FlashDeals，t3 已加）保留；README/ARCHITECTURE 的 sandcart 一律标注 "= FlashDeals（maintainer dogfooding 示例键）"。
- **技术标识符层**（DB `site` 值、`SANDCART_DATABASE_URL`、`slots_sandcart.csv`、`SITES` 元组）**保留不动**（N2），但在 README/CONTRIBUTING 明确："这三个站点键是 maintainer 的示例；你部署时用自己的站点键 + `<SITE>_DATABASE_URL` + `<SITE>_PUBLIC_ORIGIN`。"
- `ARCHITECTURE.md`（line 23/235 的 sandcart 节点）补一句示例键说明；图结构不变。
- `DEPLOYMENT.md`：Data provisioning 段补 `<SITE>_PUBLIC_ORIGIN` 配置（env 方式）；Env var reference 表新增该变量行。
- `CONTRIBUTING.md`：house rules 补一条"origin/域名绝不硬编码进仓库，只走部署者 env"。

### 5.4 【P1·F】诚实数据修复（不手工篡改生产库）

1. 部署侧配好 `SANDCART_PUBLIC_ORIGIN`（= flashdeals.today）。
2. **正当重摄取**：`python scripts/export_slots.py`（重导出 CSV）→ `python -m everlink scan --site sandcart`（`upsert_link_slots` 以绝对 URL 覆盖 link_slots）。让数据流自己携带正确 origin，而非手工 UPDATE。
3. **退役误报卡**：`python -m everlink recheck --apply`（对因相对 URL 而误判 `needs_human_recheck` 的卡，重探测健康后诚实 reject + audit）。
4. 假 Amazon seed 槽（`seed.py` t2 已改）随重摄取/重放自然修正。
5. 全程用**全新独立连接**验证持久化（吸取 psycopg3 事务嵌套"假成功"教训）。

---

## 6. 受影响文件清单

| 文件 | 改动 | 优先级 |
|---|---|---|
| `everlink/adapters.py` | 删 `SITE_BASE_URL`；加 `resolve_origin(site)`；`absolutize_slot_url(url, origin)` 纯函数化；`_row_to_slot` 调用点改 | P0 |
| `.env.example` | 新增 `<SITE>_PUBLIC_ORIGIN` 段 + 注释 | P0 |
| `README.md` | 顶部重构（定位/契约表/双库图/NOT-SaaS）；修 line 288；sandcart 示例键定位 | P0 |
| `board/app/how-it-works/page.tsx` | 新建：原理 + 双库 + 契约 + 流水线 + cron（复用组件） | P0 |
| `board/components/nav.tsx` | `LINKS` 加 How it works | P0 |
| `tests/test_adapters.py` | origin 注入/未配置/绝对URL不双前缀 的用例改 | P0 |
| `DEPLOYMENT.md` | 补 origin env 配置 + env reference 行 | P1 |
| `ARCHITECTURE.md` | sandcart 节点补示例键说明 | P1 |
| `CONTRIBUTING.md` | 补"origin 不硬编码"house rule | P1 |
| `board/README.md` | 提 `/how-it-works` | P1 |
| 生产数据（重摄取/recheck） | 非文件改动，运维执行 | P1 |

---

## 7. 验证步骤

1. `python -m pytest -q` 全绿；重点 `tests/test_adapters.py`：
   - 设 `SANDCART_PUBLIC_ORIGIN` 时相对 URL 正确绝对化；
   - 未设时相对 URL 原样返回（不猜域名）；
   - 已绝对 URL 不被双前缀。
2. `grep -rn "SITE_BASE_URL\|flashdeals.today" everlink/` 应只剩**注释/文档示例**，无功能性硬编码。
3. `cd board && npm run typecheck && npm run build` 全绿（**无 DB 也过**——`/how-it-works` 是静态页，不调 `getSql()`）。
4. 本地 `npm run dev` 打开 `/how-it-works`：一屏看懂定位/双库/契约/cron；nav 高亮正确；明暗主题正常。
5. README 渲染检查：顶部 3 行定位 + 契约表 + 双库图在 GitHub 正常渲染。
6. 数据修复后走代理诚实验证：board 上 sandcart 槽显示 FlashDeals + 绝对 URL；误报卡已退役；无假 Amazon 链接。

---

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 改 `absolutize_slot_url` 签名破坏调用点 | 全仓 grep 调用点（仅 `_row_to_slot`）；测试覆盖 |
| 部署者忘配 `<SITE>_PUBLIC_ORIGIN` 致相对 URL 未绝对化 | 未配置时诚实原样返回 + scan 报告提示；README/契约表显著列出；不静默猜域名 |
| board 新页误引入 DB 依赖致无 DB 构建失败 | `/how-it-works` 纯静态、不调 `getSql()`；build 验证 |
| 重摄取/recheck 误伤真实问题卡 | recheck 默认 dry-run，`--apply` 仅退役全健康卡；`--confirm N` 防 bot 抖动；独立连接验证 |
| 生产 DB 操作重蹈"假成功" | 用全新独立连接复核持久化；顶层事务块；不手工 UPDATE 业务数据 |

---

## 9. Backlog（冲刺后，非本 spec）

- 可写 web UI 配置管理 + `site_configs` 表（需先解决 board/agent env 不共享与 board 写职责扩展）。
- `sandcart` → `flashdeals` 物理重命名（DB site 值迁移 + env 变量改名 + CSV 改名 + Railway 配置同步）。
- 多站点自助 onboarding 向导（真正的"填表单接入"）。

---

## 10. 自审修订

- v1（2026-09-05）：初版含 `site_configs` DB 表 + 可写 `/setup` + `sandcart` 物理重命名。
- v2（2026-09-05，本版）：经 8 角色对抗式审核，砍掉可写配置/DB 表/物理重命名，origin 收敛为 env-only，`/setup` 并入只读 `/how-it-works`。范围聚焦、契合第一性、10 天可交付。决策依据见 §4。
