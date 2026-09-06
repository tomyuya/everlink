# EverLink 部署、配置与使用操作手册

> **版本**：2026-09-06（对应仓库 commit `0378739` 及之后的 main 分支）
> **适用对象**：首次接触 EverLink 的部署者 / 日常运维者 / 评审演示者
> **仓库**：https://github.com/tomyuya/everlink （MIT，开源、自托管、**非 SaaS**）
> **配套文档**：仓库内 `README.md`（定位与架构）、`DEPLOYMENT.md`（部署 runbook 原文）、
> `DEMO_SCRIPT.md` / `DEMO_RUNSHEET.md`（演示脚本）、`docs/specs/`（设计规格）
> **本手册与旧版关系**：取代 `sunshine\操作手册\EverLink 用户使用操作手册.md` 中的部署/配置章节，
> 并补入 2026-09-06 生产实踩的全部坑位（cron、只读锁、env 引号等）。

---

## 0. 怎么读这本手册

| 你的目标 | 直接跳到 |
|---|---|
| 先搞懂它是什么、安全模型是什么 | §1 |
| 本地跑起来玩一玩（不碰云） | §2 |
| 查某个环境变量 / CLI 参数 | §3 / §4 |
| 把它部署上线（Neon + Vercel + Railway） | §5 |
| 接入自己的网站 | §6 |
| 日常审核卡片、看报表 | §7 |
| 出事排查 / 避坑 | §8 / §9 / §10 |

---

## 1. 五分钟理解 EverLink

### 1.1 一句话定位

EverLink 是一个**自主链接腐烂（link-rot）巡检 agent**：每天定时扫描内容站的外链，
用 LLM 裁判（Judge）给出修复提案，把**有风险的修复**交给人类在 Decision Board 上审批，
审批通过后才由 Writer 执行"快照→写入→复探→失败回滚"的受控写回。
人类只审批风险决策，其余全自动——这是 AWS "Agents for Humans" 黑客松的命题核心。

> **两条数据来路（先记住这条，别被"双库"误导成"必须接库"）**：EverLink 起步**不需要**接你的数据库。
> - **路径 A · generic 只读爬取（默认，零配置）**：`scan --site <你站的 sitemap/页面 URL>`
>   以只读 HTTP 抓公开网页、现场提取外链生成 slot——**任何网站都可用、零代码、L1/L2 检测零 AWS 凭证、永不写回**，
>   遵守 robots.txt、≤1 请求/链接、礼貌限速。这是新用户的默认上手路径（详见 §6.1）。
> - **路径 B · 第一方库快照（可选，深度）**：只读接**你自己的**源库（`<SITE>_DATABASE_URL` +
>   `scripts/export_slots.py` 导出 `data/slots_<site>.csv`），换取块级 slot 与受控写回（详见 §6.2）。
>
> 下面的"双库模型"讲的是**写安全边界**（无论走 A 还是 B，EverLink 只写自有库、绝不写源站）；
> 其中的"源站数据库"属**路径 B 的可选项**，不是使用前提。

### 1.2 双库模型（最重要的安全边界）

```
源站生产库（AethelGem / FlashDeals / HotDeals）        EverLink 自有库（Neon Postgres）
┌────────────────────────────────────┐        ┌──────────────────────────────────┐
│ 文章 / 商品 / 链接                  │        │ link_slots      链接镜像          │
│                                    │  只读   │ slot_checks     每轮探测结果      │
│  EverLink  NEVER writes here  ◄────┼──SELECT─┤ decisions       决策卡队列        │
│  （连接后 SET read_only = on）      │        │ audit_log       全链路审计        │
│                                    │        │ write_snapshots 写回前后快照      │
└────────────────────────────────────┘        └──────────────▲───────────────────┘
                                                             │ 唯一写入口（受控）
                                                    Writer：snapshot → apply → verify
                                                    → 失败 rollback + dead-letter
```

要点：
- 对源站库**永远只读**（连接后执行 `SET default_transaction_read_only = on`）。
- EverLink 的所有写都落在**自有库**：写回 = 更新 `link_slots` 镜像行 + 留 `write_snapshots` 审计，
  **绝不写源站生产库**。接真实 CMS 属明确非目标（roadmap 之外）。
- 写回白名单 `WRITEBACK_SITES = ("aethelgem",)`（`everlink/writer.py`）：白名单外的站
  即使卡片被批准也返回 `skipped`（不是错误、不进 dead-letter）。
- **AethelGem / FlashDeals（内部键 `sandcart`）/ HotDeals 是 maintainer 自己运营的
  demo 样例站点**：公开部署以这三站为例做扫描与展示，其数据仅用于演示机制；
  自托管时接入的是**你自己的站**（§6），样例站不构成任何绑定。
- 双侧写保护：agent 侧 `db._assert_writable`、board 侧 `assertBoardWritable`，
  禁止任何写指向源站 host 或禁用名单（`EVERLINK_FORBIDDEN_HOSTS`）。

### 1.3 三 agent 流水线

`Scanner → Judge → Writer`，顺序单责（非 Swarm）：
1. **Scanner**：L1 HTTP 探测（每链接 ≤1 请求）+ L2 选择性页面解析（软 404 嫌疑才二次请求）。**检测不需要 LLM**。
2. **Judge**：Strands SDK agent，对问题 slot 产出修复提案；带 spec §6 steering hooks，
   不安全提案会被 hook 拦截/重导（`steering_cancel` 审计事件）。生产后端 = **qwen via Bedrock Mantle**（真 LLM）。
3. **Writer**：只处理**已批准**的卡片，执行 snapshot → apply → verify（复探必须 Healthy）
   → 失败 rollback 并 dead-letter 为 rejected。

### 1.4 决策卡生命周期

```
scan 发现问题 → Judge 提案 → 聚合成决策卡 [pending]
        ├─ 人类 approve → [approved] → worker 领取 → 写回+复探成功 → [applied]
        │                                          └─ 复探失败 → rollback → [rejected](dead-letter)
        ├─ 人类 reject（记录 reason，agent 记得）→ [rejected]
        └─ recheck 证实误报 → [rejected]（自动 reason + false_positive_retired 审计）
```
跨文章的**同一条死链**会聚合成**一张卡**，人类只审一次。

### 1.5 诚实标签（演示/素材语境）

| 标签 | 含义 |
|---|---|
| `[REAL]` | 生产真实运行产出 |
| `[SEEDED REPLAY]` | 种子数据回放（演示库填充） |
| `[EST.]` | 估算值 |

### 1.6 用之前必须懂的 6 个概念

看懂这 6 个词，后面所有命令的输出、board 上的每张卡你都能读明白。

**① LinkSlot（链接槽）与它的角色**
一条"待巡检的外链位置"：属于哪个站、在哪篇文章的哪个区块、原始 URL、以及**角色**（决定它能被怎么修）：

| 角色 slot_type | 含义 | 修复约束 |
|---|---|---|
| `component` | 商品/组件链接（正文里的可点外链） | 可 REPLACE_URL / REWRITE |
| `commercial` | 商业/联盟链接（带 tracking） | 可修，但跳转丢 tag → `program_ended` |
| `reference` | 参考引用链接 | **永不 REPLACE_URL**（ScopePolicy 硬拦，只能改写或上报） |
| `internal` | 站内内链 | generic 默认不报，`--include-internal` 才纳入 |

**② 检测金字塔 L1 / L2（先便宜后昂贵）**
- **L1（HTTP 层）**：每链接 ≤1 请求，看状态码 + 分析跳转链。例：联盟跳转中途**丢掉 tracking 参数** → 判 `program_ended`（你白导流）。
- **L2（页面解析层）**：隐身抓正文，看"价格块消失 / Currently unavailable / 缺货"。**只有 L1 拿不准时才花 L2**。
- 不使用任何商品 API（PA-API / RapidAPI / RainForest 均已停用）。被反爬拦截或超时 → `needs_human_recheck`，**绝不编造**。

**③ 决策卡的三套词表**
一张卡 = 一个 **verdict（检测结论）** + 一个 **action（建议动作）** + 一个 **risk**，状态机见 §1.4。

| verdict 结论 | action 动作 |
|---|---|
| `healthy` 健康 | `REPLACE_URL` 换更好的替代链接 |
| `dead` 死链 | `REWRITE_ANCHOR` 改锚文本 |
| `program_ended` 联盟计划结束 | `REWRITE_SENTENCE` 改写整句（与落地页现状对齐） |
| `offer_changed` 报价变化 | `DROP_BLOCK` 删区块（仅附带性角色） |
| `needs_human_recheck` 需人工复查 | `ESCALATE_HUMAN` 交还人类（拿不准/修复已回滚） |

> **合并规则**：`merge_key = scheme+host+path`（忽略 tracking query 与 fragment）。跨文章的**同一条死链**合并成**一张卡**，代表提案取组内**最高 risk**（fail-safe），人只审一次、批准即治愈全部受影响 slot。

**④ Steering 护栏（创意核心：测的 = 拦的，零漂移）**
`policy.py` 是**唯一真相源**——Evals 打分与运行时 hook 强制用**同一套纯函数**，所以评估测到的违规正是生产会拦下的。三条**硬拦**规则 + 一道写闸门：

| 护栏 | 机制 | 效果 |
|---|---|---|
| **披露零改动** DisclosurePolicy | 三层判定：结构免疫（block_type/role 是披露块）/ 显式 `protected=1` / 关键词正则（affiliate、commission、sponsored…），**任一层命中即保护**（fail-safe） | 受保护 slot 绝不能被任何 MODIFYING_ACTION 触碰，只能 `ESCALATE_HUMAN` |
| **reference 零改向** ScopePolicy | `slot_type=reference` 遇 `REPLACE_URL` → 违规 | 参考链接永不被重新指向 |
| **拿不准只能上报** verification | `verdict=needs_human_recheck`（=探测被拒/可达性未知）时唯一合法动作是 `ESCALATE_HUMAN` | 禁止在"不确定的测量"上改真内容，避免把探测局限变成误改 |
| **写闸门** WritePolicy（`steering.make_write_gate` hook） | Writer 任何写工具调用**必须携带已批准 `decision_id`**，否则 `BeforeToolCall` 直接拒绝 | 没有人的批准，就没有任何写入 |

> `REWRITE_SENTENCE` 还有一条**编辑约束（EditorialPolicy）**：改写必须保留或显式降级原事实主张——由 Judge prompt 约束 + 高风险路由到人审兜底（非 oracle 硬拦，属软约束）。护栏默认**开启**，`--no-enforce` 才关（不建议关）。

**⑤ Interrupt 双轨（同一个写闸门，两种"等人拍板"）**
- **同步 gate（`make_sync_approval_gate`）**：现场 demo 用。high-risk 提案触发 Strands 原生 `event.interrupt`，暂停 agent loop、在 `AgentResult.interrupts` 浮现；operator 回 `A` 批准、其余拒绝，`run_judge_sync` 续跑。
- **异步持久队列（`DecisionWorker`）**：生产用。决策卡落 `decisions` 表，人在 board / 通知里 out-of-band 批准，worker 轮询 `claim_next_approved` → 派发 Writer → `mark_applied`。
- 两轨 gate **同一个 high-risk 修复、同坐 write_gate、同一 `Proposal` schema**——未批准动作永远到不了站点。

**⑥ needs_human_recheck（诚实降级，EverLink 的"人品"）**
探测被反爬墙挡住、超时、或证据不足时，它**不瞎猜结论**，而是老实说"这个我拿不准，请人复查"，并生成一张 `ESCALATE_HUMAN` 卡交还给你。scan 结果**全是** `needs_human_recheck` 通常意味着目标站（如 Amazon）用验证码挡住了 L2——**这是正确的降级，不是 bug**（可 `--no-l2` 只看 L1，或换自家站测）。

### 1.7 安全护栏一览（为什么它不会搞坏你的站）

以下护栏**全部在代码里强制执行**，不是口头承诺：

| 护栏 | 机制 | 效果 |
|---|---|---|
| **源站只读** | 连接源站后立刻 `SET default_transaction_read_only = on` | 对源站物理上只能读、不能写 |
| **写护栏 deny-list** | `db._assert_writable` 检查目标 DSN 主机：命中任一源站连接变量或 `EVERLINK_FORBIDDEN_HOSTS` → 抛 `ProductionWriteRefused` | 生产源站实例永远不可能被写，即使手滑 |
| **只写自己的库** | 所有写回只进 EverLink 自有 `EVERLINK_DATABASE_URL`（镜像行 + 快照审计） | 业务库与 EverLink 操作库物理隔离 |
| **三层披露保护** | 见 §1.6 DisclosurePolicy | 合规文案结构性免疫 |
| **写闸门** | 见 §1.6 WritePolicy（Hooks） | 无批准 = 无写入 |
| **写前快照 + 复探 + 回滚** | snapshot → apply → verify_fix；失败即 rollback + dead-letter | 改错能自动撤销，不留脏数据 |
| **写回白名单** | `WRITEBACK_SITES = ("aethelgem",)`；名单外即使批准也 `skipped`（非错误、不进死信） | 写回范围可控、可审计 |
| **诚实降级** | 被拦/超时/证据不足 → `needs_human_recheck` | 绝不编造检测结果 |
| **密钥零入库** | 仓库只有 `.env.example`；真实 `.env` / 凭证 / 导出 CSV 全 gitignore | 公开仓库无任何密钥 |

---

## 2. 本地快速开始

### 2.1 前提

- Python ≥ 3.11（仓库按 3.12 验证）、git
- 可选：本地 Postgres（或用 Neon 免费实例）；**检测类功能零 AWS 凭证可跑**

### 2.2 安装

```bash
git clone https://github.com/tomyuya/everlink.git
cd everlink
python -m venv .venv && .venv\Scripts\activate        # Windows
pip install -e ".[dev]"                                # 含 pytest / strands 依赖
```

### 2.3 最小 env

复制 `.env.example` → `.env`，**最少只填一个变量**即可跑检测：

```ini
EVERLINK_DATABASE_URL=postgresql://user:pass@host/neondb?sslmode=require
```

schema 在**首次连接时幂等自建**（`db.ensure_schema` 读 `schema.sql`），无需手工 DDL。
不填 DSN 也能跑 `scan --dry-run`（纯只读报告，不落库）。

> **源数据从哪来？** `EVERLINK_DATABASE_URL` 是 EverLink **自有过程台账库**（探测结果/决策卡/
> 审计），**不是源站数据库**。被监测的链接数据两条来路，都不依赖这个变量：
> 1. **generic 实时爬取（新用户默认路径）**：`scan --site <你站 sitemap/页面 URL>` 以只读
>    HTTP 抓目标站公开网页、现场提取外链——**无需任何源库配置**（§6.1）；
> 2. **first-party CSV 快照（深度路径）**：**部署者本人**对**自己的**源库跑
>    `scripts/export_slots.py`（`<SITE>_DATABASE_URL` / env 三兄弟，仅导出那一刻用）生成
>    `data/slots_<site>.csv`；仓库自带三份 CSV 是 maintainer 的 demo 样例站镜像（§6.2）。
>
> 即：源数据永远由"你自己"从"你自己的站"取得（爬或导出）；EverLink 自有库只记过程台账。

### 2.4 第一次只读扫描

```bash
# 任意网站，零凭证、零写库：
python -m everlink scan --site https://example.com/sitemap.xml --dry-run

# 仓库自带的第一方站快照（data/slots_*.csv 已随仓库提交）：
python -m everlink scan --site aethelgem --dry-run --judge none
```

看到 `scan report ... verdicts: {...}` 即成功。加 `--judge mantle` 才需要 AWS 凭证（见 §3.1）。

### 2.5 测试与离线门禁

```bash
python -m pytest -q                                              # 全绿
python scripts/nightly.py --dry-run --judge none --skip-notify   # cron 编排演练，零变更
python scripts/verify_bedrock.py                                 # 有凭证时：Bedrock 连通验证
python scripts/run_evals.py                                      # Strands Evals 评估套件（spec §8）
```

### 2.6 从最安全到最真实：7 个渐进式练手场景

新手请**从 A 开始逐个体验**，每一步都比上一步更"真"一点。统一入口 `python -m everlink <子命令>`（在仓库根、已激活 venv）。

| 场景 | 命令 | 你会看到 / 注意 |
|---|---|---|
| **A 离线试跑**（最安全：不写库、不发通知、不需 AWS） | `python -m everlink scan --site aethelgem --limit 20 --judge stub --dry-run` | `stub` = 离线确定性假模型；`--dry-run` = 什么都不写 |
| **B 真实检测一个站**（仍不写库） | `python -m everlink scan --site aethelgem --limit 50 --judge none --dry-run` | `none` = 仅检测零凭证；对 Amazon 等常撞反爬 → 诚实判 `needs_human_recheck`（正确，非 bug）；L2 每链约 15~20s，可 `--no-l2` 加速 |
| **C 扫任意站/sitemap**（不限于三个样例站） | `python -m everlink scan --site https://any-site/sitemap.xml --limit 30 --judge none --dry-run` | 走 generic 只读适配器（§6.1），零代码零凭证 |
| **D 看收件箱**（需先配 `EVERLINK_DATABASE_URL`） | `python -m everlink decisions --status pending` ／ `--json` | 未配 DSN 会打印 `unavailable` 并 exit 2（设计好的降级，不是崩溃） |
| **E 批准/拒绝一张卡** | `python -m everlink decide dec-abc123 --approve` ／ `--reject --reason "披露块受保护，不动"` | 与 board 走同一 `DecisionStore`；reject 的 reason 会被 agent 记住 |
| **F 执行已批准的修复**（worker 写回） | `python -m everlink worker --once` ／ `--once --handler null`（安全空跑：标 applied 但不真写） | 每张卡：snapshot → apply → verify_fix 复探；失败自动 rollback + dead-letter + 交还你一张 `ESCALATE_HUMAN` |
| **G 一键全自动**（生产 cron 就跑这一条） | `python scripts/nightly.py`（离线冒烟：`--dry-run --judge none`） | scan→notify→worker --once→（周一）report，编排极薄、无隐藏逻辑、审计与手动逐字节一致（§4.8） |

> 想看 board 有东西可展示：`python scripts/seed_demo.py --dry-run` 先看计划，去掉 `--dry-run` 注入 **[SEEDED REPLAY]** 演示数据（每行带 `demo-seed` 标记，`--reset` 可干净移除、不碰真实数据）。board 打开为空是**正常空状态**，不是 bug。

---

## 3. 环境变量全量参考

### 3.1 Agent 侧（Railway / 本地）

| 变量 | 必需 | 用途与注意 |
|---|---|---|
| `EVERLINK_DATABASE_URL` | ✅ | EverLink **自有** Neon 池化 DSN；board 共用同一条 |
| `AWS_REGION` | Judge 需要 | 生产 `us-east-1` |
| `BEDROCK_MODEL_ID` | Judge=bedrock 时 | 直连 Claude 用，如 `us.anthropic.claude-sonnet-4-6` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Judge 需要 | 或挂 IAM role；**永不硬编码/进仓** |
| `EVERLINK_JUDGE` | 可选 | `mantle`（**代码级默认**：qwen via Bedrock Mantle 网关，绕过账户级 Anthropic allowlist 门）/ `bedrock`（直连 Claude）/ `stub`（离线 fixture）/ `none`（仅检测） |
| `BEDROCK_MANTLE_API_KEY` | 可选 | 本地/demo 路径：控制台 mint 的 key 原样作 OpenAI api_key；**生产/IAM 留空**=按需自动 mint bearer token（长任务不怕 token 过期） |
| `BEDROCK_MANTLE_MODEL_ID` | 可选 | 默认 `qwen.qwen3-next-80b-a3b-instruct`（**非 reasoning**，选型理由见 §8 坑 11） |
| `BEDROCK_MANTLE_REASONING` | 可选 | `reasoning_effort`；默认留空；仅当换 reasoning 模型时设（如 `low`）并接受其多轮限制 |
| `EVERLINK_NIGHTLY_SITES` | 可选 | 默认 `aethelgem,sandcart,hotdeals` |
| `EVERLINK_WEEKLY_DAY` | 可选 | 周报并入 nightly 的星期几，默认 `mon` |
| `EVERLINK_CRON_ORIGIN` | 可选 | `railway` = 即使 Railway 自己的 `RAILWAY_*` 变量不在，也能把台账行归因到平台。board 只把 `[railway]` 行当作 cron 已接线的证据（`nightly.run_origin`），所以笔记本上排练一次永远无法解锁 *Run now* |
| `EVERLINK_FORBIDDEN_HOSTS` | 可选 | 写保护额外 deny-list（host 片段） |
| `RESEND_API_KEY` / `RESEND_FROM` / `EVERLINK_NOTIFY_EMAIL` | 邮件推送 | **三者齐备**邮件通道才激活，缺一即 `skipped` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 可选 | 第二推送通道 |
| `EVERLINK_BOARD_URL` | 建议 | board 根 URL；通知里深链 `/inbox`、`/decision/<id>`、`/report` |
| `<SITE>_PUBLIC_ORIGIN` | 视站而定 | 源库存**相对路径**内链时必须设（如 `SANDCART_PUBLIC_ORIGIN=https://…`），否则无 scheme URL 被 SSRF guard 拒绝、整站误报 `needs_human_recheck`；未设=保持相对原样，**绝不猜域名** |
| `AETHELGEM_/SANDCART_/HOTDEALS_DATABASE_URL` | 仅导出脚本 | 只读源库 DSN，`scripts/export_slots.py` 用；nightly 不用 |
| `EVERLINK_AEG_ENV` / `EVERLINK_SANDCART_ENV` / `EVERLINK_HOTDEALS_ENV` | 仅导出脚本 | 各源项目 **.env 的绝对路径**；`export_slots.py` 运行时从中解析 DSN（仓库不硬编码）；留空=跳过该站 |
| `EVERLINK_FORCE` | 可选 | `1` = CSV 已存在也强制重新导出 |
| `FIXTURE_PORT` | 仅测试 | 离线 fixture server 端口，默认 8787 |
| `EVERLINK_ALLOW_LOCALNET` | **生产禁设** | `1` 关闭 SSRF guard 的私网拦截；fixture server 自动设；生产留空=全保护 |
| `EVERLINK_HTTP_TRUST_ENV` | 可选 | `1` = 探测/爬取信任系统代理 env；默认直连（信号更真、环境更封闭） |

> ⚠️ **AWS 凭证空值陷阱**：`AWS_PROFILE=` / `AWS_ACCESS_KEY_ID=` 即使**值为空**也算"已设置"，
> botocore 会优先空值而忽略 `~/.aws/credentials`——表现为 `aws sts get-caller-identity` 正常、
> 但 Mantle token mint 报 "Failed to mint Bedrock Mantle bearer token … Verify your AWS credentials"。
> 不用就**整行注释掉**，不要留空值。

### 3.2 Board 侧（Vercel）

| 变量 | 必需 | 用途与注意 |
|---|---|---|
| `EVERLINK_DATABASE_URL` | ✅ | 与 agent 同一条 Neon DSN（board 只读 + 决策状态 transition） |
| `EVERLINK_FORBIDDEN_HOSTS` | 可选 | 同 agent 侧写保护 |
| `NEXT_PUBLIC_BOARD_READONLY` | 可选 | `1` = 公开只读视图（隐藏勾选框/按钮）。**`NEXT_PUBLIC_` 前缀变量是构建期内联**：增删改后必须触发**重新构建**才生效（见 §8 坑 2） |

### 3.3 平台行为备注

- **Railway 环境变量名与值都不得含英文双引号 `"`**，否则 Railpack 构建报
  `secret ID missing for "" environment variable`。
- Railway 付费账户**不支持 CLI 自动部署**：首次部署必须在 Dashboard 手动连 GitHub 仓库。

---

## 4. CLI 命令参考（`python -m everlink …`）

### 4.1 `scan` — 发现 + 检测链接腐烂（只读）

```bash
python -m everlink scan --site <第一方key|页面URL|sitemap URL> [选项]
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--site` | 必需 | `aethelgem` / `sandcart`(FlashDeals) / `hotdeals` 走 CSV 快照；**其他任何输入**走 generic 只读适配器（sitemap/页面/URL 列表自动识别） |
| `--limit` | 25 | 最多扫多少 slot |
| `--rate-delay` | 1.0 | 请求间隔秒（礼貌线，别调太低） |
| `--timeout` | 15.0 | 单请求超时 |
| `--no-l2` | off | 只跑 L1，跳过页面解析 |
| `--judge` | `none` | `none`=仅检测（零凭证）/`stub`/`bedrock`/`mantle` |
| `--no-enforce` | off | 关闭 steering hooks（默认开启，会拦截不安全提案） |
| `--dry-run` | off | **任何库都不写** |
| `--max-pages` | generic:25 | generic 适配器最多爬几页 |
| `--include-internal` | off | generic：也报告同 host 内链 |

输出解读：`verdicts` 计数 → 问题链接清单（L1 状态 / L2 判定 / 证据 / 提案 risk）→
决策卡聚合数（high-risk 单卡审批、其余可批量）。非 dry-run 时写 `slot_checks` + `audit_log`
并幂等入队 pending 卡（**已决卡不会被重扫复活**）。

### 4.2 `decisions` — 查看决策队列（board 的读模型）

```bash
python -m everlink decisions --status pending --limit 20
python -m everlink decisions --json        # 与 board /api 同构的 JSON
```
`--status`：`all|pending|approved|rejected|expired|applied`（默认 pending）。

### 4.3 `decide` — 人工审批单卡（board 按钮的 CLI 双胞胎）

```bash
python -m everlink decide dec-abc123 --approve
python -m everlink decide dec-abc123 --reject --reason "披露块受保护，不动"
```
与 board 走**同一个** `DecisionStore` transition；reject 的 reason 会被 agent 记住。

### 4.4 `recheck` — 用当前检测器复探 pending 卡、退役误报

```bash
python -m everlink recheck                 # 默认 dry-run：只打印将退役的卡
python -m everlink recheck --confirm 3 --apply   # 连续 3 次全 Healthy 才退役并审计
```
- 只有**所有 slot 都复探 Healthy** 才判定误报；任一仍坏 = 真问题，原样保留。
- `--confirm N`：对抗 bot-wall 主机（如 Amazon）"一次好一次坏"的抖动；
  判定翻转的卡报 **UNSTABLE**，留给人工，不静默退役。

### 4.5 `worker` — 领取并执行已批准卡片（异步 Interrupt 轨道）

```bash
python -m everlink worker --once                     # 轮询一次即退（nightly 用）
python -m everlink worker --interval 5               # 常驻轮询，Ctrl-C 停
python -m everlink worker --once --handler null      # 安全 no-op：标记 applied 但不写
```
`--handler writer`（默认）= 真写回链：snapshot → apply → verify（复探 Healthy 才算成功）
→ 失败 rollback + dead-letter 为 rejected；全程审计。只写 EverLink 自有镜像。

### 4.6 `notify` — 推送给运维者（Resend 邮件 / Telegram）

```bash
python -m everlink notify --dry-run          # 只排版打印，零网络发送
python -m everlink notify                    # 风险路由：medium/high 单卡即推，low 汇总批量
python -m everlink notify --brief            # 晨报 digest
python -m everlink notify --channel email    # 限定单通道
```
投递结果诚实报告：`sent`（真 2xx）/ `skipped`（通道无凭证）/ `failed`（4xx/5xx/传输错误）；
每次真推送写 `audit_log` 的 `notify` 行。

### 4.7 `report` — 周报（board /report 的数字镜像）

```bash
python -m everlink report --dry-run          # 排版预览
python -m everlink report --json             # 与 /api/report 同构
python -m everlink report --days 7           # 推送周报
```
Python 与 board `/report` 跑**同一组五个聚合**，数字永不漂移。

### 4.8 `scripts/nightly.py` — 全链路 cron 入口（调度器唯一命令）

按序驱动**与人工 CLI 完全相同**的子命令（编排极薄、`plan_steps` 是纯函数、有单测）：

| 步 | 内容 | 备注 |
|---|---|---|
| 1 | `scan --site <each> --judge <backend>` | 每站一轮；源站只读 |
| 2 | `notify` | 推送新 surfaced 的卡；`--skip-notify` 可跳 |
| 3 | `worker --once --handler writer` | 领取人类已批准的卡；**`--dry-run` 时诚实跳过**（它会写） |
| 4 | `report` | 仅当当天 = `--weekly-day`（默认 mon）或 `--weekly` 强制 |

**诚实降级语义**（不造假）：单步 exit 2 = degraded（如 Judge 不可用→检测仍跑完）**链继续**；
单步抛异常 = -1 记录后继续（一站坏不掉整晚）；summary 逐步打印 ok/degraded/FAIL/skip。
常用参数：`--sites` / `--judge` / `--limit` / `--channel` / `--brief` / `--handler` /
`--weekly` / `--weekly-day` / `--days` / `--skip-notify` / `--skip-worker` / `--dry-run`。

### 4.9 随附脚本速查（`scripts/`）

| 脚本 | 用途 |
|---|---|
| `nightly.py` | 全链路 cron 入口（§4.8） |
| `export_slots.py` | 从源库只读导出 `data/slots_<site>.csv`（Phase-A；env  trio 指路） |
| `seed_demo.py` | 演示/离线 DB 填充（[SEEDED REPLAY] 数据来源） |
| `run_evals.py` | Strands Evals 评估套件（spec §8；需凭证） |
| `verify_bedrock.py` / `verify_strands.py` | 凭证/SDK 连通性验证 |
| `fixture_server.py` | 离线 fixture 站（端口 8787，自动设 ALLOW_LOCALNET） |
| `check_links.py` / `scan_site.py` / `load_slots.py` | 单点排查小工具 |
| `discover_schema.py` / `probe_target_tables.py` | 源库 schema 侦察（只读） |
| `probe_samples.py` / `probe_timing.py` | 探测样本/耗时基准 |

---

## 5. 生产部署

### 5.0 拓扑

```
        nightly cron（Railway，03:00 UTC）              人类（邮件 / Telegram）
                 │                                                │
                 ▼                                                ▼
   ┌───────────────────────────┐                   ┌──────────────────────────┐
   │ Railway 服务（Docker）     │  入队 decisions    │ Vercel：Next.js board     │
   │ python scripts/nightly.py │ ────────────────► │ inbox / audit / report    │
   │  1 scan (Scanner→Judge)   │  (Neon Postgres)  │ approve / reject          │
   │  2 notify (Resend/TG)     │ ◄──────────────── │ （仅状态 transition）       │
   │  3 worker (apply+verify)  │   approved 卡片    └──────────────────────────┘
   │  4 report (周一周报)       │
   └───────────────────────────┘
                 │ Bedrock（Judge/Writer LLM）        Neon Postgres（us-east-1）
                 └───────────────────────────────►    decisions / slot_checks /
                                                      audit_log / link_slots / snapshots
```

### 5.1 Neon 数据库

1. console.neon.tech 建项目，region **us-east-1**（与 board 的 Vercel region 同区降延迟）。
2. 复制**池化**连接串（`…-pooler…?sslmode=require`）= `EVERLINK_DATABASE_URL`。
3. schema 首连幂等自建；如需显式应用：`psql "$EVERLINK_DATABASE_URL" -f schema.sql`。
4. 必须是 EverLink **自有**库——永远不要用源站生产库或禁用实例。

### 5.2 Vercel（Decision Board）

board 在 `board/` 子目录（独立 Vercel project root，`board/vercel.json` 锁 framework + **iad1**）。

**Git 集成方式（推荐，本生产即用）**：Vercel Dashboard 导入仓库 → Root Directory 填 `board` →
push main 自动上线。环境变量在 Dashboard 或 CLI 添加：

```bash
vercel env add EVERLINK_DATABASE_URL production
vercel env add EVERLINK_FORBIDDEN_HOSTS production      # 可选
vercel --prod
```

**只读锁开关**：`NEXT_PUBLIC_BOARD_READONLY=1` = 公开"只看不能碰"视图。
本生产部署**不设**此变量 = 完全开放（勾选框 / 批量条 / 单卡 Approve/Reject 全真可用）。
> ⚠️ 该变量是 `NEXT_PUBLIC_` 前缀 → **构建期内联进 JS**。删除/修改后必须等一次重新构建
> （push 或手动 Redeploy）才生效，只删 env 不重建 = 锁还在。

### 5.3 Railway（自主 agent + cron）

仓库根 = Railway 服务根；`Dockerfile` 构建（`railway.json` 锁 `builder: DOCKERFILE`），
镜像 `CMD` = `python scripts/nightly.py`（跑完即退，正是 cron 想要的形状）。

1. **Dashboard 手动接入**（付费账户不支持 CLI 部署）：New Project → Deploy from GitHub repo
   → 确认 Dockerfile builder → 设 Variables（§3.1 全表）。
2. **Cron 必须在 Dashboard 手工设置**（本会话最大坑，见 §8 坑 1）：
   Service → **Settings** →
   - `Cron Schedule` = Custom = `0 * * * *`（小时心跳）
   - `Restart Policy` = **Never**
   - `Custom Start Command` = `python scripts/nightly.py`
   - 可选变量 `EVERLINK_CRON_ORIGIN=railway`（见 §3.1）
   保存后页面应显示下次运行时间。
   > 决定什么时候跑全链路的是**门控**而不是调度本身：小时级 cron 一天写 ~23 条诚实的
   > heartbeat skip，只有命中 board 跑批小时的那次才跑全链——也正是它让 `/settings` 的
   > *Run now* 能在一小时内被接走。日级调度设到跑批小时（`0 3 * * *`）同样会跑全链，
   > 但 *Run now* 会一直锁定、心跳前置条件一天 23 小时是红的。本生产实例目前仍是日级
   > `0 3 * * *`（`nextCronRunAt` 2026-09-07T03:00:00Z），改成小时级是剩下的唯一手工步骤。
3. 手工触发一次全链路（不等 cron）：
   ```bash
   railway run python scripts/nightly.py --dry-run --judge none   # 安全演练
   railway run python scripts/nightly.py                          # 真全链路
   ```

**平台行为两条（实测）**：
- `railway.json` 属 config-as-code（官方弃用中，支持至 2026-12-01）：**只对当次部署生效、
  绝不回写服务设置**。仓库里写的 cronSchedule 历史上从未生效过——调度只认 Dashboard 设置。
- 设置 cron 前，**每次部署都会顺带跑一次 nightly**（含 notify）。设置 cron 后部署变成
  `buildOnly`：只重建镜像、不启动任何容器，下一次 cron fire 跑的就是这个最新镜像。
  实测于 2026-09-06：09:17:52Z push、deploy `bd57dc6b` 于 09:17:55Z SUCCESS 且
  `buildOnly: true`，`nightly_runs` 无新行。所以调度设好之后 push 上线是安全的。

**第一方扫描数据**：`data/slots_*.csv` 随仓库提交并 `COPY` 进镜像，开箱即扫 77 个第一方 slot。
fork 不想带数据进 git 的三个选项：Railway volume 挂 `/app/data`（推荐）/ 私有预构建镜像 /
纯 generic 零数据模式。

### 5.4 部署后验证清单

```bash
cd board && npm run typecheck && npm run build          # board 零错误
python -m pytest -q                                      # agent 全绿
python -m everlink scan --site aethelgem --dry-run       # slot 数与 DB 吻合
python -m everlink decisions --json                      # board 读模型
python -m everlink report --json                         # /api/report 双胞胎
railway status --json | findstr nextCronRunAt            # cron 已排期（非 null）
```
最后打开 Vercel URL → 批准一张卡 → `python -m everlink worker --once` → 卡变 applied
且 `audit_log` 出现 write/verify 行 = 端到端闭环成立。

---

## 6. 站点接入指南

> **内置三站（`aethelgem` / `sandcart` / `hotdeals`）仅为 demo 样例站点**——仓库提交的
> CSV 是 maintainer 自有站点的公开链接镜像，让 fork 者开箱看到完整流水线；
> 生产自托管应接入你自己的站。

**架构上没有站点数量硬上限**（site 只是字符串键；DB 列是 text；board 标签对未知 key 回退原值）。
真实上限是运行成本：nightly 时间窗（单容器串行、每日一次）+ Judge LLM 费用 + 爬取礼貌线；
当前模型舒适区约**几十站 / 万级链接**。

### 6.1 generic 零代码接入（任何站，今天就能用）

```bash
python -m everlink scan --site https://your-site.com/sitemap.xml --judge mantle
```
- 输入自动识别：sitemap（含 `sitemap` 或以 `.xml` 结尾）/ 单页面 / URL 列表。
- 只读爬取、**永不写回**、遵守 robots.txt（fail-open）、描述性 UA、≤1 请求/链接。
- 默认上限：`max_pages=25`、`max_slots=500`/站、页间 1s——防被封的 etiquette，别乱调高。
- L1/L2 检测零 AWS 凭证；只有要 Judge 提案才需要 LLM。

### 6.2 first-party 深度接入清单（要 CSV 快照/块级 slot/可写回时）

1. `everlink/adapters.py` 的 `SITES` 元组加一个 key；
2. env 加 `<SITE>_PUBLIC_ORIGIN`（源库存相对内链时必需）与 `<SITE>_DATABASE_URL`（仅导出用）；
3. 跑 `python scripts/export_slots.py` 生成 `data/slots_<site>.csv`（只含 URL 与 flag，无 secret）；
4. （可选写回）`everlink/writer.py` 的 `WRITEBACK_SITES` 加 key——**不加则默认 skipped，安全**；
5. board 零改动（展示层 `SITE_LABEL` 映射，未知 key 回退原值）。

### 6.3 命名提示

对外文案统一用品牌名（如 FlashDeals），内部标识符保留历史 key（如 `sandcart`）——
board 展示层已有映射；不做物理重命名（风险 > 收益的既有决策）。

---

## 7. 日常运维与 Board 使用

### 7.1 页面导览（生产：everlink-seven.vercel.app）

| 页面 | 看什么 |
|---|---|
| `/` | 唯一产品页：定位四徽章（开源 MIT / 自托管非 SaaS / AWS Strands SDK + Bedrock / 零配置抓取任意站点）+ 六阶段流水线 + 自动化面板（实时排程，以及台账最近一次运行的原样引用——含触发方式与来源，本地排练不会被误读为无人值守的 cron 运行）+ 两种接入路径 + 写入安全边界与部署者契约。（原 `/how-it-works` 已合并至此，308 永久重定向。） |
| `/inbox` | 审核主战场：状态页签（Pending/Approved/Applied/Rejected/All）+ 勾选框 + 批量 Approve/Reject 条 |
| `/decision/<id>` | 单卡详情：提案理由、NEW SENTENCE、证据链（slot 级 L1/L2 证据）、Approve/Reject 真按钮（pending 卡）或 settled 提示（已决卡） |
| `/audit` | 全链路审计流，可按事件过滤（`?event=write` / `verify` / `rollback` / `dead_letter` / `steering_cancel`…） |
| `/report` | 周报数字（healed / created / decided），与 CLI `report` 同构 |
| `/settings` | 控制面：轮换周期与各站覆盖率/日预算、跑批小时（UTC）、cron 总开关、Run now（需先有活的 cron 心跳，且该心跳必须能归因到 Railway——台账每行都带 origin 标记，笔记本上手动跑一次不算）、前置条件清单、cron 台账（含 origin 列） |

### 7.2 审核流程

1. 收邮件/Telegram 推送（medium/high 单卡即推，low 批量清单）→ 点深链进卡。
2. 看证据链：L1 状态、L2 判定、`Open in your browser` 自己开链接复核（反 bot-wall 误判的最后防线）。
3. Approve（进 worker 队列）或 Reject（填 reason，agent 记得）。
4. 批量：inbox 勾选多张低风险卡 → 批量条一次 approve/reject。
5. 次日 nightly 的 worker 步骤执行 approved 卡；`/audit?event=write` 与 `?event=verify`
   各出现一行、卡变 applied、Evidence 复探 Healthy = 闭环完成。

### 7.3 通知与周报

- 每轮 nightly 第 2 步 notify：pending 卡风险路由推送；第 4 步（默认周一）周报。
- 通道激活条件见 §3.1；`notify --dry-run` 可随时预览文案不发送。

---

## 8. 注意事项与坑位清单（生产实踩）

| # | 坑 | 症状 | 根因 | 对策 |
|---|---|---|---|---|
| 1 | **Railway cron 不认 railway.json** | 凌晨没跑、audit 无新行、`nextCronRunAt: null` | config-as-code 只对该次部署生效、不回写服务设置（已弃用） | Dashboard → Settings 手工设 Cron Schedule / Restart / Start Command；验证 `railway status --json` |
| 2 | **NEXT_PUBLIC_ 构建期内联** | 删了只读 env 按钮还是灰 | Vercel 把 `NEXT_PUBLIC_*` 在 build 时烤进 JS | 删/改 env 后必须重新构建（push 或 Redeploy） |
| 3 | **Railway env 含双引号** | 构建报 `secret ID missing for ""` | Railpack 解析空名变量 | 变量名与值都不带 `"` |
| 4 | **部署顺带跑 nightly（仅在设置 cron 之前）** | push 后收到"意外"通知 | 无 cron 调度时 Railway 把它当普通服务、部署即执行一次 start command；设了 cron 后部署为 `buildOnly`，不启动任何东西（实测 2026-09-06 deploy `bd57dc6b`） | 设 cron 前：接受它（=免费补跑）或错峰 push；设 cron 后：无需处理 |
| 5 | **相对内链整站误报** | 全站 `needs_human_recheck` | 无 scheme URL 被 SSRF guard 拒 | 设 `<SITE>_PUBLIC_ORIGIN` |
| 6 | **bot-wall 主机判定抖动** | 同一卡几分钟内 healthy↔offer_changed | Amazon 等对数据中心 IP 交替返回好/坏页 | `recheck --confirm 3` 连续一致才退役；UNSTABLE 留人工 |
| 7 | **railway logs 被 more 分页卡死** | 终端停 `-- More --` | Windows 分页器 | 后台运行或改查 DB / `railway status --json` |
| 8 | **Windows 命令行引号/中文路径 mangle** | `python -c` SyntaxError、curl `-w` 乱码 | 传输层剥引号 | 一律写 UTF-8 脚本文件执行 |
| 9 | **secrets 进仓/进日志** | 安全事故 | — | 只走平台 env；仓库仅 `.env.example`；脚本不打印 DSN |
| 10 | **写回范围误读** | 以为会改源站生产内容 | 文档措辞与代码不对齐 | 记住双库模型：写回只落 EverLink 自有镜像 + 快照审计 |
| 11 | **reasoning 模型跑真 Judge 崩** | 单轮探针正常、真 scan 报 `StructuredOutputException` | gpt-oss 系的 `reasoningContent` 与 Chat Completions 深度多轮（steering hooks + recurse）不兼容 | 默认 qwen 非 reasoning；换 reasoning 模型才设 `BEDROCK_MANTLE_REASONING` 并接受限制 |
| 12 | **AWS 凭证空值** | `aws cli` 正常但 Mantle mint 失败 | 空 `AWS_PROFILE=`/`AWS_ACCESS_KEY_ID=` 仍覆盖凭证链 | 不用就整行注释（§3.1 警告框） |

---

## 9. 实用技巧与验证命令集

```bash
# cron 是否真排期（非 null 才是真的）
railway status --json | findstr /C:"cronSchedule" /C:"nextCronRunAt"

# DB 侧 nightly 是否落库（audit 列名是 ts，不是 created_at）
psql "$EVERLINK_DATABASE_URL" -c "SELECT max(ts), count(*) FROM audit_log;"
psql "$EVERLINK_DATABASE_URL" -c "SELECT status, count(*) FROM decisions GROUP BY 1;"

# 关键事件最后发生时间（write/verify/rollback/dead_letter/notify）
psql "$EVERLINK_DATABASE_URL" -c "SELECT event, max(ts) FROM audit_log GROUP BY 1 ORDER BY 2 DESC;"

# board 开放态 DOM 自检（checkbox 数 > 0 且无 Read-only 字样 = 开放）
curl -s https://<board>/inbox | findstr /C:"checkbox" /C:"Read-only"

# 误报退役三连（先 dry 看清单，再 confirm 复探，最后 apply）
python -m everlink recheck
python -m everlink recheck --confirm 3
python -m everlink recheck --confirm 3 --apply

# 通知文案预览（零发送）
python -m everlink notify --dry-run --brief
```

技巧：
- 演示/录屏前跑 `decisions --json` 核对计数口径，避免口播数字与画面不符。
- 高危卡（high risk）设计上只能**单卡审批**、不进批量——批量条对它无效是特性不是 bug。
- 周报与 `/report` 同源聚合；对外报数一律引用这两处之一，别手算。

---

## 10. 故障排查 FAQ

**Q：凌晨 cron 没跑？**
→ `railway status --json` 看 `nextCronRunAt`。null = Dashboard 没设（坑 1）。
非 null 但没行 = 看 Railway Deployments/Cron Runs 页该次运行日志。

**Q：board 按钮灰 / 出现 "Read-only view"？**
→ `NEXT_PUBLIC_BOARD_READONLY` 存在且为 1，或删了但没重建（坑 2）。

**Q：scan 报 `[everlink] Mantle unavailable` / exit 2？**
→ AWS 凭证/region 问题；离线场景改 `--judge none`（检测照常）或 `stub`。

**Q：notify 全 `skipped`？**
→ 邮件三件套（`RESEND_API_KEY`/`RESEND_FROM`/`EVERLINK_NOTIFY_EMAIL`）没齐，或 TG 两件套没齐。

**Q：approved 卡一直不 applied？**
→ worker 只在 nightly 第 3 步或手工 `worker --once` 时跑；看 `/audit?event=write`
有无该行；复探失败会 rollback + dead-letter 成 rejected（看 `dead_letter` 事件）。

**Q：generic 扫描返回 0 链接？**
→ robots.txt Disallow（fail-open 只针对读取失败，真 Disallow 会遵守）；
或页面链接全是内链（加 `--include-internal`）。

**Q：Windows 控制台打印通知文案乱码/报错？**
→ CLI 已内置 UTF-8 reconfigure；若仍异常用 `set PYTHONIOENCODING=utf-8` 前缀。

**Q：board 打开是空的？**
→ 决策队列没数据（正常空状态，非 bug）。先 `python scripts/seed_demo.py`（demo）或跑一次真实 `scan`（去掉 `--dry-run`）落库。

**Q：worker 报 `ProductionWriteRefused`？**
→ DSN 指向了源站或禁用主机——**护栏正在保护你**。确认 `EVERLINK_DATABASE_URL` 指向 EverLink 自有库，而非任何源站/生产库（§1.7）。

**Q：scan 结果全是 `needs_human_recheck`？**
→ 目标站（如 Amazon）用验证码/反爬墙挡住了 L2。**这是正确的诚实降级**，不是坏了。想快加 `--no-l2` 只看 L1，或换自家样例站测。

**Q：scan 很慢？**
→ L2 对真实站点每链接约 15~20 秒。减小 `--limit`、加 `--no-l2`、或增大 `--rate-delay`。

**Q：找不到 `everlink` 模块 / `npm run dev` 端口被占？**
→ 前者：确认在仓库根目录且已激活 venv。后者：关掉占用进程或 `npm run dev -- -p 3001` 换端口。

---

## 11. 术语与相关文档

| 术语 | 含义 |
|---|---|
| slot / LinkSlot | 一条被监测的链接位（含 site、anchor、url、protected、slot_type 等） |
| slot_type（角色） | `component` 商品/组件 · `commercial` 商业/联盟 · `reference` 参考（永不改向） · `internal` 内链 |
| L1 / L2 | L1=HTTP 状态+跳转链探测（每链 ≤1 请求）；L2=隐身抓正文（软 404/价格消失/缺货），仅 L1 拿不准时才花 |
| verdict（结论） | `healthy` / `dead` / `program_ended` / `offer_changed` / `needs_human_recheck` |
| action（动作） | `REPLACE_URL` / `REWRITE_ANCHOR` / `REWRITE_SENTENCE` / `DROP_BLOCK` / `ESCALATE_HUMAN` |
| 决策卡 decision | 聚合后的待审修复提案（pending→approved/rejected→applied）；同链跨文章合并成一张 |
| steering / policy oracle | `policy.py` 三条硬拦（披露零改动/reference 零改向/拿不准只上报）+ write_gate 写闸门；Evals 与运行时共用同一函数（测的=拦的），审计事件 `steering_cancel` |
| Interrupt 双轨 | 同步 gate（demo 实时批准）+ 异步持久队列 worker（生产 out-of-band 批准），同坐 write_gate |
| needs_human_recheck | 诚实降级标记：探测被拦/超时/证据不足就交给人，绝不编造 |
| snapshot / rollback / dead-letter | 写前快照 / 复探失败自动回滚 / 回滚后入死信并交还人（approved→rejected） |
| StubModel / Mantle | 离线确定性假模型（测试/评估）/ AWS Bedrock 的 OpenAI 兼容网关（生产 Judge 通道，qwen） |
| seed（种子数据） | demo 用的确定性回放数据集，`demo-seed` 标记，可 `--reset` 干净移除 |
| ProductionWriteRefused | 写护栏异常：DSN 指向源站/禁用主机时抛出，保护生产库不被写 |

相关文档：仓库 `README.md` / `DEPLOYMENT.md` / `ARCHITECTURE.md` / `DEVPOST.md` /
`SUBMISSION_CHECKLIST.md` / `docs/specs/2026-09-05-self-hosted-onboarding-and-origin-config-design.md`
（env-only 配置决策出处）；旧版手册 `sunshine\操作手册\EverLink 用户使用操作手册.md`（概念章节仍可参考）。
