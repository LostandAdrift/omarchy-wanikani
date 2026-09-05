// Names describe cached confirmed assignment stages, never a predicted result.
export function stageName(stage) {
  const names = ["", "Apprentice 1", "Apprentice 2", "Apprentice 3", "Apprentice 4", "Guru 1", "Guru 2", "Master", "Enlightened", "Burned"]
  return Number.isInteger(stage) && stage >= 1 && stage <= 9 ? names[stage] : ""
}

export function label(status) {
  if (!status || typeof status !== "object" || Array.isArray(status)
      || typeof status.pending !== "boolean" || typeof status.attention !== "boolean")
    return "Progress unavailable"
  const groups = ["", "apprentice", "apprentice", "apprentice", "apprentice", "guru", "guru", "master", "enlightened", "burned"]
  const name = stageName(status.stage)
  const confirmed = name && status.group === groups[status.stage] ? "Confirmed " + name
    : status.group === "burned" && Number.isInteger(status.stage) && status.stage >= 0 && status.stage <= 9 ? "Confirmed Burned"
    : status.group === "lessons" && Number.isInteger(status.stage) && status.stage >= 0 && status.stage <= 9 ? "Lesson ready · not started"
    : status.group === "locked" && (status.stage === null || Number.isInteger(status.stage) && status.stage >= 0 && status.stage <= 9) ? "Not started"
    : "Progress unavailable"
  if (status.attention === true)
    return "Needs attention · " + confirmed.charAt(0).toLowerCase() + confirmed.slice(1)
  if (status.pending === true)
    return "Waiting to sync · " + confirmed.charAt(0).toLowerCase() + confirmed.slice(1)
  return confirmed
}
