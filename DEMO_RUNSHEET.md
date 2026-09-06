# EverLink — Demo Recording Run Sheet (bilingual, ≤ 5:00, three-act)

录制执行单：秒级字幕 cue（英）+ 中文对照 + 画面动作。配对文件：[DEMO_SCRIPT.md](DEMO_SCRIPT.md)（完整旁白稿）。
**录屏 = owner 动作**。工具：Xbox Game Bar（Win+G）或 OBS，1080p，导出 mp4 → YouTube **Unlisted** → 链接填 Devpost video 字段。

**三幕结构（2026-09-05 第四遍重组）**：介绍 0:00–1:07（定位 / 规模 / 真站 / 三问 / 原理 / 资源六拍字卡与实拍）→ 怎么用 1:07–1:27（`/how-it-works` 两停）→ 演示 1:27–5:00（终端三命令 + board 页面 + 收尾字卡）。
重组理由：评委前 30 秒必须拿到"这是什么 / 为谁 / 原理 / 去哪看"，冷开场直接进终端会让后面所有画面失去锚点。总长 ≤ 5:00 是 spec §9 硬要求，介绍幕因此压缩到 67s。

## 录前检查（5 分钟，2026-09-05 四遍复演定稿）

1. **代理必须先活**：v2rayN（`D:\d36j0t1v\v2rayN\v2rayN.exe`）必须已启动且连上节点；验证 `python d:\qcoder\_proxy_check.py` 输出 `LISTENING`。**刚启动后节点需热身**——第一次导航 vercel.app 可能超时，重试即通。
2. **board 用生产地址** `https://everlink-seven.vercel.app`（禁 localhost）。**收件箱在 `/inbox`**（`/` 已是品牌落地页，不含卡片），录前导航一次 `/inbox` 确认 `Inbox · EverLink Board` 标题与 16 张 pending 卡出现。
   **录前预热**：`python d:\qcoder\_demo_warm.py`（2 轮 × 16 条 board/外站 URL）→ round 2 全 200 即通过；round 1 偶发 `ConnectError` 是代理隧道冷抖动（09-05 实测第二轮全绿），以 round 2 为准。Vercel 冷启动首航会报 10s 超时（其实内容已渲染），预热后录制时才秒开。
   **开放部署（09-06 起）**：生产 board 已移除 `NEXT_PUBLIC_BOARD_READONLY`——`/inbox` 的勾选框与批量条、卡片页的 approve/reject 按钮全部真实可用，API 写操作放行。理由：完整开放让评委看到全貌闭环（approve → nightly worker 执行 → 写入 EverLink 自有镜像库 + 快照 + 复验 + 失败回滚），不再碎片化展示；源站生产库仍严格只读，任何批准都不会改到源站内容。（历史注：09-05 曾短暂设只读 403，该状态已废弃；当时的 DOM 实测记录不再适用。）
3. **Judge 模式定档（2026-09-05 本地实测通过）**：默认 `--judge mantle` 录 Shot 8，字幕用 **[REAL]**（真实 LLM 调用，qwen via Bedrock Mantle 网关）。本地 `--limit 6` 实测 **39s / rc=0**，结构可复现（同 slot、同 `REWRITE_SENTENCE`、5 healthy + 1 offer_changed、steering 0 blocked、2 tool calls、1 决策卡），措辞每次不同属正常。
   **本地 mint 前置条件**：走 `~/.aws/credentials` 的 `[default]`；`.env` 里**绝不能有空值的 `AWS_ACCESS_KEY_ID=` / `AWS_SECRET_ACCESS_KEY=` / `AWS_PROFILE=` 行**——空串会遮蔽共享凭据文件，mint 直接报 `Failed to mint Bedrock Mantle bearer token`（09-05 已把这三行注释掉；`.env` 若重建须复查）。备选路径：`BEDROCK_MANTLE_API_KEY`（console 铸的 key，直作 OpenAI api_key）。直连 Claude 工单若批了可选 `--judge bedrock`；当晚都不可用才退回 `--judge stub` + 文末 **ALT cue**（诚实优先，不许嘴替）。
4. **数字复核（以屏幕实况为准，2026-09-05 复探）**：23,476（`data/slots_summary.json` 未变）；board 实况 **pending 16 / applied 37 / rejected 69 / healed 37**——69 条 rejected = 4 人工typed驳回 + 54 条 nightly recheck 误报退役 + 11 条 09-05 系统去重驳回，全部带理由落库；audit 全量 **steering_cancel 3 / write 38 / verify 38 / rollback 1 / dead_letter 1**（事件名是 write/verify，不存在 apply）；evals cards 41（fixture 语境）。`[REAL]`/`[SEEDED REPLAY]`/`[EST.]` 角标照 DEMO_SCRIPT 三标签执行。
5. **遮敏**：DB host、带 token 的 URL、`.env`、scan 输出里的联盟 tag（`tag=aethelgem2026-20`）blur/裁掉；board 卡片 Evidence 里的联盟 tag 同样要遮——09-05 二遍演练实测：`dec-b21f3d82bc` 的 Evidence 只渲染**应用后的新 URL**（`https://www.amazon.com/dp/…?tag=aethelgem-20`，Healthy HTTP 200），并不并列旧 URL，该 `tag=aethelgem-20` 需遮。
6. 字幕烧录或后期贴：每条 cue ≤ 2 行；角标标签与字幕同时出现。
7. **录屏范围**：全屏，须同时罩住 **IDE 终端面板**（终端镜头）与 **IDE 内置 Browser view 面板**（board/外站/字卡镜头）；IDE 最大化，无关窗口移出。Browser view 若关闭，我 navigate 即唤醒（演练已验证）。
8. **push 与录制的先后**：每次 `git push` 都会触发 Railway 部署并**跑一次完整 nightly**——09-05 09:17→09:32 UTC 实测 audit 事件持续上涨（`tool_result` 1662→1716、`notify` 100→102），跑完才停（本次未产生新卡，计数仍是 16/37/69，但这是运气不是保证）。所以顺序必须是 **改完 → push → 等 nightly 跑完（探针两次读数不再变）→ 复探计数 → 录**；录前 6 步跑完之后不要再 push。audit 总量因此是**动值**（09-05 实测 **2,051** 行），文案统一写 "~2,000 rows" 不写死。
9. **字卡文件改过之后**：Browser view 里同 URL 的 hash 导航**不会重新加载文档**——必须 `type=reload` + `ignoreCache` 一次，再 hash 跳转才生效（09-05 实测：旧文档里跳新锚点不滚动；reload 后 Chrome 恢复旧滚动位置，需再 hash 跳一次）。录前 6 步跑完后字卡不再改，录制中 hash 导航可靠。

---

# 第一幕 · 介绍（0:00–1:07）

## Shot 1 · 0:00–0:10 · 根本定位字卡

画面：字卡 `#positioning`（file:///d:/qcoder/_demo_cards.html#positioning）——`The autonomous link-rot steward.` + 开源/自托管/人批决策一句。09-05 四遍演练截图验证渲染。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:00–0:05 | EverLink is an open-source, self-hosted link-rot steward. | EverLink 是一个开源、自托管的链接腐烂管家。 |
| 0:05–0:10 | Checkers only report — EverLink decides, and you approve. | 检查器只报告——EverLink 做决定，你来批准。 |

## Shot 2 · 0:10–0:20 · 规模字卡

画面：字卡 `#stats`——23,476 outbound link slots / across 3 production sites；last full manual check: never。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:10–0:15 | These are my three content sites: 23,476 outbound link slots between them. | 这是我的三个内容站：合计 23,476 个外链槽位。 |
| 0:15–0:20 | The last time every one was checked by hand? Never. | 上一次逐条人工检查？从来没有。 |

## Shot 3 · 0:20–0:30 · 真站实拍

画面：**www.aethelgem.com**（实测 1.5–3s 载完）→ **hotdeals.today**（09-05 预热后 **2.9s** 载完；09-04 的 ~12s 是节点热身，导航工具报超时但页面其实已渲染）。各停 5s。第三站 **flashdeals.today**（内部代号 sandcart，即 FlashDeals dropshipping 独立站；首页实测 HTTP 200 可达）为保持节奏不做实时导航，"三站"叙事由 board 的站点徽章与 scan 报告补足。**注意：不存在 sandcart.com 这个域名**（旧稿误写，已废弃）。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:20–0:25 | They rot a little every day — and nobody sees it until a reader does. | 它们每天烂一点——直到读者先发现。 |
| 0:25–0:30 | So tonight, an agent patrols them. | 于是今晚，一个 agent 替我值夜。 |

## Shot 4 · 0:30–0:42 · 三问字卡（4s/卡）

画面：字卡 `#cards` 三张标题卡 PROBLEM · WHO · WHY AN AGENT。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:30–0:34 | The problem: links rot; checkers only report. | 问题：链接会腐烂；检查器只报告。 |
| 0:34–0:38 | Who it's for: independent publishers and small content teams. | 为谁：独立出版者与小型内容团队。 |
| 0:38–0:42 | Why an agent: decide-and-escalate is repetitive, judgment-heavy work. | 为何用 agent："决定并上报"是重复且吃判断力的活。 |

## Shot 5 · 0:42–0:57 · 原理字卡（5s/卡，三卡同屏）

画面：字卡 `#principle`——1 · PATROL / 2 · DECIDE / 3 · ACT & PROVE 三卡同屏（09-05 截图验证 100vh 内放得下），末行诚实三标签 `[REAL] · [SEEDED REPLAY] · [EST.]`。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:42–0:47 | Patrol: every outbound link, every night. | 巡检：每条外链，每晚。 |
| 0:47–0:52 | Decide: a real LLM Judge on Bedrock drafts the fix; four Steering policies constrain it. | 决策：Bedrock 上的真实 LLM Judge 起草修法；四条 Steering 策略约束它。 |
| 0:52–0:57 | Act & prove: apply, re-verify, roll back on failure — every step in a public audit trail. | 执行并自证：应用、复验、失败回滚——每一步都进公开审计轨迹。 |

## Shot 6 · 0:57–1:07 · 资源字卡

画面：字卡 `#resources`——SOURCE `github.com/tomyuya/everlink`（MIT · self-host runbook）+ LIVE EXAMPLE `everlink-seven.vercel.app`（read-only deployment）大字。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:57–1:02 | Open source under MIT: github.com/tomyuya/everlink. | MIT 开源：github.com/tomyuya/everlink。 |
| 1:02–1:07 | And a live read-only example: everlink-seven.vercel.app. | 以及一个只读的线上实例：everlink-seven.vercel.app。 |

# 第二幕 · 怎么用（1:07–1:27）

## Shot 7 · 1:07–1:27 · `/how-it-works` 两停

画面：Browser view 打开 **`/how-it-works`**（公开介绍页）。**停 1（1:07–1:15）顶部**：h1 "How EverLink works" + 定位段（open-source, self-hosted, not a SaaS 三徽章）+ 双库模型两卡（你的库严格只读 / EverLink 只写自己的库）。**停 2（1:15–1:27）End 键滚到底**（docH 实测 2027px ≈ 2.1 屏，一次到底）：部署契约 5 项（你的库/你的 origin/EverLink 的库/一个 LLM/一个调度器）+ **Pipeline 流程图**（Scanner → Judge → Writer）+ 自动化面板 + 诚实示例声明（三站是 maintainer 自己的 dogfooding）。品牌面板的 mark 链回 GitHub 仓库。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 1:07–1:14 | How you use it: clone it, point it at your databases, deploy it on your own infra. | 怎么用：clone 它，指向你的数据库，部署在你自己的基础设施上。 |
| 1:14–1:20 | Your site's database stays strictly read-only; EverLink writes only to its own. | 你站的库严格只读；EverLink 只写它自己的库。 |
| 1:20–1:27 | The pipeline: Scanner, Judge, Writer — with a nightly cron and a human at the end. | 流水线：Scanner、Judge、Writer——每晚 cron 启动，末端是一个人。 |

# 第三幕 · 演示（1:27–5:00）

## Shot 8 · 1:27–2:23 · 夜间运行 [REAL/SEEDED]

画面：**1:27 敲回车** `python -m everlink scan --site aethelgem --judge mantle --dry-run --limit 6`（09-05 两次实测 **39s / 55.9s**：`[1/2] discovering + detecting...` 立刻出现，report 定格在 **2:06–2:23**——6 扫 / healthy 与 offer_changed 的配比在 **5+1 与 4+2** 之间浮动 / 真实 qwen 的 `REWRITE_SENTENCE` 提案与理由滚动 / steering 0 blocked / 决策卡 **1–2 张**，均属 [REAL] 正常波动）→ **2:12 切换判定点**：① report 已定格 → 立刻 `python -m everlink notify --brief --dry-run`（实测 **2s / 7.5s**，**16 pending** 晨报，末行 `Open the inbox : https://everlink-seven.vercel.app/inbox`，09-05 已修为深链不再指根路径），晨报停 3–5s 再切 board；② 2:12 仍在滚 → **直接切 Browser view：生产 board `/inbox`**（16 张 pending 卡，该屏延长到 31s 慢滚），live notify 那一拍改用 **ALT-3**（终端里仍在滚动的真实调用本身就是 [REAL] 证据）。两句诚实行（`--dry-run: nothing written to any database` / `nothing sent`）在画面内**保留**。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 1:27–1:34 | Every night, a cron kicks off the loop: Scanner, Judge, Writer — three agents under one orchestrator. | 每晚 cron 启动循环：Scanner、Judge、Writer 三个 agent 归一个编排器管。 |
| 1:34–1:42 | The Scanner probes every slot: HTTP status and redirect chains first, a stealthy page parse only when inconclusive. | Scanner 先探 HTTP 状态与重定向链，拿不准才做深层页面解析。 |
| 1:42–1:50 | The Judge — a real LLM on Amazon Bedrock — decides the fix and emits a structured Proposal. **[REAL]** | Judge（Amazon Bedrock 上的真实 LLM）决定修法并输出结构化 Proposal。**[真实调用]**（mantle/bedrock 均为真实；仅退回 stub 时换 ALT-1） |
| 1:50–1:56 | Blocked or timed out? Flagged needs_human_recheck — it never fabricates a result. | 被墙或超时？标记 needs_human_recheck——绝不编造结果。 |
| 1:56–2:08 | By morning: 16 problem slots in my inbox, as a morning brief. **[REAL + SEEDED REPLAY]** | 早上：16 个问题槽位以晨报形式到达（nightly 真实提案 + 种子回放卡，各自带标签）。**[真实+种子回放]**（未定格分支换 ALT-3） |

## Shot 9 · 2:23–2:43 · 决策收件箱 [SEEDED]

画面（全 URL 导航，零点击）：`/inbox`（pending **16** 张 + 只读提示行）。未定格分支此屏 2:12 起（31s 慢滚）。**线上只读，不现场点击 approve/reject——展示已落库结果。**

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 2:23–2:30 | The only screen I open: a minimal approval inbox. | 我唯一打开的界面：一个极简审批收件箱。 |
| 2:30–2:43 | 16 problem slots wait here — each with its evidence and its proposed fix. | 16 个问题槽位等在这里——每张都带证据与提案。 |

## Shot 10 · 2:43–3:05 · 三态与驳回卡 [SEEDED]

画面（全 URL 导航）：`/inbox?status=applied`（**37** 张已批准）→ `/inbox?status=rejected`（**69** 张 = 4 人工 typed 驳回 + 54 recheck 误报退役 + 11 系统去重，全部带理由落库）→ 打开 **`/decision/dec-7158d74e33`**（Rewrite sentence 被驳回：价格 $199→$349、"under $200" 表述过期，驳回理由已落库）→ 返回 rejected 列表停。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 2:43–2:51 | Low-risk fixes are batched — 37 applied and verified so far. **[SEEDED REPLAY]** | 低风险修复批量处理——已应用并验证 37 条。**[种子回放]** |
| 2:51–2:59 | The risky ones I read individually — rejections like this carry a typed reason. | 高风险的我逐条读——像这条驳回带着写明的理由。 |
| 2:59–3:05 | The agent remembers that reason and won't re-propose the same fix next week. | agent 记住理由，下周不会重提同样的修复。 |

## Shot 11 · 3:05–3:27 · 安全幕 1：披露守护

画面：Browser view **`/audit?event=steering_cancel`**（过滤条显示 3 行，disclosure_policy 的 cancel_message 可见；不带过滤时埋在近 2,000 行里不可达——09-05 实测 audit 总量 **2,051** 行，每晚还涨几十行，字幕/文案统一说 "~2,000 rows" 不写死）→ 打开 **`/decision/dec-2b91672858`**（Rejected · 人工 typed 理由："Acknowledged — the disclosure block is structurally protected, so NO write is allowed"）。旧 escalate 卡 dec-d75e0275a8 已被 recheck 退役（404），弃用。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 3:05–3:12 | This block is a dead link — but it also carries my affiliate disclosure. | 这个块是死链——但它同时承载我的联盟披露声明。 |
| 3:12–3:19 | A DisclosurePolicy steering hook marks the slot protected and cancels the drop before it happens. | DisclosurePolicy 引导钩子把槽位标为受保护，在删除发生前取消工具调用。 |
| 3:19–3:27 | The audit log records steering_cancel; a human confirmed on the record: no write may touch it. | 审计日志记下 steering_cancel；人工录在案确认：任何写动作碰不了它。 |

## Shot 12 · 3:27–3:57 · 安全幕 2 + 闭环 [REAL/SEEDED]

画面（全 URL 导航，5s/页）：(a) 打开 **`/decision/dec-b21f3d82bc`**（Applied · High risk · Replace URL：Aurora Lab-Grown Diamond Solitaire 死链→活 offer；Evidence 区块渲染**应用后的新 URL** + `Healthy HTTP 200`，联盟 tag 需遮）；(b) **`/audit?event=write`**（38 行，每条 applied 修复一行、单事务）与 **`/audit?event=verify`**（38 行复探）；(c) `/report`：**Links healed 37 / Slots fixed 37**；(d) **`/audit?event=rollback`**（1 行）+ **`/audit?event=dead_letter`**（1 行，强制失败死信对）。**展示已落库闭环，不现场触发。**

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 3:27–3:34 | On approve, the Writer snapshots the block first, then applies the fix in a single transaction. | 批准后 Writer 先快照整个块，再在单事务里应用修复。 |
| 3:34–3:41 | Then a verify pass re-probes the new link — to confirm it's genuinely alive. **[REAL]** | 然后 verify 复探新链接——确认它真的活了。**[真实]** |
| 3:41–3:48 | Last night: 37 dead links verified back to zero. **[SEEDED REPLAY]** | 昨晚：37 条死链验回零。**[种子回放]** |
| 3:48–3:57 | If verification ever fails, it rolls back and dead-letters the decision. It closes the loop; it doesn't just claim success. | 一旦验证失败，回滚并把决策送入死信。它闭环，不只是宣称成功。 |

## Shot 13 · 3:57–4:22 · 评测：50 例三硬指标 [REAL]

画面：**3:57 敲回车** `python scripts/run_evals.py --full --trace console`（三次实测 **19s / 20.5s / 22s**：先滚 OTel JSON span 流，**4:16–4:19 定格** summary 块——50/50=100% / steering 0 / 三硬指标 100% / cards 41 / **OVERALL: PASS** + stub 诚实 note）。**note 末句 09-05 已改口径**：屏幕上是 `Score the real Judge with --judge mantle (the deployed Bedrock path; --judge bedrock is the direct-Claude route)`——与本片 `--judge mantle` 的真跑一致，不再是过期的 `--judge bedrock`。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 3:57–4:04 | I don't ask you to trust the agent — I test it. | 我不求你信 agent——我测试它。 |
| 4:04–4:12 | A 50-case eval suite runs fully offline against a fixture server with known ground truth. | 50 例评测套件全离线跑在有已知真值的 fixture 服务器上。 |
| 4:12–4:22 | Detection 100%, steering violations zero, three hard metrics at 100% — and the oracle is proven non-vacuous. | 检测 100%、引导违规零、三项硬指标 100%——且 oracle 被证明非空转。 |

## Shot 14 · 4:22–4:42 · 通用适配器 [REAL]

画面：**4:22 敲回车** `python -m everlink scan --site https://blog.python.org --include-internal --dry-run --limit 8`（09-05 两次实测 **10s / 58.3s**——外网波动大，8/8 healthy + dry-run 诚实行）。**4:38 判定点**：① 已定格 → 终端停 3–5s 再切结束字卡；② 仍在滚 → **4:42 直接切结束字卡**（终端里还在跑的真实抓取就是证据，字幕 4:30–4:38 "从没见过的站" 配滚动画面同样成立），generic 的 8/8 不进画面。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 4:22–4:30 | This isn't hard-coded to my sites: a generic adapter scans any blog, read-only. | 这不是为我站硬编码：generic 适配器只读扫描任意博客。 |
| 4:30–4:38 | Here it is on a site EverLink has never seen. | 这是一个 EverLink 从没见过的站。 |
| 4:38–4:42 | Read-only, everywhere. | 在任何地方都只读。 |

## Shot 15 · 4:42–5:00 · 收尾

画面：字卡 `#end`——`You approve decisions, not links.`

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 4:42–4:49 | EverLink patrols 23,476 links so I don't have to. | EverLink 巡 23,476 条链接，我不用。 |
| 4:49–4:55 | Honest about its limits, immune to disclosures, verifies its own fixes, rolls back when wrong. | 对能力诚实、披露免疫、自验修复、错了回滚。 |
| 4:55–5:00 | You approve decisions, not links. | 你批的是决策，不是链接。 |

---

## 命令小抄（终端镜头，在 IDE 终端面板跑；节奏用 sleep 控制）

```
Shot 8:  python -m everlink scan --site aethelgem --judge mantle --dry-run --limit 6   (1:27 敲回车；实测 39–56s，真实 qwen；2:12 判定点 A)
         python -m everlink notify --brief --dry-run                                  (已定格分支 2:12 敲；实测 2–8s，16 pending，末行 inbox 深链)
Shot 13: python scripts/run_evals.py --full --trace console                           (3:57 敲回车；实测 19–22s)
Shot 14: python -m everlink scan --site https://blog.python.org --include-internal --dry-run --limit 8   (4:22 敲回车；实测 10–58s；4:38 判定点 B)
```

工作目录：`d:\qcoder\everlink`。**四条命令都要当场敲回车**（不许提前跑完再回放）；时长波动全部落在判定点规则里，不需要临场改命令、改参数或改顺序。

## Board URL 清单（生产，2026-09-05 四遍复演逐条 Browser DOM 验证渲染 OK）

```
S7  介绍页   https://everlink-seven.vercel.app/how-it-works   (顶部停 8s → End 到底 12s；品牌面板 mark 链 GitHub + 正文 GitHub ×2 + mailto)
S9  收件箱   https://everlink-seven.vercel.app/inbox               (16 张 pending)
S10 applied  https://everlink-seven.vercel.app/inbox?status=applied   (37 张)
S10 rejected https://everlink-seven.vercel.app/inbox?status=rejected  (69 张)
S10 驳回卡   https://everlink-seven.vercel.app/decision/dec-7158d74e33
S11 audit过滤 https://everlink-seven.vercel.app/audit?event=steering_cancel   (3 行+过滤条)
S11 披露卡   https://everlink-seven.vercel.app/decision/dec-2b91672858        (Rejected·typed 理由确认不写)
S12 applied卡 https://everlink-seven.vercel.app/decision/dec-b21f3d82bc
S12 write/verify https://everlink-seven.vercel.app/audit?event=write · ?event=verify   (38/38 行)
S12 rollback对 https://everlink-seven.vercel.app/audit?event=rollback · ?event=dead_letter  (1/1 行)
S12 report   https://everlink-seven.vercel.app/report         (Links healed 37)
字卡        file:///d:/qcoder/_demo_cards.html#positioning · #stats · #cards · #principle · #resources · #end
外站        https://www.aethelgem.com (1.5-3s) · https://hotdeals.today (预热后 2.9s；冷启动 nav 可能报超时但页面会渲染)
第三站      flashdeals.today（内部代号 sandcart = FlashDeals 独立站，HTTP 200 可达，演示不做实时导航）· 无 sandcart.com 域名
落地页      https://everlink-seven.vercel.app/  本遍不导航（品牌 slogan 已上 #positioning 字卡；预热脚本仍覆盖）
```

## 演练记录（2026-09-04 / 09-05 前三遍，关键实测值）

| 项 | 结果 |
|---|---|
| v2rayN 拉起 | `python d:\qcoder\_start_proxy.py`（自动启动+等端口，实测 PROXY UP） |
| 生产 board 连通 | 强制代理探测 200/2.3s；Browser view 导航+渲染 OK（visible 905×961，35 卡） |
| board 19 拍 | `/` 落地页 hero、`/inbox`(16)、`?status=applied`(37)、`?status=rejected`(69 + 目标驳回卡)、`dec-7158d74e33`（$349 / under $200 + 页脚 GH/mailto）、`/audit?event=steering_cancel`（过滤条 + 3 行）、`dec-2b91672858`、`dec-b21f3d82bc`、`?event=write`(38)、`?event=verify`(38)、`?event=rollback`(1)、`?event=dead_letter`(1)、`/report`(37/37)、`/how-it-works`（mark 链 + GitHub ×2 + mailto）——全部通过 |
| scan `--judge mantle` | 两遍实测 **39s / 55.9s**：6 扫 → 5+1 或 4+2 配比、真实 qwen `REWRITE_SENTENCE`（risk=high）提案与理由、steering 0 blocked、1–2 卡、dry-run 零写入。连跑结构一致，仅措辞不同（[REAL] 预期行为） |
| notify `--brief` | 实测 **2s / 7.5s**；18 slots / 16 cards / 晨报含 inbox 深链 / "nothing sent" |
| evals `--full --trace` | 三次实测 **19s / 20.5s / 22s**；OVERALL PASS（50/50、0、三项 100%、cards 41） |
| generic blog.python.org | 两次实测 **10s / 58.3s**；8/8 healthy + dry-run 行 |
| 开放部署 DOM（09-06 起） | `/inbox` 勾选框/批量条、卡片页 approve/reject 按钮真实可用；API 写操作放行；写入仅落 EverLink 镜像库 |
| 已修的产品问题 | ① notify 把 board 根 URL 当收件箱链接 → `_deep_link()` 深链 `/inbox`（子路径部署不追加，1 条断言守住）；② evals 屏幕 note 过期（`--judge bedrock`）→ 改 mantle 并补 `_make_judge()`/argparse 的 mantle 分支（此前该 flag 不存在）；③ 测试数 311 → 312，DEVPOST/README/SUBMISSION_CHECKLIST 已同步 |
| 已知坑 | Qoder 崩溃会带走 Browser view（navigate 唤醒）与代理（_start_proxy.py 拉起）；节点刚起时 vercel.app 首航超时须重试；hotdeals 导航工具超时但页面会渲染；audit 事件名是 write/verify/rollback/dead_letter（**不存在 apply**）；列表页为客户端渲染，httpx 探针只见空壳，画面内容以 Browser DOM 核验；cmd 单个 `&` 是异步执行；管道/重定向捕获 Python 输出按 cp936 会把 em dash/箭头变 `??`（**仅捕获假象**，IDE 终端 Unicode 直写画面正常，不要为此改命令） |

## 演练记录（2026-09-05 第四遍：三幕重组）

| 项 | 结果 |
|---|---|
| 重组动机 | 评委前 30 秒缺上下文锚点；新增介绍幕（定位/原理/资源字卡）与"怎么用"幕（`/how-it-works` 前置） |
| 新字卡三张 | `#positioning` / `#principle` / `#resources` 加入 `_demo_cards.html`，Browser 截图逐张验证渲染（定位句、三卡同屏、两 URL 大字均清晰） |
| 字卡 reload 坑 | 改过字卡文件后同 URL hash 导航不重载文档（旧文档跳新锚点不滚动）；`type=reload`+`ignoreCache` 后 Chrome 恢复旧滚动位置，需再 hash 跳一次才到位。已写入录前检查第 9 条与 cue sheet 已知坑 |
| `/how-it-works` 两停 | docH 实测 2027px（vh 961）：顶部停 = 定位段+三徽章+双库模型；End 一次到底 = 部署契约+Pipeline 流程图+自动化面板+诚实示例声明。两停 20s 足够 |
| 预热脚本化 | 新增 `d:\qcoder\_demo_warm.py`（2 轮 × 16 条）替代手工逐个导航；round 1 偶发 ConnectError 为代理隧道冷抖动，round 2 全绿即通过 |
| 时间线 | 判定点 A 1:20→**2:12**、判定点 B 4:26→**4:38**；scan 1:27 敲、evals 3:57 敲、generic 4:22 敲；落地页 `/` 不再导航 |

## 录制口径

所有 `--dry-run`：零写库、零发送；屏幕上的诚实行（"nothing written to any database" / "nothing sent"）是加分画面，**不要剪掉**。

## ALT cues（仅当晚退回 stub 时用；mantle/bedrock 真实模式用正文 [REAL] 字幕，无需 ALT）

- **ALT-1**（换 Shot 8 的 1:42–1:50）：The Judge seam runs on its injected stub tonight — same structured Proposal, same harness that scores the live Bedrock path. ／ 今晚 Judge 缝跑在注入 stub 上——同样的结构化 Proposal、同一套给 Bedrock 真路径打分的评测。
- **ALT-2**（仅当 mantle 与 bedrock 当晚都跑不起来、全程未真跑 Bedrock 时才换 Shot 15 的 "Built with the Strands Agents SDK and Amazon Bedrock" 句）：Built with the Strands Agents SDK for Agents for Humans. ／ 用 Strands Agents SDK 为 Agents for Humans 而建。（注：mantle 模式即真跑 Bedrock Mantle 网关，此时收尾可如实宣称 "Strands SDK + Amazon Bedrock"，无需用 ALT-2。）
- **ALT-3**（仅当 Shot 8 的 scan 到 2:12 仍未定格、live notify 那一拍被切掉时换 1:56–2:08 句）：By morning: 16 problem slots are waiting in my inbox. **[REAL + SEEDED REPLAY]** ／ 早上：16 个问题槽位在我的收件箱里等着。**[真实+种子回放]**（去掉 "as a morning brief"——晨报没进画面就不宣称它进画面；16 这个数字由 `/inbox` 的 16 张 pending 卡实证。）

## 录后清单

1. 总时长 ≤ 5:00（秒表核对）。
2. YouTube 上传 → **Unlisted** → 复制带链接 URL → Devpost Project details video 字段。
3. 录屏文件本地留档（deadline 后冻结不改）。
