This isolated Qt test loads the real `Forecast.qml` with fixed theme tokens. It verifies keyboard and accessible-value navigation, pointer preview, responsive layout, and disabled behavior while the page is hidden. It does not replace native Omarchy theme or assistive-technology testing.

Run from the repository root:

```sh
QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME= QT_QUICK_CONTROLS_STYLE=Basic /usr/lib/qt6/bin/qmltestrunner -import tests/forecast_ui -input tests/forecast_ui
```
