"""One-time celebrations of server-confirmed account levels, never local SRS.

Only Synchronizer.run calls observe after account/reset/outbox reconciliation
completes. First observation establishes a baseline. Marker, history, and
pending display commit together; acknowledgements retain that history.
"""
import uuid

from .api import ApiError, validate_user
from .common import UserError, epoch, stamp


SOURCE = "WaniKani account"
FIELDS = ("id", "level", "confirmed_at", "source")


def _identity(user):
    try:
        validate_user(user)
    except ApiError:
        return None
    account = user["id"]
    if not ((isinstance(account, str) and account.strip()) or (type(account) is int and account > 0)):
        return None
    if not isinstance(user["data"].get("username"), str) or not user["data"]["username"].strip():
        return None
    return account, user["data"]["level"]


def _generation(store):
    value = store.get("milestone_reset_generation", 0)
    return value if type(value) is int and value >= 0 else 0


def observe(engine):
    """Record a completed normal synchronization's account observation."""
    if engine.demo:
        return None
    store = engine.store
    with store.transaction():
        identity = _identity(store.get("user"))
        if identity is None or identity[0] != store.get("account_id"):
            return None
        account, level = identity
        generation = _generation(store)
        old = store.get("milestone_observation")
        same = isinstance(old, dict) and old.get("account_id") == account
        old_level = old.get("level") if same else None
        known = same and type(old_level) is int and 1 <= old_level <= 60
        awarded = old.get("awarded_levels", []) if same else []
        awarded = {value for value in awarded if type(value) is int and 1 <= value <= 60} if isinstance(awarded, list) else set()
        reset = not same or old.get("reset_generation") != generation
        if not known or reset or level < old_level:
            store.set("pending_milestone", None)
        milestone = None
        if known and not reset and level > old_level and level not in awarded:
            milestone = {"id": str(uuid.uuid4()), "level": level, "confirmed_at": stamp(engine.now()), "source": SOURCE}
            internal = {**milestone, "account_id": account, "reset_generation": generation}
            store.event(None, None, "account_milestone", milestone["confirmed_at"], internal)
            store.set("pending_milestone", internal)
            awarded.add(level)
        store.set("milestone_observation", {"account_id": account, "level": level,
            "reset_generation": generation, "awarded_levels": sorted(awarded)})
        return milestone


def invalidate_reset(engine):
    """Call inside reset invalidation; a failed later sync must stay suppressed."""
    with engine.store.transaction():
        engine.store.set("milestone_reset_generation", _generation(engine.store) + 1)
        engine.store.set("pending_milestone", None)


def latest(engine):
    """Return only the current account's safe public display fields."""
    if engine.demo:
        return None
    identity = _identity(engine.store.get("user"))
    pending = engine.store.get("pending_milestone")
    if identity is None or not isinstance(pending, dict):
        return None
    if (pending.get("account_id") != identity[0] or identity[0] != engine.store.get("account_id")
            or pending.get("level") != identity[1] or type(pending.get("level")) is not int
            or pending.get("reset_generation") != _generation(engine.store)
            or not isinstance(pending.get("id"), str) or not pending["id"]
            or pending.get("source") != SOURCE or epoch(pending.get("confirmed_at")) is None):
        return None
    return {field: pending[field] for field in FIELDS}


def acknowledge(engine, milestone_id):
    if not isinstance(milestone_id, str) or not milestone_id or len(milestone_id) > 160:
        raise UserError("Choose the milestone to acknowledge.")
    with engine.store.transaction():
        pending = engine.store.get("pending_milestone")
        matched = isinstance(pending, dict) and pending.get("id") == milestone_id
        if matched:
            when = stamp(engine.now())
            engine.store.event(None, None, "milestone_ack", when, {"id": milestone_id, "acknowledged_at": when})
            engine.store.set("pending_milestone", None)
        return {"id": milestone_id, "acknowledged": matched}
