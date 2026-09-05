import QtQuick
import QtTest
import "../../qml/UnicodeText.mjs" as UnicodeText

TestCase {
  name: "UnicodeText"
  function test_supplementary_kanji_remains_one_character() {
    compare(UnicodeText.characters("𠮷野"), ["𠮷", "野"])
  }
  function test_limit_keeps_surrogate_pair_and_whitespace() {
    var input = " " + "山".repeat(254) + "𠮷" + "\n"
    var points = UnicodeText.characters(input)
    compare(points.length, 257)
    compare(points.slice(0, 256).join(""), " " + "山".repeat(254) + "𠮷")
    compare(points.join(""), input)
  }
  function test_does_not_normalize_combining_marks_or_line_endings() {
    var input = "か\u3099\r\n\t山󠄀  "
    compare(UnicodeText.characters(input).join(""), input)
    compare(UnicodeText.characters("か\u3099").length, 2)
  }
}
