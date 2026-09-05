pragma Singleton
import QtQuick

QtObject {
  property int cornerRadius: 4
  property var font: ({
      family: "sans-serif",
      body: 14,
      bodySmall: 12
    })
  function space(n) {
    return n
  }
}
