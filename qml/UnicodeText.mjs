// Qt's JavaScript String iterator can expose UTF-16 units even in Array.from.
// Walk code points explicitly so a selection limit never splits a kanji.
export function characters(value) {
  const text = String(value || "")
  const result = []
  for (let index = 0; index < text.length;) {
    const length = text.codePointAt(index) > 0xffff ? 2 : 1
    result.push(text.slice(index, index + length))
    index += length
  }
  return result
}
