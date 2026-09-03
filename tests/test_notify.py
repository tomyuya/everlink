"""Offline tests for the push layer (spec §4.1 / §7 — "a notification, not an app").

Everything here runs with NO network and NO DB: message composition is pure, and the
transports are driven by a ``FakeSender`` that records calls instead of POSTing. What
is proven offline:

  * risk-tiered routing (low -> one weekly batch list; medium/high -> immediate card)
  * the composed email/telegram content (subject, counts, board link, tagline)
  * ``NotifyConfig.from_env`` channel-activation logic (all-or-nothing per channel)
  * HONEST delivery states: no credentials -> ``skipped`` (sender never called);
    2xx -> ``sent``; 4xx/5xx -> ``failed``; a raising transport -> ``failed``, no crash
  * the exact Resend/Telegram request shape (URL, Bearer header, body fields)
  * HTML is escaped, so a malicious rationale/URL cannot inject markup

HONESTY: a green suite here means the plumbing + composition are correct — it does
NOT prove a real inbox/Telegram received anything. Live delivery is a separate,
explicitly-labelled smoke run with real credentials (see scripts/ + README), never
part of this offline suite.
"""
import contextlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.model import Decision, Proposal  # noqa: E402
from everlink.notify import (  # noqa: E402
    RESEND_URL,
    TELEGRAM_URL,
    MorningBrief,
    Note,
    NotifyConfig,
    Notifier,
    compose_batch_list,
    compose_decision_card,
    compose_morning_brief,
    route_cards,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _proposal(action="REPLACE_URL", risk="high", rationale="because", **fields) -> Proposal:
    return Proposal(action=action, rationale=rationale, risk_level=risk, **fields)


def _card(id, slots, action="REPLACE_URL", risk="high", **fields) -> Decision:
    return Decision(id=id, affected_slot_ids=list(slots),
                    proposal=_proposal(action=action, risk=risk, **fields))


class FakeSender:
    """Injectable transport double: records (url, headers, body), never hits network."""

    def __init__(self, status=200, text="{}", exc=None):
        self.status, self.text, self.exc = status, text, exc
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, body))
        if self.exc is not None:
            raise self.exc
        return self.status, self.text


@contextlib.contextmanager
def _env(**kv):
    """Temporarily set env vars (value None => delete); restored on exit."""
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _email_cfg(**over) -> NotifyConfig:
    base = dict(resend_api_key="k", resend_from="EverLink <a@b.com>",
                notify_emails=["ops@x.com"], board_url="https://board.test")
    base.update(over)
    return NotifyConfig(**base)


# --------------------------------------------------------------------------- #
# routing (spec §7: low -> weekly batch, medium/high -> immediate single card)
# --------------------------------------------------------------------------- #
def test_route_cards_splits_by_risk():
    lo = _card("d-lo", ["s1"], risk="low")
    med = _card("d-med", ["s2"], risk="medium")
    hi = _card("d-hi", ["s3"], risk="high")
    r = route_cards([lo, med, hi])
    assert [c.id for c in r.batch] == ["d-lo"]
    assert [c.id for c in r.immediate] == ["d-med", "d-hi"]


def test_route_cards_empty():
    r = route_cards([])
    assert r.batch == [] and r.immediate == []


# --------------------------------------------------------------------------- #
# composers — decision card
# --------------------------------------------------------------------------- #
def test_compose_decision_card_content():
    c = _card("dec-1", ["s1", "s2"], action="REPLACE_URL", risk="high",
              new_url="https://amazon.com/dp/X", rationale="re-link to a live equivalent")
    note = compose_decision_card(c, board_url="https://board.test/")
    assert note.subject.startswith("[EverLink]")
    assert "High risk" in note.subject and "Replace URL" in note.subject
    assert "2 slot(s)" in note.subject
    assert "New URL: https://amazon.com/dp/X" in note.text
    assert "re-link to a live equivalent" in note.text
    assert "https://board.test/decision/dec-1" in note.text      # board deep link
    assert "https://board.test/decision/dec-1" in note.html
    assert "Nothing is written back until you approve." in note.html


def test_compose_decision_card_no_board_url_has_no_cta():
    c = _card("dec-2", ["s1"], risk="medium", action="REWRITE_ANCHOR",
              new_anchor="the vendor page")
    note = compose_decision_card(c)                                # board_url=""
    assert "Review :" not in note.text
    assert "New anchor : the vendor page" in note.text
    assert "<a href" not in note.html                              # no link, no button


def test_compose_decision_card_caps_slot_list():
    c = _card("dec-3", [f"s{i}" for i in range(8)], risk="low", action="DROP_BLOCK")
    note = compose_decision_card(c)
    assert "8 — s0, s1, s2, s3, s4 …" in note.text                 # first 5 + ellipsis


# --------------------------------------------------------------------------- #
# composers — batch list
# --------------------------------------------------------------------------- #
def test_compose_batch_list_content():
    cards = [_card("d1", ["s1"], risk="low", action="REWRITE_ANCHOR"),
             _card("d2", ["s2", "s3"], risk="low", action="DROP_BLOCK")]
    note = compose_batch_list(cards, board_url="https://board.test")
    assert "2 low-risk" in note.subject
    assert "d1" in note.text and "d2" in note.text
    assert "Batch-approve in the inbox: https://board.test" in note.text
    assert "https://board.test" in note.html


def test_compose_batch_list_no_url_uses_placeholder():
    note = compose_batch_list([_card("d1", ["s1"], risk="low")])
    assert "(EVERLINK_BOARD_URL not set)" in note.text
    assert "<a href" not in note.html


# --------------------------------------------------------------------------- #
# composers — morning brief (spec §11 demo: "早间报告 … + 邮件推送镜头")
# --------------------------------------------------------------------------- #
def test_compose_morning_brief_full():
    b = MorningBrief(date="2026-09-02", headline="3 links rotted overnight.",
                     slots_scanned=120, problem_slots=41, decisions_pending=9,
                     by_risk={"low": 5, "high": 4},
                     by_action={"REPLACE_URL": 6, "DROP_BLOCK": 3},
                     high_risk_ids=["d1", "d2"])
    note = compose_morning_brief(b, board_url="https://board.test")
    assert "Morning brief" in note.subject and "2026-09-02" in note.subject
    assert "41 link(s) need a decision" in note.subject
    assert "3 links rotted overnight." in note.text
    assert "120 outbound links" in note.text
    assert "41 link slot(s)" in note.text
    assert "Pending cards" in note.text
    assert "High 4" in note.text and "Low 5" in note.text          # by-risk breakdown
    assert "Drop block 3" in note.text and "Replace URL 6" in note.text
    assert "notification, not an app" in note.text                 # the thesis line
    assert "https://board.test" in note.text


def test_compose_morning_brief_minimal_omits_unknowns():
    note = compose_morning_brief(MorningBrief(decisions_pending=0))
    assert "Pending cards" in note.text
    assert "outbound links" not in note.text                       # slots_scanned None
    assert "EverLink patrolled your links overnight." in note.text  # default headline
    assert "Morning brief" in note.subject


# --------------------------------------------------------------------------- #
# config activation (all-or-nothing per channel; from_env parsing)
# --------------------------------------------------------------------------- #
def test_email_enabled_requires_key_from_and_recipient():
    assert NotifyConfig(resend_api_key="k", resend_from="f", notify_emails=["a@b"]).email_enabled
    assert not NotifyConfig(resend_api_key="k", resend_from="f").email_enabled
    assert not NotifyConfig(resend_api_key="k", notify_emails=["a@b"]).email_enabled
    assert not NotifyConfig(resend_from="f", notify_emails=["a@b"]).email_enabled


def test_telegram_enabled_requires_token_and_chat():
    assert NotifyConfig(telegram_token="t", telegram_chat_ids=["1"]).telegram_enabled
    assert not NotifyConfig(telegram_token="t").telegram_enabled
    assert not NotifyConfig(telegram_chat_ids=["1"]).telegram_enabled


def test_config_from_env_parses_and_trims():
    with _env(RESEND_API_KEY="re_key", RESEND_FROM="EverLink <a@b.com>",
              EVERLINK_NOTIFY_EMAIL="ops@x.com, dev@x.com",
              TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_CHAT_ID="-100, -200",
              EVERLINK_BOARD_URL="https://board.test/"):
        cfg = NotifyConfig.from_env()
    assert cfg.email_enabled and cfg.telegram_enabled
    assert cfg.notify_emails == ["ops@x.com", "dev@x.com"]         # csv split + trim
    assert cfg.telegram_chat_ids == ["-100", "-200"]
    assert cfg.board_url == "https://board.test"                   # trailing / stripped


# --------------------------------------------------------------------------- #
# honest delivery states
# --------------------------------------------------------------------------- #
def test_deliver_no_channels_is_skipped_and_sender_unused():
    fake = FakeSender()
    n = Notifier(config=NotifyConfig(), sender=fake)               # nothing configured
    assert n.active_channels() == []
    res = n.deliver(Note(subject="s", text="t"))
    assert len(res) == 1 and res[0].channel == "none" and res[0].status == "skipped"
    assert not res[0].ok
    assert fake.calls == []                                        # never touched network


def test_resend_transport_posts_expected_request():
    fake = FakeSender(status=200, text='{"id":"email_123"}')
    n = Notifier(config=_email_cfg(resend_api_key="re_key"), sender=fake)
    assert n.active_channels() == ["email"]
    res = n.deliver(Note(subject="Subj", text="Body", html="<p>hi</p>"))
    assert res[0].status == "sent" and res[0].ok
    url, headers, body = fake.calls[0]
    assert url == RESEND_URL
    assert headers["Authorization"] == "Bearer re_key"
    assert headers["Content-Type"] == "application/json"
    assert body["from"] == "EverLink <a@b.com>" and body["to"] == ["ops@x.com"]
    assert body["subject"] == "Subj" and body["text"] == "Body" and body["html"] == "<p>hi</p>"


def test_telegram_transport_posts_per_chat_id():
    fake = FakeSender(status=200, text='{"ok":true}')
    cfg = NotifyConfig(telegram_token="123:abc", telegram_chat_ids=["-100", "-200"])
    n = Notifier(config=cfg, sender=fake)
    assert n.active_channels() == ["telegram"]
    res = n.deliver(Note(subject="s", text="hello"))
    assert [r.status for r in res] == ["sent", "sent"]
    assert len(fake.calls) == 2
    url, _headers, body = fake.calls[0]
    assert url == TELEGRAM_URL.format(token="123:abc") and "123:abc" in url
    assert body["chat_id"] == "-100" and body["text"] == "hello"
    assert body["disable_web_page_preview"] is True
    assert fake.calls[1][2]["chat_id"] == "-200"


def test_both_channels_fan_out():
    fake = FakeSender(status=200, text="{}")
    cfg = _email_cfg(telegram_token="t", telegram_chat_ids=["1"])
    n = Notifier(config=cfg, sender=fake)
    assert n.active_channels() == ["email", "telegram"]
    res = n.deliver(Note(subject="s", text="t"))
    assert {r.channel for r in res} == {"email", "telegram"}
    assert all(r.status == "sent" for r in res)


def test_http_error_is_failed_not_sent():
    fake = FakeSender(status=500, text="boom")
    n = Notifier(config=_email_cfg(), sender=fake)
    res = n.deliver(Note(subject="s", text="t"))
    assert res[0].status == "failed" and not res[0].ok
    assert "500" in res[0].detail


def test_transport_exception_is_failed_no_crash():
    fake = FakeSender(exc=RuntimeError("network down"))
    cfg = NotifyConfig(telegram_token="t", telegram_chat_ids=["1"])
    n = Notifier(config=cfg, sender=fake)
    res = n.deliver(Note(subject="s", text="t"))
    assert res[0].status == "failed"
    assert "transport error" in res[0].detail


# --------------------------------------------------------------------------- #
# push_* orchestration
# --------------------------------------------------------------------------- #
def test_push_decision_cards_routes_by_risk():
    fake = FakeSender(status=200, text="{}")
    n = Notifier(config=_email_cfg(), sender=fake)
    cards = [_card("hi", ["s1"], risk="high"), _card("med", ["s2"], risk="medium"),
             _card("lo1", ["s3"], risk="low"), _card("lo2", ["s4"], risk="low")]
    res, route = n.push_decision_cards(cards)
    assert [c.id for c in route.immediate] == ["hi", "med"]
    assert [c.id for c in route.batch] == ["lo1", "lo2"]
    # 2 immediate (one message each) + 1 batch list = 3 deliveries, email-only
    assert len(fake.calls) == 3 and len(res) == 3
    assert all(r.status == "sent" for r in res)
    batch_subject, batch_text = fake.calls[-1][2]["subject"], fake.calls[-1][2]["text"]
    assert "2 low-risk" in batch_subject
    assert "lo1" in batch_text and "lo2" in batch_text             # both rolled up


def test_push_decision_cards_empty_sends_nothing():
    fake = FakeSender(status=200, text="{}")
    n = Notifier(config=_email_cfg(), sender=fake)
    res, route = n.push_decision_cards([])
    assert route.immediate == [] and route.batch == []
    assert res == [] and fake.calls == []


def test_push_morning_brief_delivers_composed_digest():
    fake = FakeSender(status=200, text="{}")
    n = Notifier(config=_email_cfg(), sender=fake)
    res = n.push_morning_brief(MorningBrief(decisions_pending=4, problem_slots=41,
                                            headline="41 links need you."))
    assert res[0].status == "sent"
    body = fake.calls[0][2]
    assert "Morning brief" in body["subject"]
    assert "41 links need you." in body["text"]
    assert "https://board.test" in body["text"]                    # board link present


# --------------------------------------------------------------------------- #
# safety — HTML is escaped (a hostile rationale/URL cannot inject markup)
# --------------------------------------------------------------------------- #
def test_compose_escapes_html():
    c = _card("d1", ["s1"], risk="high", action="REPLACE_URL",
              rationale="<script>alert(1)</script>", new_url="https://x/?a=1&b=2")
    note = compose_decision_card(c, board_url="https://board.test")
    assert "<script>" not in note.html
    assert "&lt;script&gt;" in note.html
    assert "&amp;" in note.html                                    # & in URL escaped


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    failed = 0
    for fn in ALL:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(ALL)-failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
