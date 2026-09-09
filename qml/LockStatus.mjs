// Public lock-status reads must never interpret missing or malformed data as unlocked.
export function decode(text, succeeded) {
  if (!succeeded || typeof text !== "string" || text.length > 4096)
    return {known: false, locked: true}
  try {
    const state = JSON.parse(text)
    const fields = ["locked", "requested", "pending", "sessionLocked", "secure"]
    if (!state || fields.some(key => typeof state[key] !== "boolean"))
      return {known: false, locked: true}
    return {known: true, locked: fields.some(key => state[key])}
  } catch (_) {
    return {known: false, locked: true}
  }
}
