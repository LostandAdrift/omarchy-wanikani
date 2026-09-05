// The backend supplies 24 rolling hourly bins, excluding reviews already due.
// This presentation helper never computes or changes a WaniKani assignment.
export function bins(input) {
    return Array.from({length: 24}, (_, index) => {
        const value = Array.isArray(input) ? input[index] : 0;
        return Number.isSafeInteger(value) && value >= 0 ? value : 0;
    });
}

export function hour(value) {
    return Number.isFinite(value) ? Math.max(0, Math.min(23, Math.floor(value))) : 0;
}

export function first(input) {
    const index = bins(input).findIndex(value => value > 0);
    return index < 0 ? 0 : index;
}

export function move(selected, action) {
    if (action === "first") return 0;
    if (action === "last") return 23;
    if (action === "next") return hour(hour(selected) + 1);
    if (action === "previous") return hour(hour(selected) - 1);
    return hour(selected);
}

export function summary(input, selected, now) {
    const values = bins(input);
    const index = hour(selected);
    const validTime = typeof now === "number" && Number.isFinite(now)
        && Number.isFinite(new Date((now + 86400) * 1000).getTime());
    return {hour: index, count: values[index], cumulative: values.slice(0, index + 1).reduce((a, b) => a + b, 0),
        total: values.reduce((a, b) => a + b, 0), peak: Math.max(1, ...values),
        start: validTime ? (now + index * 3600) * 1000 : null,
        end: validTime ? (now + (index + 1) * 3600) * 1000 : null};
}
