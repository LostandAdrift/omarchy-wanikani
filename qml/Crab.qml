import QtQuick
import qs.Commons

// Original vector artwork. Redraw only on palette/blink changes; no idle render loop.
Item {
  id: crab
  implicitWidth: 72
  implicitHeight: 58
  property color ink: Color.foreground
  property color shellColor: Color.accent
  property bool animate: false
  property bool blink: false
  property bool celebrating: false
  onInkChanged: drawing.requestPaint()
  onShellColorChanged: drawing.requestPaint()
  onBlinkChanged: drawing.requestPaint()
  Accessible.role: Accessible.Graphic
  Accessible.name: "Your study crab"
  Canvas {
    id: drawing
    anchors.fill: parent
    onPaint: {
      var c = getContext("2d")
      c.reset(); c.scale(width / 100, height / 80)
      c.lineCap = "round"; c.lineJoin = "round"; c.strokeStyle = crab.ink; c.lineWidth = 3
      for (var side = -1; side <= 1; side += 2) {
        for (var j = 0; j < 3; j++) {
          c.beginPath(); c.moveTo(50 + side * 25, 48 + j * 5)
          c.lineTo(50 + side * (36 + j * 3), 53 + j * 6); c.stroke()
        }
        c.beginPath(); c.moveTo(50 + side * 24, 44); c.lineTo(50 + side * 37, 32); c.stroke()
        c.fillStyle = crab.shellColor; c.beginPath()
        c.arc(50 + side * 38, 24, 10, 0.35, 5.5); c.lineTo(50 + side * 38, 24); c.closePath(); c.fill(); c.stroke()
      }
      c.fillStyle = crab.shellColor; c.beginPath()
      c.moveTo(23, 45); c.bezierCurveTo(23, 25, 77, 25, 77, 45)
      c.bezierCurveTo(80, 67, 20, 67, 23, 45); c.fill(); c.stroke()
      c.fillStyle = crab.ink
      for (var x = 39; x <= 61; x += 22) {
        c.beginPath(); c.moveTo(x, 34); c.lineTo(x, 23); c.stroke()
        c.beginPath()
        if (crab.blink) { c.moveTo(x - 3, 22); c.lineTo(x + 3, 22); c.stroke() }
        else { c.arc(x, 22, 3, 0, Math.PI * 2); c.fill() }
      }
      c.beginPath(); c.moveTo(43, 49); c.quadraticCurveTo(50, 55, 57, 49); c.stroke()
    }
  }
  Timer { interval: 6700; repeat: true; running: crab.animate && crab.visible; onTriggered: { crab.blink = true; blinkEnd.restart() } }
  Timer { id: blinkEnd; interval: 120; onTriggered: crab.blink = false }
  SequentialAnimation on rotation {
    running: crab.celebrating && crab.animate && crab.visible
    NumberAnimation { to: -9; duration: 140 }
    NumberAnimation { to: 9; duration: 220 }
    NumberAnimation { to: 0; duration: 140 }
  }
}
