// Pure sRGB roles. Supply the actual opaque surface beneath text/controls;
// composite(surface, underlay) resolves an explicitly known translucent layer.
// These functions return opaque colors so text opacity cannot lower contrast a
// second time. Keep calls in QML bindings to follow live Omarchy theme changes.
function clamp(value) {
  return Math.max(0, Math.min(1, Number(value) || 0))
}

function rgba(value) {
  if (value && typeof value.r === "number")
    return {r: clamp(value.r), g: clamp(value.g), b: clamp(value.b), a: value.a === undefined ? 1 : clamp(value.a)}
  const text = String(value || "").toLowerCase()
  if (text === "transparent")
    return {r: 0, g: 0, b: 0, a: 0}
  if (/^#[0-9a-f]{3}$/.test(text))
    return rgba("#" + text[1] + text[1] + text[2] + text[2] + text[3] + text[3])
  // QColor's eight-digit notation is #AARRGGBB, not CSS #RRGGBBAA.
  if (/^#[0-9a-f]{6}$/.test(text) || /^#[0-9a-f]{8}$/.test(text)) {
    const offset = text.length === 9 ? 3 : 1
    return {r: parseInt(text.slice(offset, offset + 2), 16) / 255,
      g: parseInt(text.slice(offset + 2, offset + 4), 16) / 255,
      b: parseInt(text.slice(offset + 4, offset + 6), 16) / 255,
      a: offset === 3 ? parseInt(text.slice(1, 3), 16) / 255 : 1}
  }
  // Production callers pass QColor, including named colors. Invalid pure-data
  // fixtures get a deterministic neutral rather than a NaN color/binding error.
  return {r: 0, g: 0, b: 0, a: 1}
}

function hex(color) {
  return "#" + [color.r, color.g, color.b].map(function (channel) {
    return Math.round(clamp(channel) * 255).toString(16).padStart(2, "0")
  }).join("")
}

function over(front, back) {
  return {r: front.r * front.a + back.r * (1 - front.a),
    g: front.g * front.a + back.g * (1 - front.a),
    b: front.b * front.a + back.b * (1 - front.a), a: 1}
}

export function composite(surface, underlay) {
  return hex(over(rgba(surface), rgba(underlay)))
}

function luminance(color) {
  const channels = [color.r, color.g, color.b].map(function (channel) {
    return channel <= 0.04045 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4)
  })
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
}

export function contrast(candidate, surface) {
  const back = rgba(surface)
  const one = luminance(over(rgba(candidate), back))
  const two = luminance(back)
  return (Math.max(one, two) + 0.05) / (Math.min(one, two) + 0.05)
}

function mix(one, two, amount) {
  return {r: one.r + (two.r - one.r) * amount,
    g: one.g + (two.g - one.g) * amount,
    b: one.b + (two.b - one.b) * amount, a: 1}
}

export function readable(candidate, surface, fallback, minimum) {
  const target = Math.max(1, Math.min(21, minimum === undefined ? 4.5 : Number(minimum) || 4.5))
  const back = rgba(surface)
  const source = rgba(candidate)
  const visible = over(source, back)
  const original = hex(visible)
  if (contrast(original, back) >= target)
    return original

  // First recover lost opacity without changing the requested hue. Otherwise
  // move toward the supplied theme foreground, with black/white only as the
  // final mathematical fallback for a custom palette that itself cannot pass.
  const opaque = {r: source.r, g: source.g, b: source.b, a: 1}
  let end = opaque
  if (contrast(end, back) < target) {
    end = over(rgba(fallback), back)
    if (contrast(end, back) < target)
      end = rgba(contrast("#000000", back) > contrast("#ffffff", back) ? "#000000" : "#ffffff")
  }
  if (contrast(end, back) < target)
    return hex(end)
  let low = 0
  let high = 1
  // Include rounding in the predicate: returned 8-bit colors really meet the
  // threshold, rather than only their pre-quantized floating-point values.
  for (let step = 0; step < 16; ++step) {
    const middle = (low + high) / 2
    if (contrast(hex(mix(visible, end, middle)), back) >= target)
      high = middle
    else
      low = middle
  }
  return hex(mix(visible, end, high))
}

export function secondary(foreground, surface) {
  const candidate = rgba(foreground)
  candidate.a *= 0.76
  return readable(candidate, surface, foreground, 4.5)
}

export function indicator(candidate, surface, fallback) {
  return readable(candidate, surface, fallback, 3)
}

export function tint(candidate, surface, opacity) {
  const color = rgba(candidate)
  color.a *= clamp(opacity)
  return composite(color, surface)
}

// Surface containers publish their rendered roles; children follow them across
// nested layouts and Loader boundaries without hard-coding the base palette.
export function surface(item, fallback) {
  while (item) {
    if (item.kaniSurface !== undefined)
      return item.kaniSurface
    item = item.parent
  }
  return fallback
}

export function foreground(item, fallback) {
  while (item) {
    if (item.kaniText !== undefined)
      return item.kaniText
    item = item.parent
  }
  return fallback
}
