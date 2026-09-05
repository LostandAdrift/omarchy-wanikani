// Aggregate-only projection. The caller owns cache lifetime; this module does
// not read the worker, controller, filesystem, account, or current clock.
const DAY = 86400000;
const COUNTERS = {
    subject_completions: ["reviews", "lessons", "practice"],
    sessions_completed: ["reviews", "lessons", "practice"],
    listening_ratings: ["remembered", "again", "skipped"],
    dictation_ratings: ["matched", "again", "skipped"]
};
const SCALARS = ["listening_sessions_completed", "dictation_sessions_completed", "typo_corrections"];

function record(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
}

function owns(value, key) {
    return Object.prototype.hasOwnProperty.call(value, key);
}

function uuid(value) {
    return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
}

function count(value) {
    return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function dateDay(value) {
    if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)) return null;
    const year = Number(value.slice(0, 4));
    const month = Number(value.slice(5, 7));
    const day = Number(value.slice(8, 10));
    if (year < 1 || month < 1 || month > 12 || day < 1 || day > 31) return null;
    // Date.UTC treats years 0..99 as 1900..1999. Set the complete year instead.
    const parsed = new Date(0);
    parsed.setUTCFullYear(year, month - 1, day);
    parsed.setUTCHours(0, 0, 0, 0);
    if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) return null;
    return parsed.getTime();
}

function timestamp(value) {
    if (typeof value !== "string") return null;
    const parts = /^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})$/.exec(value);
    if (!parts) return null;
    const day = dateDay(parts[1]);
    const hour = Number(parts[2]), minute = Number(parts[3]), second = Number(parts[4]);
    if (day === null || hour > 23 || minute > 59 || second > 59) return null;
    const zone = parts[6];
    const zoneHours = zone === "Z" ? 0 : Number(zone.slice(1, 3));
    const zoneMinutes = zone === "Z" ? 0 : Number(zone.slice(4, 6));
    if (zoneHours > 23 || zoneMinutes > 59) return null;
    const offset = (zoneHours * 60 + zoneMinutes) * (zone[0] === "-" ? -1 : 1);
    const fraction = parts[5] || "";
    const instant = day + hour * 3600000 + minute * 60000 + second * 1000
        + Number(fraction.slice(0, 3).padEnd(3, "0")) - offset * 60000;
    const year = new Date(instant).getUTCFullYear();
    // Keep sub-millisecond precision separate from large epoch values. Adding
    // it directly can round a tiny future timestamp down to the current time.
    return Number.isFinite(instant) && year >= 1 && year <= 9999
        ? {millis: instant, fraction: fraction.length > 3 ? Number("0." + fraction.slice(3)) : 0} : null;
}

function timezone(value) {
    return typeof value === "string" && value.length >= 1 && value.length <= 128
        && /^[A-Za-z0-9_+.-]+(?:\/[A-Za-z0-9_+.-]+)*$/.test(value)
        && value.split("/").every(function (part) { return part !== "." && part !== ".."; });
}

function window(value, days, generated) {
    if (!record(value) || !owns(value, "days") || !owns(value, "start_day")
            || !owns(value, "end_day") || value.days !== days) return null;
    const start = dateDay(value.start_day), end = dateDay(value.end_day);
    if (start === null || end === null || end - start !== (days - 1) * DAY) return null;
    // QML has no ZoneInfo database interface. A real local calendar day must
    // be within one UTC day; the CLI additionally verifies the named IANA zone.
    if (Math.abs(end - Math.floor(generated.millis / DAY) * DAY) > DAY) return null;
    const result = {days: days, start_day: value.start_day, end_day: value.end_day};
    for (const metric of Object.keys(COUNTERS)) {
        if (!owns(value, metric) || !record(value[metric])) return null;
        const counters = {};
        for (const name of COUNTERS[metric]) {
            if (!owns(value[metric], name) || !count(value[metric][name])) return null;
            counters[name] = value[metric][name];
        }
        result[metric] = counters;
    }
    for (const metric of SCALARS) {
        if (!owns(value, metric) || !count(value[metric])) return null;
        result[metric] = value[metric];
    }
    return result;
}

function localDay(value) {
    const instant = new Date(value);
    return String(instant.getFullYear()).padStart(4, "0") + "-"
        + String(instant.getMonth() + 1).padStart(2, "0") + "-"
        + String(instant.getDate()).padStart(2, "0");
}

export function project(value, options) {
    try {
        if (!record(value) || !record(options) || options.ready !== true
                || typeof options.demo !== "boolean" || !uuid(options.epoch)
                || typeof options.dirty !== "boolean" || typeof options.clockChanged !== "boolean"
                || typeof options.now !== "number" || !Number.isFinite(options.now)
                || !Number.isFinite(new Date(options.now).getTime())) return null;
        const expected = {schema_version: 1, scope: "recorded_on_this_device", freshness: "cached",
            coverage: "retained_local_records", includes_retained_pre_reset_activity: true};
        if (Object.keys(expected).some(function (key) { return !owns(value, key) || value[key] !== expected[key]; })) return null;
        if (["data_epoch", "demo", "complete", "stale", "timezone", "windows", "generated_at"].some(function (key) { return !owns(value, key); })) return null;
        if (!uuid(value.data_epoch) || value.data_epoch !== options.epoch
                || typeof value.demo !== "boolean" || value.demo !== options.demo
                || typeof value.complete !== "boolean"
                || (value.stale !== null && typeof value.stale !== "boolean")
                || !timezone(value.timezone) || !record(value.windows)
                || !owns(value.windows, "7") || !owns(value.windows, "30")) return null;
        const generated = timestamp(value.generated_at);
        if (generated === null) return null;
        const short = window(value.windows["7"], 7, generated);
        const long = window(value.windows["30"], 30, generated);
        if (!short || !long || short.end_day !== long.end_day) return null;
        for (const metric of Object.keys(COUNTERS)) {
            if (COUNTERS[metric].some(function (name) { return short[metric][name] > long[metric][name]; })) return null;
        }
        if (SCALARS.some(function (metric) { return short[metric] > long[metric]; })) return null;
        return {schema_version: 1, scope: "recorded_on_this_device", freshness: "cached",
            generated_at: value.generated_at, data_epoch: value.data_epoch, demo: value.demo,
            timezone: value.timezone, complete: value.complete,
            stale: value.stale === true || options.dirty || options.clockChanged
                || generated.millis > options.now
                || (generated.millis === Math.floor(options.now) && generated.fraction > options.now - generated.millis)
                || localDay(options.now) !== short.end_day ? true : null,
            coverage: "retained_local_records", includes_retained_pre_reset_activity: true,
            windows: {"7": short, "30": long}};
    } catch (error) {
        // Never echo malformed input or private exception details into status.
        return null;
    }
}
