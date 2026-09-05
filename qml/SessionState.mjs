// Ordering only; this module performs no I/O and is shared by Qt regression tests.
export function initial(snapshot) {
    return {snapshot: snapshot || {}, context: null, sessionEpoch: null, stateRevision: -1, sessionRevision: -1};
}

export function context(snapshot) {
    return JSON.stringify([snapshot.demo === true, snapshot.username || ""]);
}

function revision(value) {
    return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

function epoch(value) {
    return typeof value === "string" ? value : "";
}

function sessionFields(snapshot) {
    return {session: snapshot.session || null, paused_graded: snapshot.paused_graded === true,
        saved_sessions: snapshot.saved_sessions || {},
        session_revision: revision(snapshot.session_revision), session_epoch: epoch(snapshot.session_epoch)};
}

export function visibleSession(session, maximum) {
    if (!session) return session;
    const grant = Number.isInteger(maximum) && maximum >= 0 && maximum <= 60 ? maximum : 0;
    const level = session.subject && session.subject.level;
    if (session.restricted === true || (session.subject && (!Number.isInteger(level) || level < 1 || level > grant))) {
        const result = Object.assign({}, session, {subject: null, restricted: true, draft: ""});
        if (session.feedback && typeof session.feedback === "object")
            result.feedback = Object.assign({}, session.feedback, {accepted: [], answer: ""});
        return result;
    }
    return session;
}

function mergeSession(state, incoming) {
    const incomingRevision = revision(incoming.session_revision);
    if (incomingRevision < state.sessionRevision)
        return Object.assign({}, state, {sessionAccepted: false});
    const fields = sessionFields(incoming);
    fields.session = visibleSession(fields.session, state.snapshot.max_level);
    return Object.assign({}, state, {
        snapshot: Object.assign({}, state.snapshot, fields),
        sessionRevision: incomingRevision, sessionAccepted: true
    });
}

export function full(state, incoming) {
    const nextContext = context(incoming);
    const nextEpoch = epoch(incoming.session_epoch);
    const nextRevision = revision(incoming.state_revision);
    const catalogueAccepted = nextRevision >= state.stateRevision;
    if (!catalogueAccepted) {
        // A slow older snapshot may contain a newer session read. Accept that
        // separately, but never revert account context or catalogue counters.
        const result = nextContext === state.context && nextEpoch === epoch(state.sessionEpoch)
            && revision(incoming.session_revision) > state.sessionRevision
            ? mergeSession(state, incoming) : Object.assign({}, state, {sessionAccepted: false});
        return Object.assign({}, result, {catalogueAccepted: false});
    }
    const changedDomain = state.context !== nextContext || epoch(state.sessionEpoch) !== nextEpoch;
    const previous = changedDomain ? {} : sessionFields(state.snapshot);
    let next = Object.assign({}, state, {
        snapshot: Object.assign({}, incoming, previous), context: nextContext, sessionEpoch: nextEpoch,
        stateRevision: nextRevision, sessionRevision: changedDomain ? -1 : state.sessionRevision
    });
    next = mergeSession(next, incoming);
    // A fresher access grant can restrict a retained newer session as well.
    next.snapshot = Object.assign({}, next.snapshot, {
        session: visibleSession(next.snapshot.session, incoming.max_level)
    });
    return Object.assign({}, next, {catalogueAccepted: true});
}

export function partial(state, incoming) {
    if (epoch(incoming.session_epoch) !== epoch(state.sessionEpoch))
        return Object.assign({}, state, {sessionAccepted: false, catalogueAccepted: false});
    return Object.assign({}, mergeSession(state, incoming), {catalogueAccepted: false});
}

export function isSession(value) {
    return value && typeof value === "object" && typeof value.id === "string"
        && typeof value.mode === "string" && typeof value.phase === "string"
        && typeof value.revision === "number" && Number.isSafeInteger(value.revision) && value.revision >= 0;
}

export function reply(state, incoming, issuedContext) {
    if ((issuedContext !== null && state.context !== null && issuedContext !== state.context)
            || epoch(incoming.session_epoch) !== epoch(state.sessionEpoch))
        return Object.assign({}, state, {replyAccepted: false});
    const result = mergeSession(state, {session: incoming,
        paused_graded: state.snapshot.paused_graded, saved_sessions: state.snapshot.saved_sessions, session_revision: incoming.revision,
        session_epoch: epoch(incoming.session_epoch)});
    return Object.assign({}, result, {replyAccepted: true, catalogueAccepted: false});
}

export function workerRestart(state) {
    // Full-state sequence numbers belong to the worker process. Session
    // revisions are durable and remain authoritative across its restart.
    return Object.assign({}, state, {stateRevision: -1});
}
