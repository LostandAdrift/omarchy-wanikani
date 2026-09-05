import QtQuick
import QtTest
import "../../qml/SessionState.mjs" as State

TestCase {
    name: "SessionState"
    function session(revision, phase) {
        return {id: "fixture-session", mode: "reviews", phase: phase || "question",
            revision: revision, subject: {id: 2, level: 2}, draft: "fixture draft"}
    }
    function snapshot(stateRevision, sessionRevision, extra) {
        return Object.assign({demo: false, username: "Fixture learner", max_level: 60,
            state_revision: stateRevision, session_revision: sessionRevision,
            session: session(sessionRevision), paused_graded: false, reviews: 5, pending: 0}, extra || {})
    }
    function test_rpc_answer_prevents_older_full_and_partial_session_rollback() {
        var state = State.full(State.initial(), snapshot(1, 1))
        state = State.reply(state, session(3, "feedback"), state.context)
        compare(state.sessionRevision, 3)
        state = State.full(state, snapshot(2, 2, {reviews: 4}))
        compare(state.snapshot.reviews, 4)
        compare(state.snapshot.session.phase, "feedback")
        compare(state.snapshot.session_revision, 3)
        state = State.partial(state, {session: session(2), session_revision: 2, paused_graded: true})
        compare(state.sessionAccepted, false)
        compare(state.snapshot.session.phase, "feedback")
        compare(state.snapshot.paused_graded, false)
    }
    function test_saved_modes_follow_session_order_and_survive_reply() {
        var saved = {reviews: {id: "review-a", completed: 1}, lessons: {id: "lesson-a", completed: 0}}
        var state = State.full(State.initial(), snapshot(1, 1, {saved_sessions: saved}))
        state = State.reply(state, session(2, "feedback"), state.context)
        compare(state.snapshot.saved_sessions.lessons.id, "lesson-a")
        var updated = {reviews: {id: "review-a", completed: 2}, lessons: saved.lessons}
        state = State.partial(state, {session: session(2), session_revision: 2, saved_sessions: updated})
        compare(state.snapshot.saved_sessions.reviews.completed, 2)
        state = State.full(state, snapshot(2, 1, {saved_sessions: saved}))
        compare(state.snapshot.saved_sessions.reviews.completed, 2)
        state = State.full(state, snapshot(3, 0, {session_epoch: "new-account", saved_sessions: {}}))
        compare(Object.keys(state.snapshot.saved_sessions).length, 0)
    }
    function test_same_revision_partial_finishes_rpc_metadata_without_catalogue_work() {
        var state = State.full(State.initial(), snapshot(1, 1))
        state = State.reply(state, session(2), state.context)
        state = State.partial(state, {session: session(2), session_revision: 2, paused_graded: true})
        compare(state.snapshot.paused_graded, true)
        compare(state.snapshot.reviews, 5)
        compare(state.catalogueAccepted, false)
    }
    function test_late_full_same_session_revision_keeps_newer_counts() {
        var state = State.full(State.initial(), snapshot(2, 5, {reviews: 4, pending: 1}))
        state = State.full(state, snapshot(1, 5, {reviews: 5, pending: 0}))
        compare(state.catalogueAccepted, false)
        compare(state.snapshot.reviews, 4)
        compare(state.snapshot.pending, 1)
        compare(state.stateRevision, 2)
    }
    function test_stale_catalogue_can_supply_a_newer_same_account_session() {
        var state = State.full(State.initial(), snapshot(4, 5, {pending: 2}))
        state = State.full(state, snapshot(3, 6, {pending: 1}))
        compare(state.snapshot.pending, 2)
        compare(state.snapshot.session.revision, 6)
        compare(state.sessionRevision, 6)
    }
    function test_older_full_cannot_revert_account_context() {
        var state = State.full(State.initial(), snapshot(2, 8))
        state = State.full(state, snapshot(3, 1, {demo: true, username: "Demo learner"}))
        state = State.full(state, snapshot(2, 9))
        compare(state.snapshot.demo, true)
        compare(state.snapshot.username, "Demo learner")
        compare(state.snapshot.session_revision, 1)
    }
    function test_context_switch_accepts_lower_revision_but_old_context_rpc_is_not_applied() {
        var state = State.full(State.initial(), snapshot(1, 100))
        var oldContext = state.context
        state = State.full(state, snapshot(2, 1, {demo: true}))
        compare(state.sessionRevision, 1)
        state = State.reply(state, session(101), oldContext)
        compare(state.replyAccepted, false)
        compare(state.sessionRevision, 1)
    }
    function test_grant_change_does_not_reset_session_order_but_hides_restricted_content() {
        var state = State.full(State.initial(), snapshot(1, 5))
        var currentContext = state.context
        state = State.full(state, snapshot(2, 4, {max_level: 1}))
        compare(state.context, currentContext)
        compare(state.sessionRevision, 5)
        compare(state.snapshot.session.subject, null)
        compare(state.snapshot.session.restricted, true)
        compare(state.snapshot.session.draft, "")
    }
    function test_old_equal_revision_cannot_restore_hidden_or_expired_subject() {
        var restricted = session(5)
        restricted.subject = null
        restricted.restricted = true
        var state = State.full(State.initial(), snapshot(3, 5, {max_level: 3, session: restricted}))
        var old = session(5)
        old.subject.level = 50
        state = State.full(state, snapshot(2, 5, {max_level: 60, session: old}))
        compare(state.snapshot.session.subject, null)
        compare(state.snapshot.max_level, 3)
        old.subject.level = 2  // A hidden subject can be within the granted level.
        state = State.full(state, snapshot(1, 5, {session: old}))
        compare(state.snapshot.session.subject, null)
    }
    function test_partial_and_rpc_always_respect_current_grant() {
        var state = State.full(State.initial(), snapshot(1, 5, {max_level: 3}))
        var incoming = session(6)
        incoming.subject.level = 50
        state = State.partial(state, {session: incoming, session_revision: 6})
        compare(state.snapshot.session.subject, null)
        incoming.revision = 7
        state = State.reply(state, incoming, state.context)
        compare(state.snapshot.session.subject, null)
        compare(State.visibleSession(incoming, 3).subject, null)
    }
    function test_newer_catalogue_can_refresh_metadata_at_equal_session_revision() {
        var state = State.full(State.initial(), snapshot(1, 5))
        var hidden = session(5)
        hidden.subject = null
        hidden.unavailable = "This subject is unavailable."
        state = State.full(state, snapshot(2, 5, {session: hidden}))
        compare(state.snapshot.session.subject, null)
        compare(state.snapshot.session.unavailable, "This subject is unavailable.")
    }
    function test_worker_restart_resets_full_sequence_and_preserves_durable_session_order() {
        var state = State.full(State.initial(), snapshot(100, 5))
        state = State.workerRestart(state)
        state = State.full(state, snapshot(1, 4, {reviews: 3}))
        compare(state.stateRevision, 1)
        compare(state.sessionRevision, 5)
        compare(state.snapshot.reviews, 3)
        compare(state.snapshot.session.revision, 5)
    }
    function test_null_session_with_newer_revision_is_an_explicit_clear() {
        var state = State.full(State.initial(), snapshot(1, 5))
        state = State.partial(state, {session: null, session_revision: 6, paused_graded: false})
        compare(state.snapshot.session, null)
        compare(state.sessionRevision, 6)
    }
    function test_explicit_deletion_clears_same_context_session_with_new_epoch() {
        var state = State.full(State.initial(), snapshot(1, 100, {session_epoch: "epoch-a", demo: true}))
        state = State.full(state, snapshot(2, 0, {session_epoch: "epoch-b", demo: true, session: null}))
        compare(state.snapshot.session, null)
        compare(state.sessionRevision, 0)
        compare(state.sessionEpoch, "epoch-b")
        state = State.full(state, snapshot(1, 101, {session_epoch: "epoch-a", demo: true}))
        compare(state.snapshot.session, null)
        compare(state.sessionEpoch, "epoch-b")
    }
    function test_old_epoch_partial_and_reply_cannot_resurrect_deleted_session() {
        var state = State.full(State.initial(), snapshot(2, 0, {session_epoch: "epoch-b", session: null}))
        state = State.partial(state, {session: session(101), session_revision: 101, session_epoch: "epoch-a"})
        compare(state.sessionAccepted, false)
        compare(state.snapshot.session, null)
        var oldReply = Object.assign(session(101), {session_epoch: "epoch-a"})
        state = State.reply(state, oldReply, state.context)
        compare(state.replyAccepted, false)
        compare(state.snapshot.session, null)
    }
    function test_restart_with_same_epoch_retains_durable_revision_order() {
        var state = State.full(State.initial(), snapshot(100, 5, {session_epoch: "epoch-a"}))
        state = State.workerRestart(state)
        state = State.full(state, snapshot(1, 4, {session_epoch: "epoch-a"}))
        compare(state.sessionEpoch, "epoch-a")
        compare(state.sessionRevision, 5)
        compare(state.snapshot.session.revision, 5)
    }
    function test_non_session_payload_is_not_misclassified() {
        compare(State.isSession({saved: true}), false)
        compare(State.isSession({id: 2, meanings: ["mountain"]}), false)
        compare(State.isSession(session(3)), true)
    }
    function test_old_rpc_does_not_overwrite_session_or_change_its_context() {
        var state = State.full(State.initial(), snapshot(1, 5))
        state = State.reply(state, session(4), state.context)
        compare(state.replyAccepted, true)
        compare(state.sessionAccepted, false)
        compare(state.sessionRevision, 5)
    }
    function test_restricted_feedback_is_redacted_without_mutating_saved_presentation() {
        var original = session(9, "feedback")
        original.feedback = {answer: "authored answer", accepted: ["authored alias"],
            kind: "incorrect", correct: false, corrected: false, retry: false}
        original.errors = 1
        var serialized = JSON.stringify(original)
        var result = State.visibleSession(original, 1)
        compare(result.subject, null)
        compare(result.draft, "")
        compare(result.feedback.answer, "")
        compare(result.feedback.accepted.length, 0)
        compare(result.feedback.kind, "incorrect")
        compare(result.errors, 1)
        compare(result.revision, 9)
        compare(JSON.stringify(original), serialized)
        original.restricted = true
        original.subject = null
        compare(State.visibleSession(original, 60).feedback.answer, "")
    }
    function test_invalid_level_and_grant_never_expand_visible_access() {
        var invalid = [null, undefined, true, false, "2", 0, -1, 1.5, 61, {}, [], NaN, Infinity]
        for (var i = 0; i < invalid.length; i++) {
            var original = session(1)
            original.subject.level = invalid[i]
            var result = State.visibleSession(original, 60)
            compare(result.subject, null)
            compare(result.draft, "")
        }
        for (var j = 0; j < invalid.length; j++)
            compare(State.visibleSession(session(1), invalid[j]).subject, null)
        var valid = session(1)
        compare(State.visibleSession(valid, 60), valid)
    }
    function test_fresh_grant_redacts_retained_newer_feedback_on_every_update_path() {
        var newest = session(10, "feedback")
        newest.feedback = {answer: "authored answer", accepted: ["authored alias"], kind: "incorrect"}
        var state = State.full(State.initial(), snapshot(1, 10, {session: newest}))
        state = State.full(state, snapshot(2, 9, {max_level: 1}))
        compare(state.snapshot.session.revision, 10)
        compare(state.snapshot.session.feedback.answer, "")
        newest.revision = 11
        state = State.partial(state, {session: newest, session_revision: 11})
        compare(state.snapshot.session.feedback.accepted.length, 0)
        newest.revision = 12
        state = State.reply(state, newest, state.context)
        compare(state.snapshot.session.feedback.answer, "")
        compare(newest.feedback.answer, "authored answer")
    }
}
