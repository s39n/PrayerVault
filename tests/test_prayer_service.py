"""The 'request prayer from the elders' journey, end to end + guardrails."""
import pytest

from app import db, models, orgs, prayer_service as ps
from app.prayer_service import PermissionDenied, PrayerError


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.init_db()


def _add_user(org_id, role, email):
    with db.session_scope() as s:
        u = models.User(org_id=org_id, email=email, display_name=email.split("@")[0])
        s.add(u)
        s.flush()
        s.add(models.Membership(org_id=org_id, user_id=u.id, role=role))
        s.flush()
        return u.id


def _church(slugbase):
    r = orgs.create_church(f"{slugbase} Church", f"admin@{slugbase}.org", auto_active=True)
    org = r["org_id"]
    return {
        "org": org,
        "admin": r["user_id"],
        "elder": _add_user(org, "elder", f"elder@{slugbase}.org"),
        "elder2": _add_user(org, "elder", f"elder2@{slugbase}.org"),
        "member": _add_user(org, "member", f"member@{slugbase}.org"),
        "other": _add_user(org, "member", f"other@{slugbase}.org"),
    }


def test_full_elder_request_lifecycle():
    c = _church("grace")
    pid = ps.create_elder_request(c["org"], c["member"], "Job interview",
                                  "Pray for John's interview Thursday", subject_name="John")

    # Shows up unclaimed in the elder queue
    queue = ps.elder_queue(c["org"], c["elder"])
    assert [p["id"] for p in queue] == [pid]
    assert queue[0]["owner_id"] is None and queue[0]["subject_name"] == "John"

    # Elder claims it
    ps.claim(c["org"], pid, c["elder"])
    assert ps.elder_queue(c["org"], c["elder"]) == []          # no longer unclaimed
    flock = ps.my_flock(c["org"], c["elder"])
    assert [p["id"] for p in flock] == [pid] and flock[0]["owner_id"] == c["elder"]

    # The requesting member (a subscriber) adds an update
    ps.add_update(c["org"], pid, c["member"], "Interview moved to Friday")
    # Elder marks it answered
    ps.set_status(c["org"], pid, c["elder"], answered=True, text="He got the job!")

    tl = ps.timeline(c["org"], pid, c["member"])
    kinds = [u["kind"] for u in tl]
    assert kinds == ["created", "update", "update", "answered"]
    assert "He got the job!" in tl[-1]["text"]
    assert ps.my_flock(c["org"], c["elder"])[0]["status"] == "answered"


def test_only_members_can_request_and_only_elders_see_queue():
    c = _church("hope")
    stranger = _add_user(_church("zion")["org"], "member", "x@zion2.org")  # other church
    # A member of another church cannot create here
    with pytest.raises(PermissionDenied):
        ps.create_elder_request(c["org"], stranger, "x", "y")
    pid = ps.create_elder_request(c["org"], c["member"], "Need", "body")
    # A plain member cannot view the elder queue
    with pytest.raises(PermissionDenied):
        ps.elder_queue(c["org"], c["member"])
    # A plain member cannot claim
    with pytest.raises(PermissionDenied):
        ps.claim(c["org"], pid, c["member"])


def test_non_subscriber_cannot_update_and_non_owner_cannot_answer():
    c = _church("trinity")
    pid = ps.create_elder_request(c["org"], c["member"], "Need", "body")
    ps.claim(c["org"], pid, c["elder"])
    # 'other' is a member but not following -> cannot add an update
    with pytest.raises(PermissionDenied):
        ps.add_update(c["org"], pid, c["other"], "butting in")
    # 'other' cannot change status either
    with pytest.raises(PermissionDenied):
        ps.set_status(c["org"], pid, c["other"], answered=True)


def test_pastoral_notes_are_elder_only_and_never_in_timeline():
    c = _church("bethel")
    pid = ps.create_elder_request(c["org"], c["member"], "Marriage", "private struggle")
    ps.claim(c["org"], pid, c["elder"])
    ps.add_pastoral_note(c["org"], pid, c["elder"], "Called Tuesday; following up next week")

    # Elder can read it
    notes = ps.pastoral_notes(c["org"], pid, c["elder"])
    assert len(notes) == 1 and "Called Tuesday" in notes[0]["text"]
    # The member cannot
    with pytest.raises(PermissionDenied):
        ps.pastoral_notes(c["org"], pid, c["member"])
    # And it never leaks into the member-visible timeline
    tl_text = " ".join(u["text"] for u in ps.timeline(c["org"], pid, c["member"]))
    assert "Called Tuesday" not in tl_text


def test_follow_up_list_respects_the_window():
    c = _church("shiloh")
    pid = ps.create_elder_request(c["org"], c["member"], "Ongoing", "body")
    ps.claim(c["org"], pid, c["elder"])
    # Just created/claimed: not overdue on a 7-day window
    assert ps.follow_up_list(c["org"], c["elder"], days=7) == []
    # With a zero-day window everything counts as needing follow-up
    overdue = ps.follow_up_list(c["org"], c["elder"], days=0)
    assert [p["id"] for p in overdue] == [pid]


def test_assign_hands_off_to_another_elder():
    c = _church("emmanuel")
    pid = ps.create_elder_request(c["org"], c["member"], "Need", "body")
    ps.claim(c["org"], pid, c["elder"])
    ps.assign(c["org"], pid, c["elder"], c["elder2"])
    assert ps.my_flock(c["org"], c["elder2"])[0]["id"] == pid
    # Cannot assign to a non-elder
    with pytest.raises(PrayerError):
        ps.assign(c["org"], pid, c["elder2"], c["member"])


def test_prayer_is_invisible_across_churches():
    a = _church("cornerstone")
    b = _church("redeemer")
    pid = ps.create_elder_request(a["org"], a["member"], "A need", "body")
    # An elder in church B cannot claim or update church A's prayer
    with pytest.raises(PrayerError):
        ps.claim(b["org"], pid, b["elder"])
    with pytest.raises(PrayerError):
        ps.add_update(b["org"], pid, b["elder"], "sneaky")
