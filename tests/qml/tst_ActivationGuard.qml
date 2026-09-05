import QtQuick
import QtTest
import "../../qml" as Kani

Item {
  width: 300
  height: 200
  Item {
    id: button
    property int clicks: 0
    focus: true
    Keys.forwardTo: [guard]
    Keys.onReturnPressed: clicks++
    Keys.onEnterPressed: clicks++
    Keys.onSpacePressed: clicks++
    Kani.ActivationGuard {
      id: guard
    }
  }
  TestCase {
    name: "ActivationGuard"
    when: windowShown
    function test_normal_activation_reaches_native_handler_once() {
      button.forceActiveFocus()
      button.clicks = 0
      keyClick(Qt.Key_Return)
      compare(button.clicks, 1)
      keyClick(Qt.Key_Enter)
      compare(button.clicks, 2)
      keyClick(Qt.Key_Space)
      compare(button.clicks, 3)
    }
    function test_held_activation_is_consumed() {
      for (var key of [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space]) {
        var event = {
          key: key,
          isAutoRepeat: true,
          accepted: false
        }
        guard.filter(event)
        verify(event.accepted)
      }
    }
    function test_editing_and_navigation_are_not_consumed() {
      for (var key of [Qt.Key_A, Qt.Key_Backspace, Qt.Key_Left, Qt.Key_Tab, Qt.Key_Escape]) {
        var event = {
          key: key,
          isAutoRepeat: true,
          accepted: true
        }
        guard.filter(event)
        verify(!event.accepted)
      }
    }
  }
}
