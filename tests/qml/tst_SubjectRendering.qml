import QtQuick
import QtTest
import "../../qml" as Kani

Rectangle {
  width: 900
  height: 700
  color: "white"
  Kani.JapaneseText {
    id: glyph
    x: 8
    y: 8
    width: 400
    color: "black"
  }
  Kani.RadicalImage {
    id: radical
    x: 600
    y: 300
    width: 140
    height: 140
    subject: ({
        id: 990001,
        slug: "authored secret meaning",
        images: [Qt.resolvedUrl("fixtures/radical.svg")]
      })
  }
  TestCase {
    name: "SubjectRendering"
    when: windowShown
    function init() {
      failOnWarning(/.*/)
      glyph.font.pixelSize = 94
      glyph.minimumPixelSize = 22
      radical.revealLabel = true
      radical.subject = {
        id: 990001,
        slug: "authored secret meaning",
        images: [Qt.resolvedUrl("fixtures/radical.svg")]
      }
    }
    function test_complete_prompt_data() {
      return [
        {
          tag: "large kanji",
          text: "山",
          width: 180,
          maximum: 94
        },
        {
          tag: "long study vocabulary",
          text: "国際交流会へようこそ",
          width: 600,
          maximum: 94
        },
        {
          tag: "narrow prompt",
          text: "日本語のとても長い練習用の言葉",
          width: 180,
          maximum: 94
        },
        {
          tag: "tall prompt grows without clipping",
          text: "日本語のとても長い練習用の言葉".repeat(4),
          width: 180,
          maximum: 94
        },
        {
          tag: "ambient card",
          text: "日本語のとても長い練習用の言葉",
          width: 280,
          maximum: 66
        },
        {
          tag: "zen gallery",
          text: "日本語のとても長い練習用の言葉",
          width: 700,
          maximum: 150
        },
        {
          tag: "supplementary kanji and combining kana",
          text: "𠮷野のか\u3099くせいの長い練習用の言葉",
          width: 180,
          maximum: 94
        }
      ]
    }
    function test_complete_prompt(data) {
      glyph.width = data.width
      glyph.font.pixelSize = data.maximum
      glyph.text = data.text
      verify(waitForRendering(glyph))
      compare(glyph.text, data.text)
      compare(glyph.Accessible.name, data.text)
      verify(!glyph.truncated)
      verify(glyph.contentWidth <= glyph.width + 1)
      verify(glyph.contentHeight <= glyph.height + 1)
      verify(glyph.fontInfo.pixelSize >= glyph.minimumPixelSize)
      verify(glyph.fontInfo.pixelSize <= data.maximum)
      if (data.tag === "large kanji") {
        compare(glyph.fontInfo.pixelSize, 94)
        compare(glyph.lineCount, 1)
      }
      if (data.tag === "narrow prompt")
        verify(glyph.lineCount > 1)
      var image = grabImage(glyph)
      verify(image.width > 0 && image.height > 0)
      var ink = false
      for (var y = 0; y < image.height && !ink; y++) {
        for (var x = 0; x < image.width && !ink; x++)
          ink = image.alpha(x, y) > 0 && image.red(x, y) < 128
      }
      verify(ink, "The complete layout must render visible Japanese glyphs.")
    }
    function test_resize_restores_large_font_without_changing_text() {
      glyph.text = "国際交流会"
      glyph.width = 180
      verify(waitForRendering(glyph))
      var small = glyph.fontInfo.pixelSize
      glyph.width = 700
      verify(waitForRendering(glyph))
      verify(glyph.fontInfo.pixelSize > small)
      compare(glyph.fontInfo.pixelSize, 94)
      compare(glyph.text, "国際交流会")
    }
    function test_combining_and_composed_kana_render_identically() {
      glyph.width = 180
      glyph.text = "がくせい"
      verify(waitForRendering(glyph))
      var composed = grabImage(glyph)
      var height = glyph.height
      glyph.text = "か\u3099くせい"
      verify(waitForRendering(glyph))
      compare(glyph.height, height)
      verify(composed.equals(grabImage(glyph)))
    }
    function test_radical_image_conceals_meaning_until_reveal() {
      var image = findChild(radical, "radicalImage")
      verify(image)
      tryCompare(image, "status", Image.Ready)
      compare(image.fillMode, Image.PreserveAspectFit)
      compare(image.Accessible.name, "Radical authored secret meaning")
      radical.revealLabel = false
      compare(image.Accessible.name, "Radical image, subject 990001")
      verify(image.Accessible.name.indexOf("secret meaning") < 0)
      radical.revealLabel = true
      compare(image.Accessible.name, "Radical authored secret meaning")
    }
    function test_corrupt_radical_uses_alternate_cached_format() {
      ignoreWarning(/.*Error decoding.*corrupt-image.txt.*Unsupported image format/)
      radical.revealLabel = false
      radical.subject = {
        id: 990002,
        slug: "never reveal this meaning",
        images: [Qt.resolvedUrl("fixtures/corrupt-image.txt"), Qt.resolvedUrl("fixtures/radical.svg")]
      }
      tryCompare(radical, "displayReady", true)
      compare(radical.sourceIndex, 1)
      compare(radical.displayLoading, false)
      compare(radical.displayFailed, false)
      var image = findChild(radical, "radicalImage")
      verify(image.asynchronous)
      compare(image.Accessible.name, "Radical image, subject 990002")
      // Updated answer feedback objects must not restart failed alternatives.
      radical.subject = {
        id: 990002,
        slug: "still secret",
        images: [Qt.resolvedUrl("fixtures/corrupt-image.txt"), Qt.resolvedUrl("fixtures/radical.svg")]
      }
      compare(radical.sourceIndex, 1)
      compare(radical.displayReady, true)
    }
    function test_all_formats_fail_without_automatic_retry() {
      ignoreWarning(/.*Cannot open.*missing-radical.svg/)
      ignoreWarning(/.*Error decoding.*corrupt-image.txt.*Unsupported image format/)
      radical.subject = {
        id: 990003,
        images: [Qt.resolvedUrl("fixtures/missing-radical.svg"), Qt.resolvedUrl("fixtures/corrupt-image.txt")]
      }
      tryCompare(radical, "displayFailed", true)
      compare(radical.displayReady, false)
      compare(radical.displayLoading, false)
      compare(radical.sourceIndex, 1)
      wait(30)
      compare(radical.sourceIndex, 1)
      radical.subject = {
        id: 990004,
        images: [Qt.resolvedUrl("fixtures/radical.svg")]
      }
      tryCompare(radical, "displayReady", true)
      compare(radical.sourceIndex, 0)
      compare(radical.displayFailed, false)
    }
    function test_empty_image_list_is_unavailable() {
      radical.subject = {
        id: 990005,
        images: []
      }
      compare(radical.displayReady, false)
      compare(radical.displayLoading, false)
      compare(radical.displayFailed, true)
      radical.subject = {
        id: 990006
      }
      compare(radical.displayFailed, true)
      radical.subject = null
      compare(radical.displayReady, false)
    }
  }
}
