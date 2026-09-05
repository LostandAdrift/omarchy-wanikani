import QtQuick

Item {
  id: root
  // Forward here before a native button's specific Enter/Space handler.
  // One held key must never check an answer and acknowledge its feedback.
  function filter(event) {
    event.accepted = event.isAutoRepeat && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
  }
  Keys.onPressed: function (event) {
    root.filter(event)
  }
}
