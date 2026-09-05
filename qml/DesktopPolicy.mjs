// Pure desktop policy shared by the shell service and fixture-only Qt tests.
export function notification(previousDue, due, nowEpoch, localHour, settings, flags) {
    settings = settings || {};
    flags = flags || {};
    const result = {notify: false, previousDue: due};
    // Consume every observation, including suppressed increases. This prevents
    // unlocking, leaving study, or ending quiet hours from replaying a backlog.
    if (previousDue < 0 || due <= previousDue || settings.notifications === false
            || flags.demo || flags.locked || flags.dnd || flags.studying || flags.vacation)
        return result;

    const start = settings.quiet_start === undefined ? 22 : settings.quiet_start;
    const end = settings.quiet_end === undefined ? 8 : settings.quiet_end;
    const quiet = start === end ? false : start > end
        ? localHour >= start || localHour < end
        : localHour >= start && localHour < end;
    if (quiet || nowEpoch < Number(settings.snooze_until || 0)
            || nowEpoch - Number(settings.last_notification_at || 0)
                < Number(settings.reminder_interval || 7200))
        return result;

    result.notify = true;
    return result;
}

export function idleWindow(deadline) {
    deadline = Number(deadline);
    return {start: 60, end: deadline - 2, enabled: Number.isFinite(deadline) && deadline > 65};
}

export function ambientAllowed(flags) {
    flags = flags || {};
    return !(flags.locked || flags.fullscreen || flags.studying || flags.panelOpen);
}
