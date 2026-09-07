# EverLink — Demo Storyboard (分镜 · 停留 & 切点 timing)

视觉分镜：把 `docs/video/vo_full.vtt` 的**配音实测时间码**映射到每一屏——**停多久 / 何时滚动 / 何时敲回车 / 何时定格 / 何时切页**。
配套三份并看：旁白 [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) · 双语字幕+URL [`DEMO_RUNSHEET.md`](DEMO_RUNSHEET.md) · 本表控**画面节奏**。配音 `docs/video/vo_full.mp3`（实测 **4:57.1**）。

**五条总原则**
1. **画面切到配音上**：每个视觉动作对齐一个 VTT cue 边界（下表时间为实测，±0.5s 可接受）。
2. **标题卡**：整段旁白时长 = 卡片停留时长；卡间硬切（或 6 帧淡入），不额外留白。
3. **终端镜头**：命令**预敲好**、在 cue 边界按回车；输出滚动本身即 `[REAL]` 证据；报告定格对齐"report lands / payoff"那句。
4. **Board 镜头**：全 URL 导航（不现场找路），每页停留见下表；**Shot 11 是快切蒙太奇**（7 屏 / 28s），录前把这些 URL 预开到浏览器标签，切页才零延迟。
5. **判定点吸收波动**：A ≈ **2:15**（scan 报告是否定格）、B ≈ **4:13**（generic 报告是否定格）。未定格 → 滚动画面继续当证据、旁白照读，**不重录**。

---

## 一、分镜总表（16 shot）

| # | 时间 | 屏 / URL | 停留 | 画面动作 | 旁白覆盖（VTT cue） |
|---|---|---|---|---|---|
| 1 | 0:00–0:08 | 字卡 `#positioning` | 8s | 硬切入，静置 | EverLink is… you approve |
| 2 | 0:08–0:16 | 字卡 `#stats` | 8s | 硬切，静置 | three sites… Never |
| 3 | 0:16–0:22 | aethelgem.com → hotdeals.today | 3s + 3s | 0:16 导航站1，0:19 导航站2 | they rot… patrols them |
| 4 | 0:22–0:36 | 字卡 WHO·WHY + **track 徽章** | 14s | 硬切；track 徽章 0:24 淡入 | who it's for… **track**… why an agent |
| 5 | 0:36–0:55 | 字卡 `#principle`（3 子卡） | 19s | PATROL 0:38 亮 / DECIDE 0:41 亮 / ACT 0:48 亮（逐条 reveal） | principle… patrol… decide… act & prove |
| 6 | 0:55–1:04 | 字卡 `#resources` | 9s | 硬切，静置 | MIT repo… live example |
| 7 | 1:04–1:28 | **`/`**（顶部→底部） | 顶 5s + 底 19s | 1:04 顶部；**1:09 按 End 滚到底**；底部 Path A 卡对 1:09–1:17、Path B 卡对 1:17–1:24 | how to use… Path A… Path B… read-only |
| 8 | 1:28–2:15 | 终端 `scan`（Path B） | 命令 8s + 滚动 ~31s + 定格 ~8s | **1:28 回车**（命令预敲）；输出滚动；报告 ~2:07–2:15 定格 | Demo one… I type… Scanner… Judge… needs-recheck |
| 9 | 2:15–2:26 | 终端 report → `notify --brief` | report 4s + brief 7s | 2:15 报告定格；**2:19 回车 notify**；2:21 晨报出现 | report lands… morning brief |
| 10 | 2:26–2:45 | **`/inbox`**（16 pending） | 19s（单页慢滚） | 2:26 导航；匀速慢滚；2:34 高亮勾选框/批量条 | only screen… 16 cards… batch… rejections |
| 11 | 2:45–3:13 | **7 屏快切蒙太奇** | 见细则（2/5/4/5/4/3/5s） | 逐 URL 切页（预开标签） | two guards… steering-cancel… writer… rollback… 37 healed |
| 12 | 3:13–3:29 | 终端 `run_evals` | 滚动 13s + summary 3s | 后台 ~3:05 预敲回车；3:13 切到该终端；summary ~3:26 定格 | I test it… 50-case… non-vacuous |
| 13 | 3:29–3:45 | 终端 `scan`（Path A generic） | 命令行 16s | **3:29 回车**（预敲）；命令行 + 初始输出 | Demo two… no db… I point it at blog.python.org |
| 14 | 3:45–4:13 | 终端 crawl 滚动 | 28s | 滚动：robots → sitemap → pages → slots 表 → 逐链探测 | watch it work… honours robots… never writes back |
| 15 | 4:13–4:38 | 终端 report 定格 | 25s | 4:13 报告定格（8/8 + dry-run 行）；4:30 可叠 A-vs-B 小字 | payoff… whole point… Path B deeper… door/house |
| 16 | 4:38–4:57 | 字卡 `#end` | 19s | 4:38 硬切；4:42 "~6 h/week" 小字淡入；4:57 淡出黑场（留 ~3s 尾黑到 5:00） | patrols 23k… six hours… Strands+Bedrock… you approve |

---

## 二、逐镜细则（重点：web 页停留多久）

### Shot 7 · `/` 产品页（1:04–1:28，24s）— 两停
| 子镜 | 时间 | 停留 | 画面 |
|---|---|---|---|
| 7a 顶部 | 1:04–1:09 | **5s** | hero 定位句 + 三徽章（开源 MIT / 自托管非 SaaS / Strands+Bedrock）+ 双库模型两卡；旁白"How you use it… two ways" |
| —滚动 | **1:09 按 End** | ~1s | 一次滚到底（docH ≈ 2 屏）；滚动动作压在"Path A"出口前 |
| 7b 底部 | 1:09–1:28 | **19s** | 六阶段 pipeline 图 + 自动化面板 + **两接入路径**。Path A 卡对旁白 1:09–1:17（可鼠标圈一下），Path B 卡对 1:17–1:24，"source read-only"句对 1:24–1:28 |

> 关键：**先滚到底再讲 Path A/B**——两条路径的卡在页面底部，别停在顶部念 Path A。

### Shot 10 · `/inbox`（2:26–2:45，19s）— 单页慢滚
| 子镜 | 时间 | 停留 | 画面 |
|---|---|---|---|
| 10a | 2:26–2:29 | 3s | 列表首屏，16 张 pending 卡入画（"the only screen I open"） |
| 10b | 2:29–2:34 | 5s | 匀速慢滚半屏，露出更多卡的证据摘要（"sixteen cards wait"） |
| 10c | 2:34–2:38 | 4s | 鼠标悬停/勾选 2–3 张卡的复选框，底部批量条亮起（"approve the safe ones in a batch"）——**开放部署交互可用**，可真抓一下 |
| 10d | 2:38–2:45 | 7s | 滚到一张带 typed why 的驳回态或保持批量条（"rejections carry a typed why"） |

> 全程**一张页面**，靠慢滚 + 勾选高亮撑满 19s，不切页。

### Shot 11 · 两护栏 + 闭环（2:45–3:13，28s）— 7 屏快切蒙太奇
| 子镜 | 时间 | URL | 停留 | 画面重点 |
|---|---|---|---|---|
| 11a | 2:45–2:47 | （从 /inbox 切） | 2s | 转场；"Two guards matter most" |
| 11b | 2:47–2:52 | `/audit?event=steering_cancel` | **5s** | 3 行 steering_cancel + 过滤条可见 |
| 11c | 2:52–2:56 | `/decision/dec-2b91672858` | **4s** | 披露块 Rejected + typed 理由（NO write allowed） |
| 11d | 2:56–3:01 | `/decision/dec-b21f3d82bc` | **5s** | Applied · Evidence = 应用后新 URL · `Healthy HTTP 200`（联盟 tag 遮） |
| 11e | 3:01–3:05 | `/audit?event=write` | **4s** | 38 行 write（字幕带出 verify 38，不必再切一页） |
| 11f | 3:05–3:08 | `/audit?event=rollback` →`?event=dead_letter` | **3s** | 各 1 行；快切或左右并排一闪 |
| 11g | 3:08–3:13 | `/report` | **5s** | Links healed **37** / Slots fixed 37 |

> 录前把 11b–11g 六个 URL **预开到独立标签**（或 Browser view 收藏），录制时 `Ctrl+Tab` 顺序切，命中每页停留。这是全片唯一切页密集的段落，节奏要卡稳。

### Shot 8 / 12 / 13 · 终端镜头的敲键时机
- **Shot 8（scan，1:28 回车）**：命令 `… scan --site aethelgem --judge mantle --dry-run --limit 6` 预先敲好，**1:28 准点回车**。实测 39–56s：跑得快报告 ~2:07 定格（多定格 8s），跑得慢到 2:15 仍在滚——都进判定点 A，旁白照读。
- **Shot 12（evals）**：为让 summary 对上"三硬指标 100%"（cue 3:16–3:26），**在 Shot 11 期间的 ~3:05 于后台终端预敲回车**（真跑，非回放），3:13 切到该终端时 span 流已在滚，summary ~3:26 定格。若坚持"切到才敲"，则 3:13 回车、summary ~3:32 落到 Shot 13 头，滚动 span 当 [REAL] 证据、summary 作定格插入。
- **Shot 13（generic，3:29 回车）**：命令 `… scan --site https://blog.python.org --include-internal --dry-run --limit 8` 预敲，**3:29 准点回车**；实测 10–58s，判定点 B ≈ 4:13。

---

## 三、录制机制（如何稳定命中停留时长）

1. **倒计时进场**：每个 shot 用配音 cue 起点作"打板"，画面动作对齐 cue 边界，而非靠秒表目测。
2. **终端命令全部预敲**：4 条命令录前敲好不回车，到点才按（Shot 8/12/13 + Shot 9 的 notify）。禁"提前跑完再回放"——Shot 12 的后台预敲是**真跑**、3:13 起在屏上可见，合规。
3. **Board 页预开标签**：Shot 11 的 6 个 URL + Shot 7 的 `/` + Shot 10 的 `/inbox` 录前全开好，切页零延迟。
4. **慢滚而非静置**：`/inbox`（19s）、终端滚动（Shot 8/14）用匀速慢滚/让输出自然滚填满时长，避免死屏。
5. **定格 = 不动**：报告/summary 落地后无需操作，静置即定格；旁白读完再切。
6. **判定点不重录**：A(2:15)/B(4:13) 未定格就顺势用滚动画面，旁白与字幕不依赖"报告已定格"。
7. **遮敏在录制时**：Shot 11d 的 `dec-b21f3d82bc` Evidence 里 `tag=aethelgem-20`、任何 DB host/token/`.env` 当场 blur 或裁切。

---

## 四、停留时长预算（合计 = 4:57，与配音一致）

| 画面类型 | shots | 秒数 |
|---|---|---|
| 标题卡 | 1,2,4,5,6,16 | 8+8+14+19+9+19 = **77s** |
| 真站实拍 | 3 | **6s** |
| **Board 页** | 7,10,11 | 24+19+28 = **71s** |
| 终端 | 8,9,12,13,14,15 | 47+11+16+16+28+25 = **143s** |
| **合计** | 16 | **297s = 4:57** ✓（尾部 ~3s 黑场补到 5:00） |

> Board 页占 71s（Shot 7 的 24s + Shot 10 的 19s + Shot 11 的 28s），是"web 页面停多久"的全部预算；其中 Shot 11 每页 3–5s 属快切，Shot 7/10 是慢节奏单页。
