# EverLink — Demo Recording Run Sheet (bilingual, ≤ 5:00)

录制执行单：秒级字幕 cue（英）+ 中文对照 + 画面动作。配对文件：[DEMO_SCRIPT.md](DEMO_SCRIPT.md)（完整旁白稿）。
**录屏 = owner 动作**。工具：Xbox Game Bar（Win+G）或 OBS，1080p，导出 mp4 → YouTube **Unlisted** → 链接填 Devpost video 字段。

## 录前检查（5 分钟，2026-09-05 复演定稿）

1. **代理必须先活**：v2rayN（`D:\d36j0t1v\v2rayN\v2rayN.exe`）必须已启动且连上节点；验证 `python d:\qcoder\_proxy_check.py` 输出 `LISTENING`。**刚启动后节点需热身**——第一次导航 vercel.app 可能超时，重试即通。
2. **board 用生产地址** `https://everlink-seven.vercel.app`（禁 localhost）。**收件箱在 `/inbox`**（`/` 已是品牌落地页，不含卡片），录前导航一次 `/inbox` 确认 `Inbox · EverLink Board` 标题与 16 张 pending 卡出现。
   **录前预热**：把下方 URL 清单里的 board 地址逐个先导航一遍——Vercel 冷启动首航会报 10s 超时（其实内容已渲染），预热后录制时才秒开。
   **只读部署（09-05 起）**：生产 board 已设 `NEXT_PUBLIC_BOARD_READONLY=1`——`/inbox` 的勾选框与批量条、卡片上的 approve/reject 按钮统一换成 `Read-only view — decisions are disabled on this deployment.` 提示行，API 写操作返回 403。理由：匿名评委若点了 approve，下一次 Railway nightly 的 worker 会真去改 AethelGem 线上内容；只读同时也把 Shot 4"只展示已落库结果、不现场点击"的口径变成平台强制。**画面影响**：Shot 4 三屏（`/inbox` 与两个 `?status=` 视图）不再有勾选框/批量条，改为只读提示行；卡片详情页（如 pending 卡 `dec-ea20afaafa`）原按钮位置同样显示该提示。二遍演练 DOM 实测：`/inbox` 的 `input`/`button` 数均为 **0**，只读提示存在，16/37/69 计数不变。
3. **Judge 模式定档（2026-09-05 本地实测通过）**：默认 `--judge mantle` 录 Shot 3，字幕用 **[REAL]**（真实 LLM 调用，qwen via Bedrock Mantle 网关）。本地 `--limit 6` 实测 **39s / rc=0**，结构可复现（同 slot、同 `REWRITE_SENTENCE`、5 healthy + 1 offer_changed、steering 0 blocked、2 tool calls、1 决策卡），措辞每次不同属正常。
   **本地 mint 前置条件**：走 `~/.aws/credentials` 的 `[default]`；`.env` 里**绝不能有空值的 `AWS_ACCESS_KEY_ID=` / `AWS_SECRET_ACCESS_KEY=` / `AWS_PROFILE=` 行**——空串会遮蔽共享凭据文件，mint 直接报 `Failed to mint Bedrock Mantle bearer token`（09-05 已把这三行注释掉；`.env` 若重建须复查）。备选路径：`BEDROCK_MANTLE_API_KEY`（console 铸的 key，直作 OpenAI api_key）。直连 Claude 工单若批了可选 `--judge bedrock`；当晚都不可用才退回 `--judge stub` + 文末 **ALT cue**（诚实优先，不许嘴替）。
4. **数字复核（以屏幕实况为准，2026-09-05 复探）**：23,476（`data/slots_summary.json` 未变）；board 实况 **pending 16 / applied 37 / rejected 69 / healed 37**——69 条 rejected = 4 人工typed驳回 + 54 条 nightly recheck 误报退役 + 11 条 09-05 系统去重驳回，全部带理由落库；audit 全量 **steering_cancel 3 / write 38 / verify 38 / rollback 1 / dead_letter 1**（事件名是 write/verify，不存在 apply）；evals cards 41（fixture 语境）。`[REAL]`/`[SEEDED REPLAY]`/`[EST.]` 角标照 DEMO_SCRIPT 三标签执行。
5. **遮敏**：DB host、带 token 的 URL、`.env`、scan 输出里的联盟 tag（`tag=aethelgem2026-20`）blur/裁掉；board 卡片 Evidence 里的联盟 tag 同样要遮——09-05 二遍演练实测：`dec-b21f3d82bc` 的 Evidence 只渲染**应用后的新 URL**（`https://www.amazon.com/dp/…?tag=aethelgem-20`，Healthy HTTP 200），并不并列旧 URL，该 `tag=aethelgem-20` 需遮。
6. 字幕烧录或后期贴：每条 cue ≤ 2 行；角标标签与字幕同时出现。
7. **录屏范围**：全屏，须同时罩住 **IDE 终端面板**（终端镜头）与 **IDE 内置 Browser view 面板**（board/外站镜头）；IDE 最大化，无关窗口移出。Browser view 若关闭，我 navigate 即唤醒（演练已验证）。
8. **push 与录制的先后**：每次 `git push` 都会触发 Railway 部署并**跑一次完整 nightly**——09-05 09:17→09:32 UTC 实测 audit 事件持续上涨（`tool_result` 1662→1716、`notify` 100→102），跑完才停（本次未产生新卡，计数仍是 16/37/69，但这是运气不是保证）。所以顺序必须是 **改完 → push → 等 nightly 跑完（探针两次读数不再变）→ 复探计数 → 录**；录前 6 步跑完之后不要再 push。audit 总量因此是**动值**（09-05 实测 **1,994** 行），文案统一写 "~2,000 rows" 不写死。

---

## Shot 1 · 0:00–0:30 · 冷开场：真问题

画面：字卡 `#stats`（file:///d:/qcoder/_demo_cards.html#stats）→ **www.aethelgem.com**（实测 1.5–3s 载完）→ **hotdeals.today**（09-05 预热后 **2.9s** 载完；09-04 的 ~12s 是节点热身，导航工具报超时但页面其实已渲染——仍留足 15s）。第三站 **flashdeals.today**（内部代号 sandcart，即 FlashDeals dropshipping 独立站；首页实测 HTTP 200 可达）为保持节奏不做实时导航，"三站"叙事由 board 的站点徽章与 scan 报告补足。**注意：不存在 sandcart.com 这个域名**（旧稿误写，已废弃）。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:00–0:05 | These are my three content sites. | 这是我的三个内容站。 |
| 0:05–0:12 | Between them: 23,476 outbound link slots — product cards, affiliate links, references. | 合计 23,476 个外链槽位——商品卡、联盟链接、参考引用。 |
| 0:12–0:18 | The last time every one was checked by hand? Never. | 上一次逐条人工检查？从来没有。 |
| 0:18–0:25 | They rot a little every day — and nobody sees it until a reader does. | 它们每天烂一点——直到读者先发现。 |
| 0:25–0:30 | So tonight, an agent patrols them. | 于是今晚，一个 agent 替我值夜。 |

## Shot 2 · 0:30–1:00 · 三问：problem / who / why

画面：三张标题卡 PROBLEM · WHO · WHY（或人对镜头）。**0:38 在 IDE 终端敲入 Shot 3 的 scan 命令并回车**——09-05 两次实测 **39s / 55.9s**（外网 + Amazon L2 解析波动），report 定格落在 **1:17–1:34** 之间；**1:20 是切换判定点**，规则见 Shot 3。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 0:30–0:38 | The problem: links rot — products 404, affiliate programs end, prices drift from the sentence that cites them. | 问题：链接会腐烂——商品 404、联盟计划终止、价格与引用它的句子脱节。 |
| 0:38–0:44 | Broken-link checkers only report. They never decide what to do. | 死链检查器只报告，从不决定该怎么办。 |
| 0:44–0:52 | Who it's for: independent publishers and small content teams — one to three people, several sites. | 为谁：独立出版者与小型内容团队——一两三个人、管好几个站。 |
| 0:52–1:00 | Why an agent: "replace, rewrite, drop, or escalate" is repetitive, judgment-heavy work — exactly what an agent should take on. | 为何用 agent："替换、改写、删除、还是上报"是重复且吃判断力的活——正该交给 agent。 |

## Shot 3 · 1:00–1:35 · 夜间运行 [REAL/SEEDED]

画面：scan 已于 0:38 启动（`python -m everlink scan --site aethelgem --judge mantle --dry-run --limit 6`，09-05 两次实测 **39s / 55.9s**：`[1/2] discovering + detecting...` 立刻出现，report 定格在 **1:17–1:34**——6 扫 / healthy 与 offer_changed 的配比在 **5+1 与 4+2** 之间浮动 / 真实 qwen 的 `REWRITE_SENTENCE` 提案与理由滚动 / steering 0 blocked / 决策卡 **1–2 张**，均属 [REAL] 正常波动）→ **1:20 切换判定点**：① report 已定格 → 立刻 `python -m everlink notify --brief --dry-run`（实测 **2s / 7.5s**，**16 pending** 晨报，末行 `Open the inbox : https://everlink-seven.vercel.app/inbox`，09-05 已修为深链不再指根路径），晨报停 3–5s 再切 board；② 1:20 仍在滚 → **直接切 Browser view：生产 board `/inbox`**（16 张 pending 卡），live notify 那一拍改用 **ALT-3**（终端里仍在滚动的真实调用本身就是 [REAL] 证据）。两句诚实行（`--dry-run: nothing written to any database` / `nothing sent`）在画面内**保留**。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 1:00–1:07 | Every night, a cron kicks off the loop: Scanner, Judge, Writer — three agents under one orchestrator. | 每晚 cron 启动循环：Scanner、Judge、Writer 三个 agent 归一个编排器管。 |
| 1:07–1:15 | The Scanner probes every slot: HTTP status and redirect chains first, a stealthy page parse only when inconclusive. | Scanner 先探 HTTP 状态与重定向链，拿不准才做深层页面解析。 |
| 1:15–1:23 | The Judge — a real LLM on Amazon Bedrock — decides the fix and emits a structured Proposal. **[REAL]** | Judge（Amazon Bedrock 上的真实 LLM）决定修法并输出结构化 Proposal。**[真实调用]**（mantle/bedrock 均为真实；仅退回 stub 时换 ALT-1） |
| 1:23–1:29 | Blocked or timed out? Flagged needs_human_recheck — it never fabricates a result. | 被墙或超时？标记 needs_human_recheck——绝不编造结果。 |
| 1:29–1:35 | By morning: 16 problem slots in my inbox, as a morning brief. **[REAL + SEEDED REPLAY]** | 早上：16 个问题槽位以晨报形式到达（nightly 真实提案 + 种子回放卡，各自带标签）。**[真实+种子回放]** |

## Shot 4 · 1:35–2:15 · 决策收件箱 [SEEDED]

画面（全 URL 导航，零点击）：`/inbox`（pending **16** 张）→ `/inbox?status=applied`（**37** 张已批准）→ `/inbox?status=rejected`（**69** 张 = 4 人工 typed 驳回 + 54 recheck 误报退役 + 11 系统去重，全部带理由落库）→ 打开 **`/decision/dec-7158d74e33`**（Rewrite sentence 被驳回：价格 $199→$349、"under $200" 表述过期，驳回理由已落库）→ 返回 rejected 列表停。**线上只读，不现场点击 approve/reject——展示已落库结果。**

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 1:35–1:42 | The only screen I open: a minimal approval inbox. | 我唯一打开的界面：一个极简审批收件箱。 |
| 1:42–1:50 | Low-risk fixes are batched — 37 applied and verified so far. **[SEEDED REPLAY]** | 低风险修复批量处理——已应用并验证 37 条。**[种子回放]** |
| 1:50–1:58 | The risky ones I read individually — rejections like this carry a typed reason; false positives the recheck retires land in the same list, reasoned. | 高风险的我逐条读——像这条驳回带着写明的理由；nightly recheck 退役的误报也进同一清单，同样有理由落库。 |
| 1:58–2:06 | The agent remembers that reason and won't re-propose the same fix next week. | agent 记住理由，下周不会重提同样的修复。 |
| 2:06–2:15 | Every card carries its evidence: the HTTP trail, the page context, and the policy that shaped it. | 每张卡都带证据：HTTP 轨迹、页面上下文、以及塑造它的策略。 |

## Shot 5 · 2:15–2:50 · 安全幕 1：披露守护

画面：Browser view **`/audit?event=steering_cancel`**（过滤条显示 3 行，disclosure_policy 的 cancel_message 可见；不带过滤时埋在近 2,000 行里不可达——09-05 09:32 UTC 实测 audit 总量 **1,994** 行，每晚还涨几十行，字幕/文案统一说 "~2,000 rows" 不写死）→ 打开 **`/decision/dec-2b91672858`**（Rejected · 人工 typed 理由："Acknowledged — the disclosure block is structurally protected, so NO write is allowed"）。旧 escalate 卡 dec-d75e0275a8 已被 recheck 退役（404），弃用。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 2:15–2:22 | This block is a dead link — but it also carries my affiliate disclosure. | 这个块是死链——但它同时承载我的联盟披露声明。 |
| 2:22–2:30 | Deleting it would be a legal and trust disaster. | 删掉它等于法律与信任灾难。 |
| 2:30–2:38 | A DisclosurePolicy steering hook marks the slot protected and cancels the drop before it happens. | DisclosurePolicy 引导钩子把槽位标为受保护，在删除发生前取消工具调用。 |
| 2:38–2:45 | The audit log records steering_cancel; the decision went to a human, who confirmed on the record: no write may touch it. | 审计日志记下 steering_cancel；决策随后到人工，录在案的确认：任何写动作碰不了这个块。 |
| 2:45–2:50 | Disclosure text is structurally immune — no write action can touch it. | 披露文本结构性免疫——任何写动作碰不了它。 |

## Shot 6 · 2:50–3:40 · 安全幕 2 + 闭环 [REAL/SEEDED]

画面（全 URL 导航）：(a) 打开 **`/decision/dec-b21f3d82bc`**（Applied · High risk · Replace URL：Aurora Lab-Grown Diamond Solitaire 死链→活 offer；Evidence 区块渲染**应用后的新 URL** + `Healthy HTTP 200`，联盟 tag 需遮）；(b) **`/audit?event=write`**（38 行，每条 applied 修复一行、单事务）与 **`/audit?event=verify`**（38 行复探）；(c) `/report`：**Links healed 37 / Slots fixed 37**；(d) **`/audit?event=rollback`**（1 行）+ **`/audit?event=dead_letter`**（1 行，强制失败死信对）。**展示已落库闭环，不现场触发。**

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 2:50–2:58 | Editorial policy shapes every proposal: a dead merchant link gets replaced with a live offer — never silently dropped. | 编辑策略塑造每个提案：死的商品链接换成活的 offer——绝不静默删除。 |
| 2:58–3:06 | On approve, the Writer snapshots the block first, then applies the fix in a single transaction. | 批准后 Writer 先快照整个块，再在单事务里应用修复。 |
| 3:06–3:14 | Then a verify pass re-probes the new link — to confirm it's genuinely alive. **[REAL]** | 然后 verify 复探新链接——确认它真的活了。**[真实]** |
| 3:14–3:22 | Last night: 37 dead links verified back to zero. **[SEEDED REPLAY]** | 昨晚：37 条死链验回零。**[种子回放]** |
| 3:22–3:32 | If verification ever fails, it rolls back to the snapshot and dead-letters the decision with a recommendation card. | 一旦验证失败，回滚到快照，并把决策送入死信附建议卡。 |
| 3:32–3:40 | It closes the loop; it doesn't just claim success. | 它闭环，不只是宣称成功。 |

## Shot 7 · 3:40–4:10 · 评测：50 例三硬指标 [REAL]

画面：终端 `python scripts/run_evals.py --full --trace console`（三次实测 **19s / 20.5s / 22s**：先滚 OTel JSON span 流，最后定格 summary 块——50/50=100% / steering 0 / 三硬指标 100% / cards 41 / **OVERALL: PASS** + stub 诚实 note）。**note 末句 09-05 已改口径**：屏幕上是 `Score the real Judge with --judge mantle (the deployed Bedrock path; --judge bedrock is the direct-Claude route)`——与本片 `--judge mantle` 的真跑一致，不再是过期的 `--judge bedrock`。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 3:40–3:47 | I don't ask you to trust the agent — I test it. | 我不求你信 agent——我测试它。 |
| 3:47–3:55 | A 50-case eval suite runs fully offline against a fixture server with known ground truth. | 50 例评测套件全离线跑在有已知真值的 fixture 服务器上。 |
| 3:55–4:03 | Detection 100%, steering violations zero, and three hard metrics at 100%. | 检测 100%、引导违规零、三项硬指标 100%。 |
| 4:03–4:10 | And the oracle is proven non-vacuous: inject a rule-breaking judge, and the evaluators catch it. | 评测 oracle 本身也非空转：注入一个违规 judge，评测器抓得住它。 |

## Shot 8 · 4:10–4:40 · 通用适配器 + live demo

画面：**4:10 敲回车** IDE 终端 `python -m everlink scan --site https://blog.python.org --include-internal --dry-run --limit 8`（09-05 两次实测 **10s / 58.3s**——外网波动大，8/8 healthy + dry-run 诚实行）。**4:26 判定点**：① 已定格 → 终端停 3–5s 再切 board；② 仍在滚 → **直接切 board**（终端里还在跑的真实抓取就是证据，字幕 4:18–4:26 "从没见过的站" 配滚动画面同样成立），generic 的 8/8 不进画面。随后 Browser view：生产 board **落地页 `/`**（`h1` = "EverLink"，副标 `The autonomous link-rot steward`；页面 title 为 "EverLink · the autonomous link-rot steward"——正文首字母大写，字幕/文案引用时按实际大小写）→ **`/inbox`**（种子数据保证总有真东西可看）→ **`/how-it-works`**（公开介绍页：品牌 mark 链回 `/`、正文 GitHub 链接 ×2 + 联系邮箱 mailto；09-05 新增镜头）。

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 4:10–4:18 | This isn't hard-coded to my sites: a generic adapter scans any blog, read-only. | 这不是为我站硬编码：generic 适配器只读扫描任意博客。 |
| 4:18–4:26 | Here it is on a site EverLink has never seen. | 这是一个 EverLink 从没见过的站。 |
| 4:26–4:33 | And here's the live board — seeded so there's always something real to look at. | 这是线上 board——种子数据保证总有真东西可看。 |
| 4:33–4:40 | Public intro page, repo link, contact — open source, self-hosted, read-only by design. | 公开介绍页、仓库链接、联系邮箱——开源、自托管、只读是设计决定。 |

## Shot 9 · 4:40–5:00 · 收尾

画面：人对镜头或周报页 → 结束字卡 `You approve decisions, not links.`

| in–out | EN subtitle | 中文对照 |
|---|---|---|
| 4:40–4:47 | EverLink patrols 23,476 links so I don't have to. | EverLink 巡 23,476 条链接，我不用。 |
| 4:47–4:54 | Honest about its limits, immune to disclosures, verifies its own fixes, rolls back when wrong. | 对能力诚实、披露免疫、自验修复、错了回滚。 |
| 4:54–5:00 | You approve decisions, not links. | 你批的是决策，不是链接。 |

---

## 命令小抄（终端镜头，在 IDE 终端面板跑；节奏用 sleep 控制）

```
Shot 3:  python -m everlink scan --site aethelgem --judge mantle --dry-run --limit 6   (0:38 敲回车；实测 39–56s，真实 qwen；1:20 判定点)
         python -m everlink notify --brief --dry-run                                  (实测 2–8s，16 pending，末行 inbox 深链)
Shot 7:  python scripts/run_evals.py --full --trace console                           (实测 19–22s)
Shot 8:  python -m everlink scan --site https://blog.python.org --include-internal --dry-run --limit 8   (4:10 敲回车；实测 10–58s；4:26 判定点)
```

工作目录：`d:\qcoder\everlink`。**四条命令都要当场敲回车**（不许提前跑完再回放）；时长波动全部落在判定点规则里，不需要临场改命令、改参数或改顺序。

## Board URL 清单（生产，2026-09-05 复演逐条 Browser DOM 验证渲染 OK）

```
S8  落地页   https://everlink-seven.vercel.app/                      (品牌 hero："the autonomous link-rot steward")
S3/S4/S8 收件箱 https://everlink-seven.vercel.app/inbox               (16 张 pending)
S4  applied  https://everlink-seven.vercel.app/inbox?status=applied   (37 张)
S4  rejected https://everlink-seven.vercel.app/inbox?status=rejected  (69 张)
S4  驳回卡   https://everlink-seven.vercel.app/decision/dec-7158d74e33
S5  audit过滤 https://everlink-seven.vercel.app/audit?event=steering_cancel   (3 行+过滤条)
S5  披露卡   https://everlink-seven.vercel.app/decision/dec-2b91672858        (Rejected·typed 理由确认不写)
S6  applied卡 https://everlink-seven.vercel.app/decision/dec-b21f3d82bc
S6  write/verify https://everlink-seven.vercel.app/audit?event=write · ?event=verify   (38/38 行)
S6  rollback对 https://everlink-seven.vercel.app/audit?event=rollback · ?event=dead_letter  (1/1 行)
S6  report   https://everlink-seven.vercel.app/report         (Links healed 37)
S8  介绍页   https://everlink-seven.vercel.app/how-it-works   (品牌面板+页脚链接，09-05 新增)
字卡        file:///d:/qcoder/_demo_cards.html#stats · #cards · #end
外站        https://www.aethelgem.com (1.5-3s) · https://hotdeals.today (预热后 2.9s；冷启动 nav 可能报超时但页面会渲染，留 15s)
第三站      flashdeals.today（内部代号 sandcart = FlashDeals 独立站，HTTP 200 可达，演示不做实时导航）· 无 sandcart.com 域名
```

## 演练记录（2026-09-04，全链路 verified）

| 项 | 结果 |
|---|---|
| v2rayN 拉起 | `python d:\qcoder\_start_proxy.py`（自动启动+等端口，实测 PROXY UP） |
| 生产 board 连通 | 强制代理探测 200/2.3s；Browser view 导航+渲染 OK（visible 905×961，35 卡） |
| 8 个 board URL | 全部 200 且内容标记验证通过（rejected/rewrite/$349、escalate/stub、applied/replace、steering_cancel×3、verify×84、healed 37） |
| scan --limit 6 dry-run | 09-04 演练用 stub：~2min 全量；6×Amazon captcha→ESCALATE_HUMAN 诚实；steering 0 blocked/6 audited。**已于 09-05 用 `--judge mantle` 重演通过（39s），见下节** |
| notify --brief dry-run | ~2s；35 pending 全 high escalate；"nothing sent" |
| evals --full --trace | 22s；OVERALL PASS（50/50、0、三项 100%、cards 41） |
| generic blog.python.org | ~10s；8/8 healthy + dry-run 行 |
| 字卡三页 | file:// 渲染 OK（#stats/#cards/#end） |
| 已知坑 | Qoder 崩溃会带走 Browser view（navigate 唤醒）与代理（_start_proxy.py 拉起）；节点刚起时 vercel.app 首航超时须重试；hotdeals 导航工具超时但页面会渲染；audit 事件名是 write/verify/rollback/dead_letter（**不存在 apply**）；列表页（/、applied、rejected）为客户端渲染，httpx 探针只见空壳，画面内容以 Browser DOM 核验；cmd 单个 `&` 是异步执行，别误判同步完成 |

## 演练记录（2026-09-05 复演，全 9 Shot 逐拍 verified）

| 项 | 结果 |
|---|---|
| 字卡三页 | `#stats` / `#cards` / `#end` file:// 渲染 OK（23,476 与 `data/slots_summary.json` 一致，未改） |
| 外站 | aethelgem 200 正常；hotdeals.today 本次 **2.9s、无超时**（09-04 的 ~12s 是节点热身，预热后消失） |
| board 19 拍 | `/` 落地页 hero、`/inbox`(16)、`?status=applied`(37)、`?status=rejected`(69 + 目标驳回卡)、`dec-7158d74e33`（含新页脚链接）、`/audit?event=steering_cancel`（过滤条 + 3 行）、`dec-2b91672858`、`dec-b21f3d82bc`、`?event=write`(38)、`?event=verify`(38)、`?event=rollback`(1)、`?event=dead_letter`(1)、`/report`(37/37)、`/how-it-works`（mark 链 + GitHub + mailto 三标记 true）——全部通过 |
| scan `--judge mantle` | **修复后通过**：39s / rc=0 / 6 扫 → 5 healthy + 1 offer_changed / 真实 qwen `REWRITE_SENTENCE`（risk=high）提案与理由 / steering 0 blocked / 2 tool calls / 1 卡 / dry-run 零写入。连跑两次结构完全一致，仅措辞不同（[REAL] 预期行为） |
| notify `--brief` | ~2s；18 slots / 16 cards / 晨报含 inbox URL / "nothing sent"（`.env` 补第 39 行 `EVERLINK_BOARD_URL` 后不再出现 "(not set)" 丑括号） |
| evals `--full --trace` | 19s；OVERALL PASS（cards 41） |
| generic blog.python.org | 8/8 healthy + dry-run 行 |
| 新发现并已修的坑 | ① `.env` 里空值 `AWS_*` 行遮蔽 `~/.aws/credentials` → mantle mint 失败（已注释三行，B/C 两路实测 mint 0.9–1.1s OK，无需代理）；② board 列表页迁到 `/inbox`，`/` 变落地页（URL 清单已改）；③ Vercel 冷启动首航报 10s 超时但 `readyState=complete`、内容齐全 → **录前预热全部 URL**；④ `pip install` 参数带引号会被原样传参报错（用 `pip install strands-agents[openai]==1.54.0` 不加引号） |
| 二遍演练（只读部署后，Browser 17 拍） | **全部 PASS**：字卡三页 · aethelgem（title/h1 实测）· hotdeals **2.3s 无超时** · `/` 落地页 · `/inbox` 16 卡 + 只读提示 + `input`/`button` 均 0 · applied 37 · rejected 69 · `dec-7158d74e33`（$349 / under $200 + 页脚 GH/mailto）· pending 卡 `dec-ea20afaafa` 只读提示 · `?event=steering_cancel` chip + 3 行 · `dec-2b91672858` · `dec-b21f3d82bc` · write/verify/rollback/dead_letter = 38/38/1/1 · `/report` 37/37 · `/how-it-works`（GH×2 + mailto + mark）。两处文案按实测修正：hero 正文首字母大写（小写串只在 title）；Evidence 只渲染新 URL（`tag=aethelgem-20`） |
| 三遍演练（终端四拍干净顺序复演） | **全部 rc=0**：scan `--judge mantle` **55.9s**（6 扫 → 4 healthy + 2 offer_changed、2 卡、4 tool calls，比首演多一个 slot `aethelgem:8:44:0`——Amazon L2 实况波动，属 [REAL] 正常）· notify `--brief` **7.5s**（18 slots / 16 cards）· evals `--full` **20.5s** OVERALL PASS · generic blog.python.org **58.3s**（8/8 healthy）。时长波动已写进各 Shot 的判定点规则（1:20 / 4:26），录制时不需要临场改命令 |
| 三遍发现并已修的产品问题 | ① **notify 把 board 根 URL 当收件箱链接**（`/` 现在是落地页）→ 新增 `_deep_link()`，晨报与批量信的 text + html CTA 一律指 `/inbox`（子路径部署如 `board.x/everlink` 不追加，新增 1 条断言守住）；② **evals 屏幕 note 过期**（写 `--judge bedrock`）→ 改 `--judge mantle`，并给 `run_evals.py --judge` 与 `evals._make_judge()` 补上 mantle 分支——此前该 flag 根本不存在，DEMO_SCRIPT "scored with the same harness via --judge mantle" 是空头支票（实测 `_make_judge('mantle')` 1.2s 建出真模型 Agent）；同步 EVALS_REPORT / README / BLOG_DRAFT；③ 测试数 **311 → 312**，DEVPOST×2 / README×2 / SUBMISSION_CHECKLIST×1 已同步 |
| 已知坑（三遍补） | 用管道或重定向捕获 Python 输出时按 cp936 编码，em dash / 箭头会变 `??`——**只是捕获假象**：IDE 终端是 Unicode 控制台直写，录制画面正常。**不要为此改命令或把文案降级成 ASCII** |

## 录制口径

所有 `--dry-run`：零写库、零发送；屏幕上的诚实行（"nothing written to any database" / "nothing sent"）是加分画面，**不要剪掉**。

## ALT cues（仅当晚退回 stub 时用；mantle/bedrock 真实模式用正文 [REAL] 字幕，无需 ALT）

- **ALT-1**（换 Shot 3 的 1:15–1:23）：The Judge seam runs on its injected stub tonight — same structured Proposal, same harness that scores the live Bedrock path. ／ 今晚 Judge 缝跑在注入 stub 上——同样的结构化 Proposal、同一套给 Bedrock 真路径打分的评测。
- **ALT-2**（仅当 mantle 与 bedrock 当晚都跑不起来、全程未真跑 Bedrock 时才换 Shot 9 的 "Built with the Strands Agents SDK and Amazon Bedrock" 句）：Built with the Strands Agents SDK for Agents for Humans. ／ 用 Strands Agents SDK 为 Agents for Humans 而建。（注：mantle 模式即真跑 Bedrock Mantle 网关，此时收尾可如实宣称 "Strands SDK + Amazon Bedrock"，无需用 ALT-2。）
- **ALT-3**（仅当 Shot 3 的 scan 到 1:20 仍未定格、live notify 那一拍被切掉时换 1:29–1:35 句）：By morning: 16 problem slots are waiting in my inbox. **[REAL + SEEDED REPLAY]** ／ 早上：16 个问题槽位在我的收件箱里等着。**[真实+种子回放]**（去掉 "as a morning brief"——晨报没进画面就不宣称它进画面；16 这个数字由 `/inbox` 的 16 张 pending 卡实证。）

## 录后清单

1. 总时长 ≤ 5:00（秒表核对）。
2. YouTube 上传 → **Unlisted** → 复制带链接 URL → Devpost Project details video 字段。
3. 录屏文件本地留档（deadline 后冻结不改）。
