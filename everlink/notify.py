"""Push layer — surface decision cards + the morning brief (spec §4.1 / §7).

"It surfaces as a notification, not an app." EverLink reaches the operator over
**Resend** (email) and **Telegram** — two channels, one message model.

Design (mirrors ``probes.py``): MESSAGE COMPOSITION is pure and offline-testable
(the ``compose_*`` builders take plain data and return a ``Note`` — no network, no
DB); the TRANSPORTS are thin HTTP calls through an **injectable sender**, so the
offline suite never touches the network and nothing is sent unless credentials are
configured. We call Resend's REST API via ``httpx`` directly (rather than the SDK)
so a transport is exactly one injectable POST and the composers stay pure.

Risk-tiered routing (spec §7): ``low``-risk cards roll up into ONE weekly
batch-approval list; ``medium``/``high``-risk cards are pushed immediately, one
message each, because they need a human now.

HONESTY: if ``RESEND_API_KEY`` / ``TELEGRAM_BOT_TOKEN`` (+ recipient) are unset the
channel is simply INACTIVE and delivery is reported as ``skipped`` — the module
NEVER claims a message was delivered when it was not. ``sent`` is returned only on a
2xx from the real API. Live delivery is verified by a separate smoke (with real
credentials), not by the offline suite.
"""
from __future__ import annotations

import html
import os
from dataclasses import dataclass, field
from datetime import date as _date, datetime as _datetime, timezone
from typing import Callable, Iterable, Optional

import httpx

from .model import Decision

_TIMEOUT = 15.0

ACTION_LABEL = {
    "REPLACE_URL": "Replace URL",
    "REWRITE_ANCHOR": "Rewrite anchor",
    "REWRITE_SENTENCE": "Rewrite sentence",
    "DROP_BLOCK": "Drop block",
    "ESCALATE_HUMAN": "Escalate to human",
}
RISK_LABEL = {"low": "Low", "medium": "Medium", "high": "High"}
RISK_EMOJI = {"low": "\U0001F7E2", "medium": "\U0001F7E0", "high": "\U0001F534"}

RESEND_URL = "https://api.resend.com/emails"
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _split(csv: str) -> list[str]:
    return [p.strip() for p in (csv or "").split(",") if p.strip()]


def _action(a: str) -> str:
    return ACTION_LABEL.get(a, a)


def _risk(r: str) -> str:
    return RISK_LABEL.get(r, r)


# --------------------------------------------------------------------------- #
# message model
# --------------------------------------------------------------------------- #
@dataclass
class Note:
    """One channel-agnostic message: an email subject/text/html + a telegram text.

    ``text`` is the single source of truth for the plaintext email part AND the
    Telegram body, so the two channels never drift apart.
    """

    subject: str
    text: str
    html: str = ""


@dataclass
class MorningBrief:
    """The numbers behind the morning digest. The caller (cli/pe3) fills what it
    knows; composers omit anything left ``None``/empty, so a partial brief is honest
    rather than padded with invented figures."""

    date: str = ""                                   # ISO yyyy-mm-dd; defaults to today
    headline: str = ""
    slots_scanned: Optional[int] = None
    problem_slots: Optional[int] = None              # link slots awaiting a decision
    decisions_pending: int = 0
    by_risk: dict[str, int] = field(default_factory=dict)
    by_action: dict[str, int] = field(default_factory=dict)
    high_risk_ids: list[str] = field(default_factory=list)


@dataclass
class WeeklyReport:
    """The numbers behind the weekly digest — the Python MIRROR of the board's
    ``weeklyStats`` aggregate (board/lib/queries.ts). The agent's scheduled report
    (cli ``report``) and the board's /report page therefore show the SAME numbers
    (single source of truth: one SQL shape, two consumers). Built by
    ``report.build_weekly_report``; anything left 0/empty is reported honestly, not
    padded with invented figures."""

    window_days: int = 7
    generated_at: str = ""                             # ISO; defaults to now
    by_status: dict[str, int] = field(default_factory=dict)
    by_action: dict[str, int] = field(default_factory=dict)
    audit_events: dict[str, int] = field(default_factory=dict)
    links_healed: int = 0                              # decisions applied in the window
    slots_affected_by_applied: int = 0                 # slots those applied cards touched
    decisions_created: int = 0                         # all decisions created in the window
    decisions_decided: int = 0                         # approved+rejected+applied in window

    @property
    def is_empty(self) -> bool:
        """Mirrors the board /report page's 'Nothing to report yet' condition."""
        return (self.decisions_created == 0 and self.links_healed == 0
                and not self.audit_events)


@dataclass
class RouteResult:
    """Output of risk-tiered routing (spec §7)."""

    immediate: list[Decision] = field(default_factory=list)   # medium + high
    batch: list[Decision] = field(default_factory=list)       # low


@dataclass
class DeliveryResult:
    channel: str                                       # email | telegram | none
    status: str                                        # sent | skipped | failed
    detail: str = ""
    recipients: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "sent"


# --------------------------------------------------------------------------- #
# pure composers (offline-testable; no network, no DB)
# --------------------------------------------------------------------------- #
def route_cards(cards: Iterable[Decision]) -> RouteResult:
    """Split cards by risk: low -> weekly batch list, medium/high -> immediate."""
    out = RouteResult()
    for c in cards:
        (out.batch if c.proposal.risk_level == "low" else out.immediate).append(c)
    return out


def _slots_line(ids: list[str], cap: int = 5) -> str:
    head = ", ".join(ids[:cap])
    return head + (" …" if len(ids) > cap else "")


def compose_decision_card(card: Decision, board_url: str = "") -> Note:
    """One medium/high-risk card as an immediate push (spec §7 single-card review)."""
    p = card.proposal
    n = len(card.affected_slot_ids)
    link = f"{board_url.rstrip('/')}/decision/{card.id}" if board_url else ""
    subject = f"[EverLink] {_risk(p.risk_level)} risk · {_action(p.action)} · {n} slot(s)"

    lines = [
        f"{RISK_EMOJI.get(p.risk_level, '')} {_risk(p.risk_level)}-risk fix needs your decision",
        "",
        f"Action : {_action(p.action)} ({p.action})",
        f"Why    : {p.rationale}",
    ]
    if p.new_url:
        lines.append(f"New URL: {p.new_url}")
    if p.new_anchor:
        lines.append(f"New anchor : {p.new_anchor}")
    if p.new_sentence:
        lines.append(f"New sentence: {p.new_sentence}")
    lines.append(f"Slots  : {n} — {_slots_line(card.affected_slot_ids)}")
    lines.append("")
    if link:
        lines.append(f"Review : {link}")
    lines.append("Approve or reject in the board — the fix is applied only after you approve.")
    text = "\n".join(lines)

    rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#71717a;font-size:13px'>{html.escape(k)}</td>"
        f"<td style='padding:4px 0;color:#18181b;font-size:13px'>{html.escape(str(v))}</td></tr>"
        for k, v in [
            ("Action", _action(p.action)),
            ("Risk", _risk(p.risk_level)),
            ("Why", p.rationale),
            *([("New URL", p.new_url)] if p.new_url else []),
            *([("New anchor", p.new_anchor)] if p.new_anchor else []),
            *([("New sentence", p.new_sentence)] if p.new_sentence else []),
            ("Slots", f"{n} — {_slots_line(card.affected_slot_ids)}"),
        ]
    )
    cta = (
        f"<a href='{html.escape(link, quote=True)}' style='background:#0ea5e9;color:#fff;"
        f"text-decoration:none;padding:9px 16px;border-radius:8px;font-size:14px'>Review this fix</a>"
        if link else ""
    )
    body = (
        f"<div style='font-family:ui-sans-serif,system-ui,Arial;max-width:560px;margin:0 auto;"
        f"border:1px solid #e4e4e7;border-radius:12px;padding:20px'>"
        f"<h2 style='margin:0 0 12px;font-size:17px;color:#18181b'>EverLink · {_risk(p.risk_level)}-risk fix</h2>"
        f"<table style='border-collapse:collapse'>{rows}</table>"
        f"<p style='margin:16px 0 0'>{cta}</p>"
        f"<p style='margin:14px 0 0;color:#a1a1aa;font-size:12px'>Nothing is written back until you approve.</p>"
        f"</div>"
    )
    return Note(subject=subject, text=text, html=body)


def compose_batch_list(cards: list[Decision], board_url: str = "") -> Note:
    """The low-risk weekly batch-approval list (spec §7 "batch-approve low-risk")."""
    n = len(cards)
    subject = f"[EverLink] {n} low-risk fix(es) ready for batch approval"
    items = "\n".join(
        f" • {c.id} — {_action(c.proposal.action)} · {len(c.affected_slot_ids)} slot(s)"
        for c in cards
    )
    url = board_url.rstrip("/") if board_url else "(EVERLINK_BOARD_URL not set)"
    text = (
        "\U0001F7E2 These low-risk fixes are safe to approve together:\n\n"
        f"{items}\n\n"
        f"Batch-approve in the inbox: {url}\n"
        "One click approves the lot; open any card to review it first."
    )
    lis = "".join(
        f"<li style='padding:6px 0;border-bottom:1px solid #f4f4f5;font-size:13px;color:#18181b'>"
        f"<code style='color:#71717a'>{html.escape(c.id)}</code> — {html.escape(_action(c.proposal.action))} "
        f"· {len(c.affected_slot_ids)} slot(s)</li>"
        for c in cards
    )
    href = board_url.rstrip("/") if board_url else ""
    cta = (
        f"<a href='{html.escape(href, quote=True)}' style='background:#10b981;color:#fff;text-decoration:none;"
        f"padding:9px 16px;border-radius:8px;font-size:14px'>Open the batch inbox</a>" if href else ""
    )
    body = (
        f"<div style='font-family:ui-sans-serif,system-ui,Arial;max-width:560px;margin:0 auto;"
        f"border:1px solid #e4e4e7;border-radius:12px;padding:20px'>"
        f"<h2 style='margin:0 0 6px;font-size:17px;color:#18181b'>{n} low-risk fixes ready</h2>"
        f"<p style='margin:0 0 12px;color:#71717a;font-size:13px'>Safe to approve together.</p>"
        f"<ul style='margin:0 0 16px;padding:0;list-style:none'>{lis}</ul>"
        f"<p style='margin:0'>{cta}</p></div>"
    )
    return Note(subject=subject, text=text, html=body)


def compose_morning_brief(brief: MorningBrief, board_url: str = "") -> Note:
    """The morning digest (spec §11 demo: "早间报告 … + 邮件推送镜头")."""
    day = brief.date or _date.today().isoformat()
    tail = ""
    if brief.problem_slots:
        tail = f" · {brief.problem_slots} link(s) need a decision"
    subject = f"[EverLink] Morning brief · {day}{tail}"

    lines = [brief.headline or "EverLink patrolled your links overnight."]
    if brief.slots_scanned is not None:
        lines.append(f"Scanned        : {brief.slots_scanned} outbound links")
    if brief.problem_slots is not None:
        lines.append(f"Need a decision: {brief.problem_slots} link slot(s)")
    lines.append(f"Pending cards  : {brief.decisions_pending}")
    if brief.by_risk:
        lines.append("By risk        : " + ", ".join(
            f"{_risk(k)} {v}" for k, v in sorted(brief.by_risk.items())))
    if brief.by_action:
        lines.append("By action      : " + ", ".join(
            f"{_action(k)} {v}" for k, v in sorted(brief.by_action.items())))
    if brief.high_risk_ids:
        lines.append(f"High-risk now  : {_slots_line(brief.high_risk_ids)}")
    lines.append("")
    url = board_url.rstrip("/") if board_url else "(EVERLINK_BOARD_URL not set)"
    lines.append(f"Open the inbox : {url}")
    lines.append('"It surfaces as a notification, not an app."')
    text = "\n".join(lines)

    stat = lambda label, val: (  # noqa: E731 - tiny local renderer
        f"<div style='flex:1;min-width:120px;border:1px solid #e4e4e7;border-radius:10px;padding:12px'>"
        f"<div style='color:#a1a1aa;font-size:12px'>{html.escape(label)}</div>"
        f"<div style='color:#18181b;font-size:20px;font-weight:600'>{html.escape(str(val))}</div></div>"
    )
    stats = "".join([
        stat("Pending cards", brief.decisions_pending),
        *([stat("Scanned", brief.slots_scanned)] if brief.slots_scanned is not None else []),
        *([stat("Need decision", brief.problem_slots)] if brief.problem_slots is not None else []),
    ])
    href = board_url.rstrip("/") if board_url else ""
    cta = (
        f"<a href='{html.escape(href, quote=True)}' style='background:#0ea5e9;color:#fff;text-decoration:none;"
        f"padding:9px 16px;border-radius:8px;font-size:14px'>Open the inbox</a>" if href else ""
    )
    body = (
        f"<div style='font-family:ui-sans-serif,system-ui,Arial;max-width:600px;margin:0 auto;"
        f"border:1px solid #e4e4e7;border-radius:12px;padding:20px'>"
        f"<h2 style='margin:0 0 4px;font-size:18px;color:#18181b'>EverLink morning brief</h2>"
        f"<div style='color:#a1a1aa;font-size:12px;margin-bottom:14px'>{html.escape(day)}</div>"
        f"<p style='margin:0 0 14px;color:#3f3f46;font-size:14px'>{html.escape(brief.headline or 'EverLink patrolled your links overnight.')}</p>"
        f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px'>{stats}</div>"
        f"<p style='margin:0'>{cta}</p>"
        f"<p style='margin:14px 0 0;color:#a1a1aa;font-size:12px'>It surfaces as a notification, not an app.</p>"
        f"</div>"
    )
    return Note(subject=subject, text=text, html=body)


def _sorted_counts(counts: dict[str, int]) -> list[tuple[str, int]]:
    """Counts sorted by value desc, key asc — mirrors the board /report Breakdown order."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def compose_weekly_report(report: WeeklyReport, board_url: str = "") -> Note:
    """The weekly digest (spec §4.1 '... -> 周报'; §4.2 '周报 + changelog + 审计日志').

    Renders the SAME numbers as the board's /report page (``WeeklyReport`` mirrors
    ``weeklyStats``): four headline stats, then the by-status / by-action / audit-event
    breakdowns. An empty window is reported honestly ("Nothing to report yet"), never
    padded with invented activity — the digest and the board are one source of truth.
    """
    day = report.generated_at or _datetime.now(timezone.utc).isoformat(timespec="seconds")
    href = board_url.rstrip("/") if board_url else ""
    link = f"{href}/report" if href else ""
    subject = (f"[EverLink] Weekly report · {report.window_days}d · "
               f"{report.links_healed} link(s) healed")

    if report.is_empty:
        text = (
            f"EverLink weekly report — last {report.window_days} day(s)\n\n"
            "Nothing to report yet: no scans or decisions landed in this window. Once "
            "the nightly patrol runs and the queue sees decisions, this fills in "
            "automatically.\n" + (f"\nFull report : {link}" if link else ""))
        body = (
            f"<div style='font-family:ui-sans-serif,system-ui,Arial;max-width:600px;margin:0 auto;"
            f"border:1px solid #e4e4e7;border-radius:12px;padding:20px'>"
            f"<h2 style='margin:0 0 4px;font-size:18px;color:#18181b'>EverLink weekly report</h2>"
            f"<div style='color:#a1a1aa;font-size:12px;margin-bottom:14px'>{html.escape(day)} · last {report.window_days} day(s)</div>"
            f"<p style='margin:0;color:#3f3f46;font-size:14px'>Nothing to report yet — no scans "
            f"or decisions in this window.</p></div>")
        return Note(subject=subject, text=text, html=body)

    stats = [
        ("Links healed", report.links_healed),
        ("Slots fixed", report.slots_affected_by_applied),
        ("Decisions created", report.decisions_created),
        ("Decisions decided", report.decisions_decided),
    ]
    lines = [f"EverLink weekly report — last {report.window_days} day(s)", ""]
    lines += [f"{label:<18}: {val}" for label, val in stats]
    if report.by_status:
        lines += ["", "By status : " + ", ".join(
            f"{k} {v}" for k, v in _sorted_counts(report.by_status))]
    if report.by_action:
        lines.append("By action : " + ", ".join(
            f"{_action(k)} {v}" for k, v in _sorted_counts(report.by_action)))
    if report.audit_events:
        lines.append("Audit     : " + ", ".join(
            f"{k} {v}" for k, v in _sorted_counts(report.audit_events)))
    lines += ["", f"Full report : {link}" if link else "Full report : (EVERLINK_BOARD_URL not set)",
              '"You approve decisions, not links."']
    text = "\n".join(lines)

    stat_html = "".join(
        f"<div style='flex:1;min-width:120px;border:1px solid #e4e4e7;border-radius:10px;padding:12px'>"
        f"<div style='color:#a1a1aa;font-size:12px'>{html.escape(label)}</div>"
        f"<div style='color:#18181b;font-size:20px;font-weight:600'>{val}</div></div>"
        for label, val in stats)

    def _breakdown(title: str, counts: dict[str, int], labeler=lambda k: k) -> str:
        if not counts:
            return ""
        total = sum(counts.values()) or 1
        rows = "".join(
            f"<div style='display:flex;justify-content:space-between;padding:3px 0;font-size:13px;color:#3f3f46'>"
            f"<span>{html.escape(labeler(k))}</span>"
            f"<span style='color:#71717a'>{v} · {round(v * 100 / total)}%</span></div>"
            for k, v in _sorted_counts(counts))
        return (f"<div style='margin-top:14px'><div style='font-size:13px;font-weight:600;"
                f"color:#18181b;margin-bottom:4px'>{html.escape(title)}</div>{rows}</div>")

    cta = (
        f"<a href='{html.escape(link, quote=True)}' style='background:#0ea5e9;color:#fff;text-decoration:none;"
        f"padding:9px 16px;border-radius:8px;font-size:14px'>Open the full report</a>" if link else "")
    body = (
        f"<div style='font-family:ui-sans-serif,system-ui,Arial;max-width:600px;margin:0 auto;"
        f"border:1px solid #e4e4e7;border-radius:12px;padding:20px'>"
        f"<h2 style='margin:0 0 4px;font-size:18px;color:#18181b'>EverLink weekly report</h2>"
        f"<div style='color:#a1a1aa;font-size:12px;margin-bottom:14px'>{html.escape(day)} · last {report.window_days} day(s)</div>"
        f"<div style='display:flex;gap:10px;flex-wrap:wrap'>{stat_html}</div>"
        f"{_breakdown('Decisions by status', report.by_status)}"
        f"{_breakdown('Decisions by action', report.by_action, _action)}"
        f"{_breakdown('Audit events', report.audit_events)}"
        f"<p style='margin:16px 0 0'>{cta}</p>"
        f"<p style='margin:14px 0 0;color:#a1a1aa;font-size:12px'>You approve decisions, not links.</p>"
        f"</div>")
    return Note(subject=subject, text=text, html=body)


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
@dataclass
class NotifyConfig:
    resend_api_key: str = ""
    resend_from: str = ""
    notify_emails: list[str] = field(default_factory=list)
    telegram_token: str = ""
    telegram_chat_ids: list[str] = field(default_factory=list)
    board_url: str = ""

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key and self.resend_from and self.notify_emails)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_ids)

    @classmethod
    def from_env(cls) -> "NotifyConfig":
        return cls(
            resend_api_key=os.environ.get("RESEND_API_KEY", "").strip(),
            resend_from=os.environ.get("RESEND_FROM", "").strip(),
            notify_emails=_split(os.environ.get("EVERLINK_NOTIFY_EMAIL", "")),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_ids=_split(os.environ.get("TELEGRAM_CHAT_ID", "")),
            board_url=os.environ.get("EVERLINK_BOARD_URL", "").strip().rstrip("/"),
        )


# --------------------------------------------------------------------------- #
# transports (thin HTTP; sender is injectable so tests never hit the network)
# --------------------------------------------------------------------------- #
Sender = Callable[[str, dict, dict], "tuple[int, str]"]


def httpx_sender(url: str, headers: dict, body: dict) -> tuple[int, str]:
    """Default transport: one POST, returning (status_code, response_text)."""
    resp = httpx.post(url, headers=headers, json=body, timeout=_TIMEOUT)
    return resp.status_code, resp.text


class ResendTransport:
    channel = "email"

    def __init__(self, api_key: str, from_addr: str, sender: Sender = httpx_sender):
        self.api_key = api_key
        self.from_addr = from_addr
        self.sender = sender

    def send(self, note: Note, to: list[str]) -> DeliveryResult:
        if not self.api_key or not to:
            return DeliveryResult("email", "skipped", "missing api key or recipients", list(to))
        body: dict = {"from": self.from_addr, "to": list(to), "subject": note.subject, "text": note.text}
        if note.html:
            body["html"] = note.html
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            status, resp = self.sender(RESEND_URL, headers, body)
        except Exception as e:  # network/transport failure is honest, never a crash
            return DeliveryResult("email", "failed", f"transport error: {e}", list(to))
        if 200 <= status < 300:
            return DeliveryResult("email", "sent", f"HTTP {status}", list(to))
        return DeliveryResult("email", "failed", f"HTTP {status}: {resp[:200]}", list(to))


class TelegramTransport:
    channel = "telegram"

    def __init__(self, token: str, sender: Sender = httpx_sender):
        self.token = token
        self.sender = sender

    def send(self, note: Note, chat_ids: list[str]) -> list[DeliveryResult]:
        if not self.token or not chat_ids:
            return [DeliveryResult("telegram", "skipped", "missing token or chat ids", list(chat_ids))]
        url = TELEGRAM_URL.format(token=self.token)
        out: list[DeliveryResult] = []
        for cid in chat_ids:
            body = {"chat_id": cid, "text": note.text, "disable_web_page_preview": True}
            try:
                status, resp = self.sender(url, {"Content-Type": "application/json"}, body)
            except Exception as e:
                out.append(DeliveryResult("telegram", "failed", f"transport error: {e}", [cid]))
                continue
            if 200 <= status < 300:
                out.append(DeliveryResult("telegram", "sent", f"HTTP {status}", [cid]))
            else:
                out.append(DeliveryResult("telegram", "failed", f"HTTP {status}: {resp[:200]}", [cid]))
        return out


# --------------------------------------------------------------------------- #
# notifier (config + composers + transports)
# --------------------------------------------------------------------------- #
class Notifier:
    """Composes and dispatches. Channels with no credentials are simply inactive."""

    def __init__(self, config: Optional[NotifyConfig] = None, sender: Sender = httpx_sender):
        self.config = config or NotifyConfig.from_env()
        self.sender = sender
        self.email = (
            ResendTransport(self.config.resend_api_key, self.config.resend_from, sender)
            if self.config.email_enabled else None
        )
        self.telegram = (
            TelegramTransport(self.config.telegram_token, sender)
            if self.config.telegram_enabled else None
        )

    def active_channels(self) -> list[str]:
        return [c for c, on in (("email", self.email), ("telegram", self.telegram)) if on]

    def deliver(self, note: Note) -> list[DeliveryResult]:
        results: list[DeliveryResult] = []
        if self.email:
            results.append(self.email.send(note, self.config.notify_emails))
        if self.telegram:
            results.extend(self.telegram.send(note, self.config.telegram_chat_ids))
        if not results:
            results.append(DeliveryResult(
                "none", "skipped",
                "no channels configured (set RESEND_API_KEY + RESEND_FROM + EVERLINK_NOTIFY_EMAIL "
                "and/or TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)"))
        return results

    def push_morning_brief(self, brief: MorningBrief) -> list[DeliveryResult]:
        return self.deliver(compose_morning_brief(brief, self.config.board_url))

    def push_weekly_report(self, report: WeeklyReport) -> list[DeliveryResult]:
        return self.deliver(compose_weekly_report(report, self.config.board_url))

    def push_decision_cards(self, cards: Iterable[Decision]) -> tuple[list[DeliveryResult], RouteResult]:
        """Risk-route then push: one message per medium/high card, one batch list for low."""
        cards = list(cards)
        route = route_cards(cards)
        results: list[DeliveryResult] = []
        for c in route.immediate:
            results += self.deliver(compose_decision_card(c, self.config.board_url))
        if route.batch:
            results += self.deliver(compose_batch_list(route.batch, self.config.board_url))
        return results, route
