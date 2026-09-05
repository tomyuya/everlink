# EverLink 自托管上手清晰化 + origin 配置化 — 实现计划

> **For agentic workers:** REQUIRED: 用 superpowers:subagent-driven-development（若有 subagent）或 superpowers:executing-plans 执行本计划。步骤用 checkbox（`- [ ]`）语法跟踪。

**Goal:** 把 EverLink 的"开源 · 自托管 · 非 SaaS"定位在 README 与 board 上讲到陌生人一眼看懂，并把站点 origin 从硬编码改为部署者填写的 env 配置，从根上消除上帝视角失真。

**Architecture:** origin 走 env-only（`<SITE>_PUBLIC_ORIGIN`），解析封装在 `adapters.resolve_origin`，`cli.py`/`agents.py`/`db.py` 不改；board 新增只读静态 `/how-it-works` 页，复用现有 `Pipeline`/`AutomationPanel` 组件；文档统一把三个站点定位为 maintainer 的 dogfooding 示例键，对外展示 FlashDeals。

**Tech Stack:** Python 3.14 + Strands Agents SDK（adapters / pytest）；Next.js 16 + React 19 + Tailwind（board）；Markdown（文档）；Neon Postgres（数据修复）。

**Spec:** [`docs/specs/2026-09-05-self-hosted-onboarding-and-origin-config-design.md`](../specs/2026-09-05-self-hosted-onboarding-and-origin-config-design.md)

> **Commit & push 约定（贯穿全计划）**：每个 Task 末尾的 commit step 是 TDD 的"frequent commit"节拍标记。实际执行时遵循 owner 既定约束——commit message 用 `-F <file>` 传入（不内联长消息）、`git push` 用原生命令走已配置代理（`127.0.0.1:10809`，**绝不**加 `-c http.proxy=` 覆盖）、secrets/DSN 不进仓不打印。是否真正落 commit 由 Git 安全边界决定：本计划在全部 chunk 实现 + 验证通过后统一提交，不碎片化 push。

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `everlink/adapters.py` | 站点导出 → `LinkSlot`；origin 绝对化 | Modify：删 `SITE_BASE_URL`，加 `resolve_origin(site)`，`absolutize_slot_url(url, origin)` 纯函数化 |
| `tests/test_adapters.py` | origin 绝对化的回归测试 | Modify：从硬编码断言改为 `monkeypatch` env 驱动 |
| `.env.example` | 部署者 env 契约模板 | Modify：新增 `<SITE>_PUBLIC_ORIGIN` 段 |
| `README.md` | 开源门面 / 部署者契约 | Modify：顶部重写（定位 + NOT-SaaS + 契约表 + 双库图），修 origin 描述 |
| `board/app/how-it-works/page.tsx` | 产品原理 + 部署契约可视化（只读静态） | Create |
| `board/components/nav.tsx` | 顶部导航 | Modify：`LINKS` 加 How it works |
| `DEPLOYMENT.md` | 部署 runbook | Modify：补 origin env 配置 + env reference 行 |
| `ARCHITECTURE.md` | 架构图解 | Modify：sandcart 节点补示例键说明 |
| `CONTRIBUTING.md` | 开发规范 | Modify：加"origin 不硬编码"house rule |
| `board/README.md` | board 说明 | Modify：提 `/how-it-works` |

**边界原则**：Chunk 1（Python origin）与 Chunk 3（board 页）互不依赖，可并行；Chunk 2/4（文档）依赖 Chunk 1 定稿的 env 变量名。Chunk 5（数据修复）依赖 Chunk 1 部署上线。

---

## Chunk 1: origin 配置化（P0 · C，TDD 核心）

### Task 1.1: `absolutize_slot_url` 纯函数化 + `resolve_origin` env resolver

**Files:**
- Modify: `tests/test_adapters.py`（整文件重写为 env 驱动）
- Modify: `everlink/adapters.py:11-64`（imports + 删常量 + 新函数 + 调用点）

- [ ] **Step 1: 重写失败测试**（先让测试表达新契约：origin 从 env 来、函数签名收 origin、未配置则诚实原样返回）

将 `tests/test_adapters.py` 全文替换为：

```python
"""Adapter CSV loading: a first-party site's INTERNAL relative URLs are absolutized
against the site's PUBLIC ORIGIN, which the DEPLOYER configures via env — never
hardcoded in this open-source repo.

Regression history: 76 sandcart/FlashDeals slots were exported as bare `/products/...`
paths (no scheme). Stored as-is, every probe hit the SSRF guard's "scheme '' not
allowed" wall -> needs_human_recheck, and the Judge proposed destructive edits for a
"broken link" that was never broken. The fix resolves each relative URL against the
site's configured origin at ingestion. "sandcart" is the maintainer's internal codename
for the FlashDeals dropshipping storefront — a dogfooding EXAMPLE key, not an Amazon
affiliate; a deployer substitutes their own site key + origin.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from everlink import adapters  # noqa: E402

_HDR = ("id,site,article_id,article_title,block_id,block_type,slot_type,role,"
        "anchor_text,url,regions,protected")
_ORIGIN = "https://flashdeals.today"


def _write_csv(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(_HDR + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def test_absolutize_prefixes_relative_and_passes_absolute_through():
    # relative internal link gains the configured origin
    assert adapters.absolutize_slot_url("/products/waist-fan-6000mah", _ORIGIN) == (
        "https://flashdeals.today/products/waist-fan-6000mah")
    # an already-absolute URL is untouched (no double-prefix, no clobber)
    assert adapters.absolutize_slot_url(
        "https://www.amazon.de/dp/B00BCE30RS?tag=x", _ORIGIN) == (
        "https://www.amazon.de/dp/B00BCE30RS?tag=x")
    # no configured origin (None) => returned as-is; empty url => empty
    assert adapters.absolutize_slot_url("/p", None) == "/p"
    assert adapters.absolutize_slot_url("", _ORIGIN) == ""


def test_resolve_origin_reads_env_symmetric_with_dsn(monkeypatch):
    monkeypatch.setenv("SANDCART_PUBLIC_ORIGIN", _ORIGIN)
    assert adapters.resolve_origin("sandcart") == _ORIGIN
    monkeypatch.delenv("SANDCART_PUBLIC_ORIGIN", raising=False)
    # unset => None (the repo never guesses a domain)
    assert adapters.resolve_origin("sandcart") is None


def test_relative_url_absolutized_on_load_when_origin_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDCART_PUBLIC_ORIGIN", _ORIGIN)
    _write_csv(tmp_path, "slots_sandcart.csv", [
        'sandcart:a1:sec0:pl,sandcart,a1,"Best Portable Fans 2026",sec0,'
        'section_product_link,internal,,quiet 40dBA waist fan,'
        '/products/waist-fan-6000mah,,0',
    ])
    slots = adapters.load_slots("sandcart", data_dir=tmp_path)
    assert len(slots) == 1
    assert slots[0].url == "https://flashdeals.today/products/waist-fan-6000mah"


def test_relative_url_left_as_is_when_origin_unconfigured(tmp_path, monkeypatch):
    # HONEST behaviour: with no origin configured the relative URL is NOT guessed —
    # it stays relative so the missing-config surfaces instead of a fabricated domain.
    monkeypatch.delenv("SANDCART_PUBLIC_ORIGIN", raising=False)
    _write_csv(tmp_path, "slots_sandcart.csv", [
        'sandcart:a1:sec0:pl,sandcart,a1,"T",sec0,section_product_link,internal,,'
        'fan,/products/waist-fan-6000mah,,0',
    ])
    slots = adapters.load_slots("sandcart", data_dir=tmp_path)
    assert slots[0].url == "/products/waist-fan-6000mah"


def test_aethelgem_absolute_affiliate_url_survives_load_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("AETHELGEM_PUBLIC_ORIGIN", raising=False)
    _write_csv(tmp_path, "slots_aethelgem.csv", [
        'aethelgem:1:2:0,aethelgem,1,"T",2,product_card,component,,desk,'
        'https://www.amazon.de/dp/B00BCE30RS?tag=aethelgem2026-20,,0',
    ])
    slots = adapters.load_slots("aethelgem", data_dir=tmp_path)
    assert slots[0].url == "https://www.amazon.de/dp/B00BCE30RS?tag=aethelgem2026-20"


def test_merged_all_csv_absolutizes_per_row_site(tmp_path, monkeypatch):
    # slots_all.csv mixes sites; each row resolves by ITS OWN site's origin.
    monkeypatch.setenv("SANDCART_PUBLIC_ORIGIN", _ORIGIN)
    monkeypatch.delenv("AETHELGEM_PUBLIC_ORIGIN", raising=False)
    _write_csv(tmp_path, "slots_all.csv", [
        'sandcart:a1:sec0:pl,sandcart,a1,"Fans",sec0,section_product_link,internal,,'
        'fan,/products/waist-fan-6000mah,,0',
        'aethelgem:1:2:0,aethelgem,1,"T",2,product_card,component,,desk,'
        'https://www.amazon.de/dp/B00BCE30RS?tag=aethelgem2026-20,,0',
    ])
    by_site = {s.site: s.url for s in adapters.load_all(data_dir=tmp_path)}
    assert by_site["sandcart"] == "https://flashdeals.today/products/waist-fan-6000mah"
    assert by_site["aethelgem"] == "https://www.amazon.de/dp/B00BCE30RS?tag=aethelgem2026-20"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d d:\qcoder\everlink && python -m pytest tests/test_adapters.py -q`
Expected: FAIL —— `AttributeError: module 'everlink.adapters' has no attribute 'resolve_origin'`，且 `absolutize_slot_url` 签名不符（现收 `site` 而非 `origin`）。

- [ ] **Step 3: 改 `adapters.py` 实现新契约**

3a. 在 imports 段（`import csv` 附近，line 11-13）加 `import os`：

```python
import csv
import os
from pathlib import Path
from urllib.parse import urljoin
```

3b. 删除 `SITE_BASE_URL` 常量及其上方 12 行注释（line 20-31），替换为 env resolver。保留 `SITES` 与 `DATA_DIR` 不动。新代码：

```python
SITES = ("aethelgem", "sandcart", "hotdeals")


def resolve_origin(site: str) -> str | None:
    """The public origin a DEPLOYER configures for one site, via env.

    Symmetric with ``<SITE>_DATABASE_URL`` (see db.SOURCE_DSN_VARS). Some source
    databases store INTERNAL links as bare relative paths (e.g. ``/products/...``);
    a relative URL has no scheme, so the probe-side SSRF guard rejects it and the
    whole site surfaces as false ``needs_human_recheck`` cards. Resolving against
    the site's configured origin at ingestion fixes the root cause.

    NOTHING is hardcoded: this is an open-source, self-hosted project, so the repo
    can never know a deployer's domain. An unset origin returns ``None`` and the
    relative URL is left as-is — the missing config surfaces honestly instead of a
    guessed domain being fabricated.
    """
    return os.environ.get(f"{site.upper()}_PUBLIC_ORIGIN") or None
```

3c. `absolutize_slot_url` 改为接受注入的 `origin`（纯函数），替换 line 34-46：

```python
def absolutize_slot_url(url: str, origin: str | None) -> str:
    """Resolve a slot URL against a deployer-configured origin (pure function).

    * Already-absolute URLs (http/https) are returned unchanged — no double-prefix.
    * Relative internal links gain the origin via ``urljoin``.
    * No configured origin (or empty url) is returned as-is — never a guessed domain.
    """
    if not origin or not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(origin, url)
```

3d. `_row_to_slot` 的 url 行（line 61）改为注入 resolve 出的 origin：

```python
        url=absolutize_slot_url(row["url"], resolve_origin(site)),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d d:\qcoder\everlink && python -m pytest tests/test_adapters.py -q`
Expected: PASS（6 passed）。

- [ ] **Step 5: 跑全量离线套件确认无回归**

Run: `cd /d d:\qcoder\everlink && python -m pytest -q`
Expected: 全绿（此前 309 passed；本次仅 adapters 相关用例数变化，其余不受影响）。

- [ ] **Step 6: Commit（节拍标记，见顶部 Commit 约定）**

```bash
git add everlink/adapters.py tests/test_adapters.py
git commit -F .commit_msg_origin.txt   # "refactor(adapters): origin from deployer env, not hardcoded SITE_BASE_URL"
```

### Task 1.2: `.env.example` 新增 `<SITE>_PUBLIC_ORIGIN` 段

**Files:**
- Modify: `.env.example:24`（source databases 段之后插入）

- [ ] **Step 1: 在 `HOTDEALS_DATABASE_URL=...`（line 24）之后、`# scripts/export_slots.py ...`（line 26）之前插入**

```
# --- Public origin per first-party site (link absolutization) ---
# Some source databases store INTERNAL links as bare relative paths (e.g.
# /products/...). EverLink absolutizes them against the site's PUBLIC ORIGIN at
# ingestion so probes hit the real store instead of failing the SSRF scheme check.
# Set YOUR OWN domain per site; symmetric with <SITE>_DATABASE_URL above. A site
# whose links are already absolute (e.g. Amazon affiliate URLs) needs no origin.
# NOTHING is hardcoded in the repo — an unset origin leaves relative URLs as-is,
# so a missing config surfaces honestly instead of a fabricated domain.
SANDCART_PUBLIC_ORIGIN=https://your-store.example.com
# AETHELGEM_PUBLIC_ORIGIN=
# HOTDEALS_PUBLIC_ORIGIN=
```

- [ ] **Step 2: 校验模板无语法破坏**

Run: `cd /d d:\qcoder\everlink && python -c "print(open('.env.example',encoding='utf-8').read().count('PUBLIC_ORIGIN'))"`
Expected: 输出 `>=1`（至少 SANDCART 一行未注释 + 两行注释示例含该词）。

- [ ] **Step 3: Commit（节拍）**

```bash
git add .env.example
git commit -F .commit_msg_env.txt   # "docs(env): document per-site <SITE>_PUBLIC_ORIGIN deployer config"
```

### Task 1.3: 全仓确认无残留功能性硬编码

- [ ] **Step 1: grep origin 硬编码**

Run: `cd /d d:\qcoder\everlink && grep -rn "SITE_BASE_URL" everlink/ tests/ scripts/`
Expected: 无任何命中（常量已删）。

- [ ] **Step 2: grep 域名，确认只剩注释/文档/测试 fixture**

Run: `cd /d d:\qcoder\everlink && grep -rn "flashdeals.today" everlink/`
Expected: `everlink/` 生产代码内**无**功能性命中（仅可能出现在 docstring 举例；`tests/` 里的 `_ORIGIN` fixture 与 `data/`、文档不在此路径）。若 `adapters.py` 仍有命中，须为注释示例而非赋值。

---

## Chunk 2: README 顶部重写（P0 · B）

### Task 2.1: 重写开篇为"定位 → 契约 → 双库图"倒金字塔

**Files:**
- Modify: `README.md:1-18`（标题到第一个 `---` 之间）

- [ ] **Step 1: 用下述内容替换 README 的 line 1-16（标题 + tagline + 描述 + hackathon note + Docs 行）**

````markdown
# EverLink

> **一个开源（MIT）、自托管的链接腐烂巡检 agent。** 你 clone 代码、部署到自己的
> 基础设施、填自己的配置，它就每晚自动巡检**你自己站点**的出站链接：坏了自己修，
> 只在需要人判断时把一张决策卡推给你。

**它不是 SaaS。** 没有注册、没有托管、没有月费、没有多租户。它是一段你跑在自己
服务器上的代码。本仓库里出现的 **AethelGem / HotDeals / FlashDeals** 三个站点，只是
**maintainer 作为第一个用户的 dogfooding 示例**——你部署时把它们换成你自己的站点键、
数据库和域名。

<details>
<summary><b>30 秒看懂它做什么</b>（展开）</summary>

EverLink 是一个自主后台 agent：巡检内容/联盟站点的出站链接，探测链接腐烂（商品页
死亡、联盟计划终止、价格/库存漂移、失效引用），*自己决定怎么修*，并**只在真正需要
人判断时**浮出一张紧凑的决策卡。它不是又一个"坏链报告器"——它是一个链接*管家*。

> 为 **AWS "Agents for Humans" Hackathon**（Professional Agents track）而建，使用
> **Strands Agents SDK** + **Amazon Bedrock**。
</details>

## Deploy it — 你需要准备什么（部署者契约）

EverLink 自托管，所以部署时你要提供它无法自带的东西。**代码里不硬编码任何域名、
库地址或密钥**——全部由你通过环境变量或 board 填入：

| # | 你要提供 | 怎么配 | 为什么需要 |
|---|---|---|---|
| 1 | 你自己站点的数据库（**只读**） | env `<SITE>_DATABASE_URL` | 数据源：要巡检的链接从这里读 |
| 2 | 你自己站点的**公开域名** | env `<SITE>_PUBLIC_ORIGIN` | 把站内相对链接 `/products/x` 拼成绝对 URL 再探测 |
| 3 | EverLink 自己的数据库 | env `EVERLINK_DATABASE_URL` | 存巡检过程数据（决策卡 / 审计 / 检查记录） |
| 4 | 一个 LLM | AWS Bedrock 凭证 | Judge / Writer 的判断大脑 |
| 5 | 一个定时器 | Railway cron `0 3 * * *`（或任意） | 每晚自动触发巡检 |

`<SITE>` 是你给自己的站点起的键（示例里是 `AETHELGEM` / `SANDCART` / `HOTDEALS`）。
完整分步 runbook 见 **[`DEPLOYMENT.md`](DEPLOYMENT.md)**；原理图解见 board 的
**`/how-it-works`** 页。

## 两个数据库（这是理解 EverLink 的关键）

```
   ┌─────────────────────────────┐          ┌──────────────────────────────┐
   │  ① 你自己站点的库（数据源）   │          │  ② EverLink 自己的库           │
   │  <SITE>_DATABASE_URL         │          │  EVERLINK_DATABASE_URL         │
   │                              │  只读     │                                │
   │  你的商品/文章/链接           │ ───────► │  link_slots（你链接的镜像）     │
   │                              │ SELECT    │  slot_checks（每次探测结果）    │
   │  EverLink 永不写这里          │  only     │  decisions（待你审批的卡）      │
   │  （db._assert_writable 守卫） │          │  audit_log（每一步的审计）      │
   └─────────────────────────────┘          └──────────────────────────────┘
```

- **① 源库**：你自己的电商/内容站点数据库。EverLink 以 `SET default_transaction_read_only=on`
  **严格只读**接入，从中读出要巡检的链接。**EverLink 永远不写你的源库**——写守卫
  （`db._assert_writable`）会拒绝任何打到源库 host 的写操作。
- **② EverLink 库**：agent 自己的业务过程数据库，存巡检镜像、探测结果、决策卡与审计。
  这是 EverLink 唯一会写的地方。

**Docs:** [`ARCHITECTURE.md`](ARCHITECTURE.md)（图解）· [`DEPLOYMENT.md`](DEPLOYMENT.md)（runbook）·
[`EVALS_REPORT.md`](EVALS_REPORT.md)（eval 证据）· [`CONTRIBUTING.md`](CONTRIBUTING.md)（开发规范）·
[`SUBMISSION_CHECKLIST.md`](SUBMISSION_CHECKLIST.md)（phase gate）。
````

- [ ] **Step 2: 人工核对渲染**

在编辑器 Markdown 预览里确认：`<details>` 折叠正常、契约表 5 行对齐、双库 ASCII 图在代码块内不错位。

- [ ] **Step 3: Commit（节拍）**

```bash
git add README.md
git commit -F .commit_msg_readme.txt   # "docs(readme): lead with open-source/self-hosted positioning + deployer contract + two-DB model"
```

### Task 2.2: 修正正文里把硬编码当正当实现的描述

**Files:**
- Modify: `README.md:288`（Dataset 段的 sandcart bullet）
- Modify: `README.md:372-373`（Scope 段）

- [ ] **Step 1: 替换 line 288 的 origin 描述**

原文含 "The adapter absolutizes them against `https://flashdeals.today` (see `adapters.SITE_BASE_URL`)"，替换为：

```markdown
- `internal` slots (sandcart = **FlashDeals**, an independent dropshipping storefront) are stored in the source DB as relative `/products/...` paths. The adapter absolutizes them against the site's **configured public origin** (`<SITE>_PUBLIC_ORIGIN` env var — the deployer sets their own; nothing is hardcoded in the repo) so probes hit the real storefront instead of failing the SSRF scheme check. FlashDeals' links are internal product pages, **not** Amazon affiliate URLs (only AethelGem and hotdeals carry amazon.{tld}/dp links). `sandcart` is the maintainer's internal example site key — substitute your own when you deploy.
```

- [ ] **Step 2: 在 Scope 段（line 372）确认非 SaaS 表述与新开篇一致**

保留 "Not a commercial product / multi-tenant SaaS / billing."；将 line 373 "sandcart/hotdeals write-back is on the roadmap" 中的 `sandcart` 视需要标注为示例键（不改语义，仅确保读者理解 sandcart=示例）。

- [ ] **Step 3: grep 确认 README 内 `SITE_BASE_URL` 已无残留**

Run: `cd /d d:\qcoder\everlink && grep -n "SITE_BASE_URL" README.md`
Expected: 无命中。

- [ ] **Step 4: Commit（节拍）**

```bash
git add README.md
git commit -F .commit_msg_readme2.txt   # "docs(readme): origin is deployer env config, not a hardcoded base URL"
```

---

## Chunk 3: board `/how-it-works` 页（P0 · B）

### Task 3.1: 新建 `/how-it-works` 静态页（复用 Pipeline / AutomationPanel，不调 DB）

**Files:**
- Create: `board/app/how-it-works/page.tsx`

- [ ] **Step 1: 写页面**（静态 server component；复用现有组件与设计语言；**不含 `force-dynamic`、不调 `getSql()`**，确保无 DB 也能 build/render）

```tsx
import type { Metadata } from "next";
import type { ReactNode } from "react";
import {
  Boxes,
  Database,
  Globe,
  KeyRound,
  Server,
  ShieldCheck,
  Timer,
} from "lucide-react";

import { AutomationPanel } from "@/components/automation-panel";
import { Pipeline } from "@/components/pipeline";

export const metadata: Metadata = {
  title: "EverLink · how it works",
};

/**
 * The product's "start here" page: what EverLink is, the two-database model, and
 * exactly what a deployer must provide. STATIC and READ-ONLY — it never calls
 * getSql(), so it renders (and `next build` passes) with NO database configured.
 * Board twin of the README deployer contract.
 */
export default function HowItWorksPage() {
  return (
    <div className="space-y-8">
      <Positioning />
      <TwoDatabaseModel />
      <DeployerContract />
      <Pipeline />
      <AutomationPanel lastActivity="" />
      <ExampleDeploymentNote />
    </div>
  );
}

/** One-glance positioning: open-source, self-hosted, NOT a SaaS. */
function Positioning() {
  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
        How EverLink works
      </h1>
      <p className="max-w-prose text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
        EverLink is an{" "}
        <span className="font-medium text-zinc-900 dark:text-zinc-100">
          open-source, self-hosted
        </span>{" "}
        agent that patrols the outbound links of <em>your</em> sites every night,
        detects link rot, repairs what it safely can, and surfaces a decision card
        only when a fix needs a human. You clone the code, deploy it on your own
        infrastructure, and fill in your own config.
      </p>
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge icon={<Boxes className="h-3.5 w-3.5" />} label="Open source · MIT" />
        <Badge icon={<Server className="h-3.5 w-3.5" />} label="Self-hosted" />
        <Badge
          icon={<ShieldCheck className="h-3.5 w-3.5" />}
          label="Not a SaaS · no signup, no billing"
        />
      </div>
    </section>
  );
}

function Badge({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-100 px-2.5 py-1 font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
      {icon}
      {label}
    </span>
  );
}

/** The key mental model: your read-only source DB vs EverLink's own DB. */
function TwoDatabaseModel() {
  return (
    <section aria-label="Two-database model" className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Two databases · the key to understanding EverLink
      </h2>
      <div className="grid gap-3 md:grid-cols-2">
        <DbCard
          n="①"
          title="Your site's database (the data source)"
          env="<SITE>_DATABASE_URL"
          tone="readonly"
          lines={[
            "Your products / articles / links live here.",
            "EverLink connects STRICTLY READ-ONLY (default_transaction_read_only=on).",
            "EverLink NEVER writes here — db._assert_writable refuses any source-host write.",
          ]}
        />
        <DbCard
          n="②"
          title="EverLink's own database"
          env="EVERLINK_DATABASE_URL"
          tone="readwrite"
          lines={[
            "link_slots — a mirror of the links it patrols.",
            "slot_checks / decisions / audit_log — the run's own process data.",
            "The ONLY place EverLink writes.",
          ]}
        />
      </div>
    </section>
  );
}

function DbCard({
  n,
  title,
  env,
  lines,
  tone,
}: {
  n: string;
  title: string;
  env: string;
  lines: string[];
  tone: "readonly" | "readwrite";
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center gap-2">
        <Database
          className={
            tone === "readonly"
              ? "h-4 w-4 text-sky-600 dark:text-sky-400"
              : "h-4 w-4 text-emerald-600 dark:text-emerald-400"
          }
        />
        <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          {n} {title}
        </span>
      </div>
      <code className="mt-2 inline-block rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
        {env}
      </code>
      <ul className="mt-2 space-y-1 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        {lines.map((l) => (
          <li key={l}>· {l}</li>
        ))}
      </ul>
    </div>
  );
}

/** What a deployer must provide — board twin of the README contract table. */
function DeployerContract() {
  const items = [
    { icon: <Database className="h-4 w-4" />, what: "Your site's DB (read-only)", how: "env <SITE>_DATABASE_URL", why: "the links to patrol are read from here" },
    { icon: <Globe className="h-4 w-4" />, what: "Your site's public origin", how: "env <SITE>_PUBLIC_ORIGIN", why: "turns relative /products/x into an absolute URL to probe" },
    { icon: <Database className="h-4 w-4" />, what: "EverLink's own DB", how: "env EVERLINK_DATABASE_URL", why: "stores checks, decisions, audit" },
    { icon: <KeyRound className="h-4 w-4" />, what: "An LLM", how: "AWS Bedrock credentials", why: "the Judge / Writer brain" },
    { icon: <Timer className="h-4 w-4" />, what: "A scheduler", how: "Railway cron 0 3 * * *", why: "triggers the nightly patrol" },
  ];
  return (
    <section aria-label="Deployer contract" className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Deploy it · what you provide
      </h2>
      <p className="text-[12px] text-zinc-500 dark:text-zinc-400">
        EverLink hardcodes NO domain, DB address, or secret — you supply all of it.
        Full runbook in{" "}
        <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">DEPLOYMENT.md</code>.
      </p>
      <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {items.map((it, i) => (
          <li
            key={it.what}
            className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-700 dark:text-zinc-300">
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                {it.icon}
              </span>
              {i + 1}. {it.what}
            </div>
            <code className="mt-1.5 block truncate text-[10px] text-sky-700 dark:text-sky-400">
              {it.how}
            </code>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-500 dark:text-zinc-400">
              {it.why}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Honesty note: the three sites here are the maintainer's dogfooding example. */
function ExampleDeploymentNote() {
  return (
    <section className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 text-[12px] leading-relaxed text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-300">
      <strong className="text-zinc-900 dark:text-zinc-100">
        This deployment is an example.
      </strong>{" "}
      The AethelGem / HotDeals / FlashDeals sites in this board are the maintainer's
      own — the first user dogfooding EverLink. Their internal site keys (e.g.{" "}
      <code>sandcart</code> = FlashDeals) stand in for <em>your</em> site keys. When
      you deploy EverLink you point it at your own databases and origins; nothing
      about these example sites is baked into the code.
    </section>
  );
}
```

- [ ] **Step 2: typecheck（会捕获 AutomationPanel 的 prop 契约）**

Run: `cd /d d:\qcoder\everlink\board && npm run typecheck`
Expected: PASS。若报 `AutomationPanel` 的 `lastActivity` 为可选或类型不符，按其真实签名调整（省略该 prop 或传 `""`）——typecheck 是唯一裁决。

- [ ] **Step 3: Commit（节拍）**

```bash
git add board/app/how-it-works/page.tsx
git commit -F .commit_msg_how.txt   # "feat(board): add static /how-it-works page (positioning + two-DB model + deployer contract)"
```

### Task 3.2: nav 加入口

**Files:**
- Modify: `board/components/nav.tsx:5`（import 图标）、`:10-15`（LINKS 数组）

- [ ] **Step 1: import 增图标**

```tsx
import { BarChart3, BookOpen, House, Inbox, ScrollText } from "lucide-react";
```

- [ ] **Step 2: `LINKS` 在 Home 之后插入一项**

```tsx
const LINKS = [
  { href: "/", label: "Home", icon: House, exact: true },
  { href: "/how-it-works", label: "How it works", icon: BookOpen, exact: false },
  { href: "/inbox", label: "Inbox", icon: Inbox, exact: false },
  { href: "/audit", label: "Audit", icon: ScrollText, exact: false },
  { href: "/report", label: "Report", icon: BarChart3, exact: false },
] as const;
```

- [ ] **Step 3: typecheck** — `cd /d d:\qcoder\everlink\board && npm run typecheck`；Expected: PASS。

- [ ] **Step 4: Commit（节拍）** — `git commit -F .commit_msg_nav.txt`（"feat(board): add How it works to nav"）

### Task 3.3: 无 DB 构建 + 人工核验

- [ ] **Step 1: 无 DB 全量构建（关键：静态页不得引入 DB 依赖）**

Run: `cd /d d:\qcoder\everlink\board && npm run build`
Expected: PASS，`/how-it-works` **不因缺 `EVERLINK_DATABASE_URL` 失败**。

- [ ] **Step 2: 本地起服务人工核验**

Run: `cd /d d:\qcoder\everlink\board && npm run dev`；打开 `http://localhost:3000/how-it-works`：确认一屏看懂定位/双库/契约/流水线/cron；nav 高亮正确；明暗主题正常；无 DB 时页面仍完整渲染。

---

## Chunk 4: 文档清理 + sandcart 示例键定位（P1 · E）

### Task 4.1: `DEPLOYMENT.md` 补 origin 配置

**Files:** Modify `DEPLOYMENT.md`（Data provisioning 段 + Env var reference 表）

- [ ] **Step 1: Data provisioning 段补一段 origin 说明**

```markdown
### Public origin per site (`<SITE>_PUBLIC_ORIGIN`)

If a source database stores internal links as bare relative paths (e.g. FlashDeals'
`/products/...`), set that site's public origin so the adapter can absolutize them at
ingestion — otherwise the probe-side SSRF guard rejects a scheme-less URL and the whole
site surfaces as false `needs_human_recheck` cards. Symmetric with `<SITE>_DATABASE_URL`
(e.g. `SANDCART_PUBLIC_ORIGIN=https://your-store.example.com`). Sites whose links are
already absolute need no origin. Nothing is hardcoded: an unset origin leaves relative
URLs untouched rather than guessing a domain.
```

- [ ] **Step 2: Env var reference 表新增一行**

```markdown
| `<SITE>_PUBLIC_ORIGIN` | agent (scan) | Public origin for absolutizing a site's relative internal links; symmetric with `<SITE>_DATABASE_URL`; unset = leave relative URLs as-is |
```

- [ ] **Step 3: Commit（节拍）** — `git commit -F .commit_msg_dep.txt`（"docs(deployment): document <SITE>_PUBLIC_ORIGIN"）

### Task 4.2: `ARCHITECTURE.md` 补示例键说明

**Files:** Modify `ARCHITECTURE.md:54-56`（§1 图注文字，不改 Mermaid 结构）

- [ ] **Step 1: 在 §1 system context 图注补一句**

```markdown
The three source sites (`aethelgem` / `hotdeals` / `sandcart`) are the maintainer's
dogfooding EXAMPLE keys — `sandcart` is the internal codename for the FlashDeals
storefront. A deployer substitutes their own site keys, databases and origins; no site
identity or domain is hardcoded in the agent.
```

- [ ] **Step 2: Commit（节拍）** — `git commit -F .commit_msg_arch.txt`（"docs(architecture): mark the three sites as deployer-substitutable example keys"）

### Task 4.3: `CONTRIBUTING.md` 加 house rule

**Files:** Modify `CONTRIBUTING.md`（house rules 段）

- [ ] **Step 1: 增一条规则**

```markdown
- **No hardcoded origins or domains.** A site's public origin comes only from the
  deployer's `<SITE>_PUBLIC_ORIGIN` env var (see `adapters.resolve_origin`). Never bake
  a domain into the repo — this is an open-source, self-hosted project, so the code must
  work for any deployer's site, not just the maintainer's.
```

- [ ] **Step 2: Commit（节拍）** — `git commit -F .commit_msg_contrib.txt`（"docs(contributing): origins come from deployer env, never hardcoded"）

### Task 4.4: `board/README.md` 提 `/how-it-works`

**Files:** Modify `board/README.md`（页面清单段）

- [ ] **Step 1: 加一行** — `- /how-it-works — static, read-only product primer: open-source/self-hosted positioning, the two-database model, and the deployer contract. Renders with no DB configured.`

- [ ] **Step 2: Commit（节拍）** — `git commit -F .commit_msg_breadme.txt`（"docs(board): list /how-it-works"）

---

## Chunk 5: 诚实数据修复（P1 · F，运维执行，不手工篡改生产库）

> 依赖 Chunk 1 已部署（agent 侧配好 `<SITE>_PUBLIC_ORIGIN`）。全程不手工 `UPDATE` 业务数据；让数据流经正当重摄取携带正确 origin。

### Task 5.1: 配 origin + 正当重摄取

- [ ] **Step 1:** 在 agent 部署环境（Railway）设 `SANDCART_PUBLIC_ORIGIN=https://flashdeals.today`（本地则在 `.env`）。
- [ ] **Step 2: 重导出 CSV（只读 SELECT 源库）** — Run: `cd /d d:\qcoder\everlink && set EVERLINK_FORCE=1 && python scripts/export_slots.py`
- [ ] **Step 3: 重新 scan（以绝对 URL upsert link_slots）** — Run: `cd /d d:\qcoder\everlink && python -m everlink scan --site sandcart --judge none`；Expected: `link_slots.url` 为绝对 `https://flashdeals.today/products/...`，scan 不再整站 `needs_human_recheck`。

### Task 5.2: 退役历史误报卡

- [ ] **Step 1: dry-run** — Run: `cd /d d:\qcoder\everlink && python -m everlink recheck --confirm 2`；Expected: 打印因相对 URL 误判、如今健康的卡；写 nothing。
- [ ] **Step 2: apply（诚实 reject + audit）** — Run: `cd /d d:\qcoder\everlink && python -m everlink recheck --apply --confirm 2`；Expected: 仅退役全健康卡，真实问题卡不动，每次退役写 `audit_log`。

### Task 5.3: 独立连接验证 + 走代理诚实核验

- [ ] **Step 1: 全新独立连接确认持久化**（吸取 psycopg3 事务嵌套"假成功"教训）——独立 `psycopg.connect(EVERLINK_DATABASE_URL)`，`SELECT url FROM link_slots WHERE site='sandcart' LIMIT 5` 确认绝对 URL；确认误报卡已退役。不在同一事务/连接内自证。
- [ ] **Step 2: 走代理核验 board**（原生网络走已配代理，不覆盖）——打开 `https://everlink-seven.vercel.app`：sandcart 槽展示为 **FlashDeals** + 绝对可点 URL；无假 Amazon 链接；`/how-it-works` 正常；误报卡已从 inbox 消失。

---

## Execution Handoff

计划已保存。

**自主确认（owner 已授权自主推进、不参与逐步确认）**：本计划经第一性原理 + 对抗式审核收敛，spec 与 plan 一致、TDD 可执行、边界清晰、守住开源/自托管/非 SaaS 大方向 —— **判定 Ready to execute**。

**执行方式**：harness 具备 subagent → superpowers:subagent-driven-development（每 Task fresh subagent + 两阶段 review）；否则 superpowers:executing-plans 当前会话分批 + checkpoint。

**执行顺序**：Chunk 1（origin，P0 根基）→ Chunk 2（README，P0）→ Chunk 3（board 页，P0）→ Chunk 4（文档，P1）→ Chunk 5（数据修复，P1，依赖上线）。Chunk 1 与 Chunk 3 无依赖可并行。

**Commit 收口**：各 Task commit 为 TDD 节拍标记；按顶部约定，全部 chunk 实现 + 验证通过后统一提交（`-F` 文件消息、原生代理 push），不碎片化。
