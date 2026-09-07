# EverLink — Demo Recording Run Sheet (bilingual · ≤ 5:00 · two-demo focus)

录制执行单：逐句字幕 cue（英，时间码取自 `docs/video/vo_full.vtt` **实测**）+ 中文对照 + 画面动作。
配对文件：[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md)（导演旁白稿）· 读稿 `docs/video/vo_full.txt` · 配音 `docs/video/vo_full.mp3`（实测 **4:57.1**）· 逐句时间码 `docs/video/vo_full.vtt` · 分镜停留/切点 [`DEMO_STORYBOARD.md`](DEMO_STORYBOARD.md)。
**录屏 = owner 动作**。工具：Xbox Game Bar（Win+G）或 OBS，1080p，导出 mp4 → YouTube **Unlisted** → 链接填 Devpost video 字段。

**三幕两-demo 结构（2026-09-07 重剪；下表时间码为配音实测，已取代 09-05 旧稿的计划时间）**：

| 幕 | 时间 | 内容 |
|---|---|---|
| Act 1 介绍 | 0:00–1:04 | 定位 / 规模 / 真站 / 为谁·为何·**track** / 原理 / 资源 |
| Act 2 怎么用 + 两路径 | 1:04–1:28 | `/` 一屏两停：定位+三徽章+双库模型 → End 到底 pipeline + 自动化面板 + 两接入路径 |
| **Demo 1 · Path B 全链** | 1:28–3:29 | 终端 scan（operate+process）→ 晨报 → 收件箱人批 → 两护栏+闭环 → evals |
| **Demo 2 · Path A 通用只读** | 3:29–4:38 | operate（敲 generic scan）→ process（爬取流水）→ show（报告 + A vs B） |
| Close 收尾 | 4:38–4:57 | `#end` 字卡 + 量化 impact（~six hours/week） |

总长 ≤ 5:00 是 spec §9 硬要求；实测配音 **4:57.1**，尾部留 ~3s 黑场。剪辑以本表时间码把画面切到配音上。

> 两个 demo 各走 **operate → process → show** 三段——这是本遍重点，评委的 Technological
> Implementation / Design / Impact 主要在这 ~3 分钟里给分。诚实三标签 `[REAL]` /
> `[SEEDED REPLAY]` / `[EST.]` 全程与字幕同屏。

## 录前检查（5 分钟）

1. **代理必须先活**：v2rayN（`D:\d36j0t1v\v2rayN\v2rayN.exe`）已启动且连上节点；验证 `python d:\qcoder\_proxy_check.py` 输出 `LISTENING`。**刚启动后节点需热身**——首次导航 vercel.app 可能超时，重试即通。
2. **board 用生产地址** `https://everlink-seven.vercel.app`（禁 localhost）。**收件箱在 `/inbox`**（`/` 是品牌落地页兼介绍页，不含卡片），录前导航一次 `/inbox` 确认标题 `Inbox · EverLink Board` 与 16 张 pending 卡出现。
   **录前预热**：`python d:\qcoder\_demo_warm.py`（2 轮 × 16 条 board/外站 URL）→ round 2 全 200 即通过；round 1 偶发 `ConnectError` 是代理隧道冷抖动，以 round 2 为准。Vercel 冷启动首航会报 10s 超时（内容其实已渲染），预热后录制时才秒开。
   **开放部署（09-06 起，本会话 Browser 实测复核仍为真）**：生产 board **可交互**——`/inbox` 勾选框与批量条、卡片页 approve/reject 按钮全部真实可用，API 写操作放行；写入**仅落 EverLink 自有镜像库**（快照 + 复验 + 失败回滚），源站生产库始终严格只读。README/DEVPOST 的 "fully interactive" 宣称与此一致。录制默认**展示已落库结果**（applied/rejected），如需现场演示一次批量 approve 也安全。
3. **Judge 模式定档**：默认 `--judge mantle` 录 Shot 8，字幕用 **[REAL]**（真实 LLM 调用，qwen via Bedrock Mantle 网关）。本地 `--limit 6` 实测 **39s / 56s**，结构可复现（同 slot、同 `REWRITE_SENTENCE`、5 healthy + 1 offer_changed、steering 0 blocked、1–2 决策卡），措辞每次不同属正常。
   **本地 mint 前置**：走 `~/.aws/credentials` 的 `[default]`；`.env` 里**绝不能有空值的 `AWS_ACCESS_KEY_ID=` / `AWS_SECRET_ACCESS_KEY=` / `AWS_PROFILE=` 行**（空串会遮蔽共享凭据文件，mint 直接报 `Failed to mint Bedrock Mantle bearer token`）。备选：`BEDROCK_MANTLE_API_KEY`。直连 Claude 工单若批了可选 `--judge bedrock`；当晚都不可用才退回 `--judge stub` + 文末 **ALT cue**（诚实优先，不许嘴替）。
4. **数字复核（以屏幕实况为准）**：23,476（`data/slots_summary.json`）；board 实况 **pending 16 / applied 37 / rejected 69 / healed 37**（69 = 4 人工 typed 驳回 + 54 nightly recheck 误报退役 + 11 系统去重，全部带理由落库）；audit 全量 **steering_cancel 3 / write 38 / verify 38 / rollback 1 / dead_letter 1**（事件名是 write/verify，**不存在 apply**）；evals cards 41。
5. **遮敏**：DB host、带 token 的 URL、`.env`、scan 输出与卡片 Evidence 里的联盟 tag（`tag=aethelgem2026-20` / `tag=aethelgem-20`）blur 或裁掉。`dec-b21f3d82bc` 的 Evidence 只渲染**应用后的新 URL**（Healthy HTTP 200），其 tag 需遮。
6. **字幕**：烧录或后期贴；每条 cue ≤ 2 行；`[REAL]`/`[SEEDED REPLAY]`/`[EST.]` 角标与字幕同屏。本表 EN 行可直接做字幕源，精确到帧的时间码见 `docs/video/vo_full.vtt`。
7. **录屏范围**：全屏，须同时罩住 **IDE 终端面板**（终端镜头）与 **IDE 内置 Browser view 面板**（board/外站/字卡镜头）；IDE 最大化，无关窗口移出。Browser view 若关闭，navigate 即唤醒。
8. **push 与录制先后**：每次 `git push` 触发 Railway 部署并**跑一次完整 nightly**（audit 事件持续上涨，跑完才停）。顺序必须是 **改完 → push → 等 nightly 跑完（探针两次读数不再变）→ 复探计数 → 录**；录前 5 步跑完后不要再 push。audit 总量是**动值**，文案统一写 "~2,000 rows" 不写死。
9. **字卡改过之后**：Browser view 里同 URL 的 hash 导航**不重载文档**——必须 `type=reload` + `ignoreCache` 一次，再 hash 跳转才生效。录前 5 步跑完后字卡不再改，录制中 hash 导航可靠。

---

# 第一幕 · 介绍（0:00–1:04）

## Shot 1 · 0:00–0:08 · 定位字卡
画面：字卡 `#positioning`（`file:///d:/qcoder/_demo_cards.html#positioning`）——`The autonomous link-rot steward.` + 开源/自托管/人批决策一句。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:00–0:04 | EverLink is an open-source, self-hosted link-rot steward. | EverLink 是一个开源、自托管的链接腐烂管家。 |
| 0:04–0:08 | Checkers only report — EverLink decides, and you approve. | 检查器只报告——EverLink 做决定，你来批准。 |

## Shot 2 · 0:08–0:16 · 规模字卡
画面：字卡 `#stats`——23,476 outbound link slots / across 3 production sites；last full manual check: never。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:08–0:13 | These are my three content sites: twenty-three thousand outbound link slots. | 这是我的三个内容站：两万三千个外链槽位。 |
| 0:13–0:16 | The last time every one was checked by hand? Never. | 上一次逐条人工检查？从来没有。 |

## Shot 3 · 0:16–0:22 · 真站实拍
画面：**www.aethelgem.com**（1.5–3s 载完）→ **hotdeals.today**（预热后 ~2.9s）。第三站 flashdeals.today（内部代号 sandcart）不做实时导航，"三站"叙事由 board 站点徽章与 scan 报告补足。**不存在 sandcart.com 域名**。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:16–0:20 | They rot a little every day, and nobody sees it until a reader does. | 它们每天烂一点，没人看得见——直到读者先发现。 |
| 0:20–0:22 | So an agent patrols them. | 于是一个 agent 替我巡它们。 |

## Shot 4 · 0:22–0:36 · 为谁 · 为何 · track 字卡
画面：字卡 WHO · WHY AN AGENT + 一枚 **"Professional Agents track"** 徽章。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:22–0:29 | Who it's for: independent publishers and small content teams — we're entering the Professional Agents track. | 为谁：独立出版者与小型内容团队——我们报的是 Professional Agents 赛道。 |
| 0:29–0:36 | Why an agent: decide-and-escalate is repetitive, judgment-heavy work — exactly what an agent should take on. | 为何用 agent："决定并上报"是重复且吃判断力的活——正是 agent 该接的。 |

## Shot 5 · 0:36–0:55 · 原理字卡（三卡同屏）
画面：字卡 `#principle`——PATROL / DECIDE / ACT & PROVE 三卡同屏，末行诚实三标签 `[REAL] · [SEEDED REPLAY] · [EST.]`。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:36–0:38 | The principle in three lines. | 原理三行说完。 |
| 0:38–0:41 | Patrol: every outbound link, every night. | 巡检：每条外链，每晚。 |
| 0:41–0:48 | Decide: a real LLM Judge on Amazon Bedrock drafts the fix, constrained by four Steering policies. | 决策：Amazon Bedrock 上的真实 LLM Judge 起草修法，受四条 Steering 策略约束。 |
| 0:48–0:55 | Act and prove: apply, re-verify, roll back on failure — every step in a public audit trail. | 执行并自证：应用、复验、失败回滚——每一步都进公开审计轨迹。 |

## Shot 6 · 0:55–1:04 · 资源字卡
画面：字卡 `#resources`——SOURCE `github.com/tomyuya/everlink`（MIT · self-host runbook）+ LIVE EXAMPLE `everlink-seven.vercel.app` 大字。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:55–1:00 | Open source under MIT: github dot tomyuya slash everlink. | MIT 开源：github.com/tomyuya/everlink。 |
| 1:00–1:04 | And a live example: everlink-seven dot vercel dot app. | 以及一个线上实例：everlink-seven.vercel.app。 |

---

# 第二幕 · 怎么用 + 两路径（1:04–1:28）

## Shot 7 · 1:04–1:28 · `/` 一屏两停
画面：Browser view 打开 **`/`**（唯一产品页，已吸收旧 `/how-it-works`，后者 308 重定向到此）。**停 1（1:04–1:16）顶部**：定位 + 三徽章（开源 MIT / 自托管非 SaaS / Strands SDK + Bedrock）+ 双库模型两卡。**停 2（1:16–1:28）End 键滚到底**：六阶段 pipeline 图 + 自动化面板（实时排程 + 台账最近一次运行原样引用）+ **两接入路径**（Path A / Path B）+ 写入安全边界与部署者契约。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 1:04–1:09 | How you use it: clone it, deploy it on your own infrastructure. Links get in two ways. | 怎么用：clone 它，部署在你自己的基础设施上。链接有两种接入方式。 |
| 1:09–1:17 | Path A: a generic read-only crawl of any website — no database, no credentials, never writes back. | Path A：对任意网站的通用只读爬取——无数据库、无凭证、绝不写回。 |
| 1:17–1:24 | Path B: a read-only snapshot of your own database, unlocking block-level fixes and gated write-back. | Path B：对你自己库的只读快照，解锁块级修复与门控写回。 |
| 1:24–1:28 | Your source database stays strictly read-only either way. | 无论哪条路，你的源库都严格只读。 |

---

# 第三幕 · Demo 1 — Path B 全链（1:28–3:29）

## Shot 8 · 1:28–2:15 · operate + process：夜间扫描 [REAL] · **Technological Implementation**
画面：**1:28 敲回车** `python -m everlink scan --site aethelgem --judge mantle --dry-run --limit 6`（实测 **39–56s**，真实 qwen 提案滚动，report 定格约 **2:06–2:15**；`--dry-run` 诚实行 `nothing written to any database` 全程在画面内）。**判定点 A ≈ 2:15**：report 已定格 → 进 Shot 9 敲 notify；仍在滚 → 滚动中的真实调用本身即 [REAL] 证据，直接进 Shot 9。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 1:28–1:36 | Demo one: Path B, the full loop on my own site — the nightly cron's loop, run by hand, dry-run, so nothing is written. | Demo 一：Path B，在我自己站上跑全链——就是夜间 cron 那套循环，我手动跑、dry-run，所以什么都不写。 |
| 1:36–1:42 | I type: everlink scan, site aethelgem, judge mantle, dry-run, limit six. | 我敲：everlink scan，site aethelgem，judge mantle，dry-run，limit six。 |
| 1:42–1:56 | A Scanner agent pulls each link slot from my database snapshot and probes it — L1 HTTP status and redirect-chain analysis first, then an L2 stealthy page parse only where L1 is inconclusive. | Scanner agent 从我库快照里取出每个链接槽位去探测——先 L1 HTTP 状态与重定向链，L1 拿不准才做 L2 隐蔽页面解析。 |
| 1:56–2:08 | A Judge agent — a real LLM on Amazon Bedrock — reads that evidence and drafts a structured Proposal: replace this URL, rewrite that anchor, or escalate. **[REAL]** | Judge agent——Amazon Bedrock 上的真实 LLM——读这些证据，起草结构化 Proposal：换 URL、改写锚文本，或上报。**[真实调用]** |
| 2:08–2:15 | Anything blocked or timed out is flagged needs-human-recheck: the agent knows its limits and never fabricates. | 凡被墙或超时的都标 needs-human-recheck：agent 知道自己的边界，绝不编造。 |

## Shot 9 · 2:15–2:26 · show：报告 + 晨报 [REAL]
画面：report 定格（证据链 + 提案）；随后（若已定格）敲 `python -m everlink notify --brief --dry-run`（**2–8s**，**16 pending** 晨报，末行深链 `…/inbox`，`nothing sent` 诚实行在画面）。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 2:15–2:20 | The scan report lands: real proposals scrolling, each with its evidence chain. | 扫描报告落地：真实提案滚动，每条都带证据链。 |
| 2:20–2:26 | Then the morning brief: sixteen problem slots, pushed to me as a notification, not an app. | 然后是晨报：十六个问题槽位，作为通知推给我，不是一个 app。 |

## Shot 10 · 2:26–2:45 · show：决策收件箱 [SEEDED REPLAY] · **Design**
画面：Browser view `/inbox`——16 张 pending 卡、勾选框、批量 approve/reject 条（**开放部署，交互可用**；默认展示已落库结果，不强制现场点击）。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 2:26–2:29 | The only screen I open: the decision inbox. | 我唯一打开的界面：决策收件箱。 |
| 2:29–2:34 | Sixteen cards wait, each with its evidence and its proposed fix. | 十六张卡等在这里，每张都带证据与提案修法。 |
| 2:34–2:38 | I approve the safe ones in a batch; I read the risky ones individually. | 安全的我批量批准；有风险的我逐条读。 |
| 2:38–2:45 | Rejections carry a typed why — and the agent remembers it, so it won't re-propose the same fix next week. **[SEEDED REPLAY]** | 驳回带写明的理由——agent 会记住，下周不再重提同样的修法。**[种子回放]** |

## Shot 11 · 2:45–3:13 · show：两护栏 + 闭环 [REAL/SEEDED] · **Creativity / Design**
画面（全 URL 导航）：`/audit?event=steering_cancel`（3 行）+ `dec-2b91672858`（披露块受保护，人工 typed 确认不写）→ `dec-b21f3d82bc`（Applied · Replace URL，Evidence = 应用后新 URL + `Healthy HTTP 200`，tag 需遮）→ `/audit?event=write`（38）+ `?event=verify`（38）→ `/report`（healed 37）→ `?event=rollback`（1）+ `?event=dead_letter`（1）。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 2:45–2:47 | Two guards matter most. | 两道护栏最要紧。 |
| 2:47–2:56 | This disclosure block is dead — but deleting it is a legal disaster, so a Steering policy cancels the drop and the audit logs steering-cancel. | 这个披露块是死链——但删掉它是法律灾难，所以一条 Steering 策略取消删除，审计记下 steering-cancel。 |
| 2:56–3:04 | And when I approve a fix, the Writer snapshots the block, applies in one transaction, then re-probes the new link to prove it's alive. **[REAL]** | 我批准修复后，Writer 先给块快照，在单事务里应用，再复探新链接证明它活着。**[真实]** |
| 3:04–3:08 | If verification fails, it rolls back and dead-letters the decision. | 若验证失败，回滚并把决策送入死信。 |
| 3:08–3:13 | Last night: thirty-seven links healed, verified back to zero. **[SEEDED REPLAY]** | 昨晚：三十七条链接修复，验回零。**[种子回放]** |

## Shot 12 · 3:13–3:29 · show：我测它，不信它 [REAL] · **Technological Implementation**
画面：**约 3:13 敲回车** `python scripts/run_evals.py --full --trace console`（实测 **19–22s**：先滚 OTel span 流，summary 块 50/50=100% / steering 0 / 三硬指标 100% / cards 41 / **OVERALL: PASS**）。**对齐提示**：命令约 19–22s，而本 shot 仅 16s——可在 Shot 11 尾（~3:08）预敲回车，使 summary 落在 ~3:27 对上 "三硬指标 100%" 那句；若未定格，滚动中的 OTel span 流即 [REAL] 证据，summary 可作定格插入。屏幕 note 口径为 `--judge mantle`（与本片真跑一致）。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 3:13–3:16 | And I don't ask you to trust the agent — I test it. | 我不求你信 agent——我测试它。 |
| 3:16–3:26 | A fifty-case eval suite runs offline against known ground truth: detection one hundred percent, steering violations zero, three hard metrics at one hundred percent. **[REAL]** | 五十例评测套件离线跑在已知真值上：检测 100%、引导违规零、三项硬指标 100%。**[真实]** |
| 3:26–3:29 | And the oracle is proven non-vacuous. | 且 oracle 被证明非空转。 |

---

# 第三幕 · Demo 2 — Path A 通用只读爬取（3:29–4:38）

## Shot 13 · 3:29–3:45 · operate · **Design**
画面：**3:29 敲回车** `python -m everlink scan --site https://blog.python.org --include-internal --dry-run --limit 8`（实测 **10–58s**，外网波动大）。**判定点 B ≈ 4:13**：已定格 → 终端停 3–5s 进 Shot 15；仍在滚 → 滚动中的真实抓取即证据，Shot 15 配滚动画面同样成立。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 3:29–3:33 | Demo two: Path A, the generic read-only crawl. | Demo 二：Path A，通用只读爬取。 |
| 3:33–3:36 | No database, no code change, no credentials. | 无数据库、无代码改动、无凭证。 |
| 3:36–3:45 | I point it at a site EverLink has never seen: everlink scan, site blog dot python dot org, include-internal, dry-run, limit eight. | 我把它指向一个 EverLink 从没见过的站：everlink scan，site blog.python.org，include-internal，dry-run，limit eight。 |

## Shot 14 · 3:45–4:13 · process · **Technological Implementation**
画面：爬取流水滚动——robots.txt → sitemap（若是索引则播报并展开一个）→ 页面抓取 → 外链槽位表 → 逐链探测。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 3:45–3:46 | Watch it work. | 看它干活。 |
| 3:46–4:07 | It honours robots.txt, fetches the sitemap — and if that's an index, it says so and expands one — crawls a few pages, extracts every outbound link, skips social-share and same-site links as noise, then probes each survivor over read-only HTTP: at most one request per link, politely rate-limited. | 它遵守 robots.txt，抓 sitemap——若是索引就明说并展开一个——爬几页，抽出每条外链，把社交分享与站内链接当噪声跳过，再对每条幸存者走只读 HTTP 探测：每链至多一次请求，礼貌限速。 |
| 4:07–4:13 | No LLM, no credentials, and it never writes back — not here, not anywhere. | 无 LLM、无凭证，且绝不写回——这里不会，任何地方都不会。 |

## Shot 15 · 4:13–4:38 · show：报告 + A vs B · **Impact / Design**
画面：定格终端报告——逐槽位 HTTP 判定、健康计数（8/8）、诚实行 `--dry-run: nothing written to any database`。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 4:13–4:24 | The payoff: a plain link-rot report in the terminal — every outbound slot with its HTTP verdict, a healthy count, and the honesty line: read-only, nothing written. | 回报：终端里一份朴素的链接腐烂报告——每个外链槽位带 HTTP 判定、一个健康计数，和那行诚实声明：只读，什么都没写。 |
| 4:24–4:30 | That is the whole point of Path A: any website, a real report in under a minute, zero setup. | 这就是 Path A 的全部意义：任意网站，一分钟内出真报告，零配置。 |
| 4:30–4:35 | Path B goes deeper — block-level fixes and write-back on your own site. | Path B 更深——在你自己站上做块级修复与写回。 |
| 4:35–4:38 | Path A is the door; Path B is the house. | Path A 是门，Path B 是房子。 |

---

# Close（4:38–4:57）

## Shot 16 · 4:38–4:57 · 收尾字卡
画面：字卡 `#end`——`You approve decisions, not links.`

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 4:38–4:42 | EverLink patrols twenty-three thousand links so I don't have to. | EverLink 巡两万三千条链接，我就不用。 |
| 4:42–4:49 | It's honest about its limits, never touches my disclosures, verifies its own fixes, and hands me back about six hours a week. **[EST.]** | 它对能力诚实、绝不碰我的披露、自验修复，每周还我大约六小时。**[估算]** |
| 4:49–4:55 | Built with the Strands Agents SDK and Amazon Bedrock for Agents for Humans. | 用 Strands Agents SDK 与 Amazon Bedrock 为 Agents for Humans 而建。 |
| 4:55–4:57 | You approve decisions, not links. | 你批的是决策，不是链接。 |

---

## 命令小抄（终端镜头，在 IDE 终端面板跑；节奏用判定点吸收波动）

```
Shot 8  (1:28 敲) python -m everlink scan --site aethelgem --judge mantle --dry-run --limit 6      实测 39–56s；判定点 A ≈ 2:15
Shot 9  (定格后敲) python -m everlink notify --brief --dry-run                                       实测 2–8s；16 pending；末行 inbox 深链
Shot 12 (~3:13 敲) python scripts/run_evals.py --full --trace console                               实测 19–22s；可 3:08 预敲对齐 summary
Shot 13 (3:29 敲) python -m everlink scan --site https://blog.python.org --include-internal --dry-run --limit 8   实测 10–58s；判定点 B ≈ 4:13
```

工作目录：`d:\qcoder\everlink`。**四条命令当场敲回车**（不许提前跑完再回放）；时长波动全部落在判定点规则里，不需临场改命令/参数/顺序。

## Board URL 清单（生产；录前逐条 Browser DOM 验证渲染 OK）

```
S7  产品页/介绍  https://everlink-seven.vercel.app/                       (顶部停 → End 到底；旧 /how-it-works 已 308 并入此页)
S10 收件箱      https://everlink-seven.vercel.app/inbox                  (16 张 pending；交互可用)
S11 steering   https://everlink-seven.vercel.app/audit?event=steering_cancel   (3 行 + 过滤条)
S11 披露卡      https://everlink-seven.vercel.app/decision/dec-2b91672858      (Rejected · typed 理由确认不写)
S11 applied 卡  https://everlink-seven.vercel.app/decision/dec-b21f3d82bc      (Applied · Evidence=新 URL · tag 需遮)
S11 write/verify https://everlink-seven.vercel.app/audit?event=write · ?event=verify   (38 / 38 行)
S11 report     https://everlink-seven.vercel.app/report                 (Links healed 37)
S11 rollback对  https://everlink-seven.vercel.app/audit?event=rollback · ?event=dead_letter  (1 / 1 行)
S10 rejected   https://everlink-seven.vercel.app/inbox?status=rejected  (69 张) · applied ?status=applied (37 张)
字卡          file:///d:/qcoder/_demo_cards.html#positioning · #stats · #principle · #resources · #end
外站          https://www.aethelgem.com (1.5–3s) · https://hotdeals.today (预热后 ~2.9s)
第三站        flashdeals.today（内部代号 sandcart = FlashDeals 独立站，HTTP 200，不做实时导航）· 无 sandcart.com 域名
```

## 演练记录（历史，关键实测值）

| 项 | 结果 |
|---|---|
| v2rayN 拉起 | `python d:\qcoder\_start_proxy.py`（自动启动 + 等端口，实测 PROXY UP） |
| 生产 board 连通 | 强制代理探测 200/2.3s；Browser view 导航 + 渲染 OK |
| scan `--judge mantle` | 两遍 **39s / 56s**：6 扫 → 5+1 或 4+2、真实 qwen `REWRITE_SENTENCE`（risk=high）、steering 0 blocked、1–2 卡、dry-run 零写入；连跑结构一致仅措辞不同（[REAL] 预期） |
| notify `--brief` | **2s / 7.5s**；18 slots / 16 cards / 晨报含 inbox 深链 / "nothing sent" |
| evals `--full --trace` | 三次 **19s / 20.5s / 22s**；OVERALL PASS（50/50、0、三项 100%、cards 41） |
| generic blog.python.org | 两次 **10s / 58.3s**；8/8 healthy + dry-run 行 |
| 开放部署 DOM（09-06 起） | `/inbox` 勾选框/批量条、卡片页 approve/reject 按钮真实可用；API 写放行；写入仅落 EverLink 镜像库（本会话 Browser 复核仍为真） |
| 已修的产品问题 | ① notify 深链 `/inbox`（不再指根路径）；② evals 屏幕 note 由过期 `--judge bedrock` 改 `--judge mantle`；③ 测试数 311 → 312 → **319（当前，pytest 实测）**，DEVPOST/README/SUBMISSION_CHECKLIST/BLOG_DRAFT 已同步；④ board cron 心跳改为 **cadence-aware**（从台账 fire 间隔推断周期，日级 cron 也读 alive，Run-now 门控独立）；⑤ Path A generic 跳过社交分享挂件、sitemap-index 采样显式化 |
| 已知坑 | Qoder 崩溃会带走 Browser view（navigate 唤醒）与代理（`_start_proxy.py` 拉起）；节点刚起时 vercel.app 首航超时须重试；hotdeals 导航工具超时但页面会渲染；audit 事件名是 write/verify/rollback/dead_letter（**不存在 apply**）；列表页客户端渲染，httpx 探针只见空壳，画面内容以 Browser DOM 核验；管道/重定向捕获 Python 输出按 cp936 会把 em dash/箭头变 `??`（**仅捕获假象**，IDE 终端 Unicode 直写画面正常，不要为此改命令） |

## 录制口径

所有 `--dry-run`：零写库、零发送；屏幕上的诚实行（"nothing written to any database" / "nothing sent"）是加分画面，**不要剪掉**。数字以屏幕实况为准；`[REAL]` 真实调用、`[SEEDED REPLAY]` 种子回放、`[EST.]` 估算，三标签不混用。

## ALT cues（仅当晚退回 stub 时用；mantle/bedrock 真实模式用正文 [REAL] 字幕，无需 ALT）

- **ALT-1**（换 Shot 8 的 1:56–2:08）：The Judge seam runs on its injected stub tonight — same structured Proposal, same harness that scores the live Bedrock path. ／ 今晚 Judge 缝跑在注入 stub 上——同样的结构化 Proposal、同一套给 Bedrock 真路径打分的评测。
- **ALT-2**（仅当 mantle 与 bedrock 当晚都跑不起来、全程未真跑 Bedrock 时才换 Shot 16 的 4:49–4:55）：Built with the Strands Agents SDK for Agents for Humans. ／ 用 Strands Agents SDK 为 Agents for Humans 而建。（mantle 即真跑 Bedrock Mantle 网关，此时收尾可如实宣称 "Strands SDK + Amazon Bedrock"，无需 ALT-2。）
- **ALT-3**（仅当 Shot 9 的晨报未进画面时换 2:20–2:26）：Then the morning brief: sixteen problem slots are waiting in my inbox. ／ 然后是晨报：十六个问题槽位在我收件箱里等着。（去掉 "pushed as a notification"——没进画面就不宣称；16 由 `/inbox` 的 16 张 pending 实证。）

## 录后清单

1. 总时长 ≤ 5:00（秒表核对；配音实测 4:57.1）。
2. YouTube 上传 → **Unlisted** → 复制带链接 URL → Devpost Project details video 字段。
3. 录屏文件本地留档（deadline 后冻结不改）。
