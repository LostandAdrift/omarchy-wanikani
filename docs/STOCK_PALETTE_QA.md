# Stock palette qualification

Read-only, offscreen verification on 2026-09-05 covered every installed stock palette in Omarchy 4.0.2-1, with Qt 6.11.2. No desktop theme, lock, plugin lifecycle or account state changed. This is source verification after the frozen 0.2.3 archive; it does not qualify the installed client or constitute a complete WCAG audit.

The 22 palettes were **catppuccin, catppuccin-latte, ethereal, everforest, flexoki-light, gruvbox, hackerman, kanagawa, last-horizon, lumon, lupine, matte-black, miasma, nord, osaka-jade, retro-82, ristretto, rose-pine, solitude, tokyo-night, vantablack and white**. The fixture reads background, foreground, accent and red/urgent from each installed `colors.toml`, retaining its SHA-256 in the local evidence inventory. No stock per-theme `shell.toml` overrides were present.

The [reproducible matrix](../tests/test_stock_palette_surfaces.py) exercises actual Study, SubjectDetails, Listening, KanjiExamples, Progress and dashboard LevelProgress components, with unchanged installed native Button and TextField source. It extracts the installed Style's pure control-token functions and their color utilities; stateful shell theme loaders, IO, media playback and the BorderSurface painter remain inert. Font sizing and spacing are authored fixtures. Run it with:

```sh
python3 -m unittest discover -s tests -p 'test_stock_palette_surfaces.py' -v
```

| Surface | Live change and contrast checks |
|---|---|
| Reviews and guided lessons | Answer draft and caret remain; saved Reading step stays silent. Entered, placeholder and selected text meet 4.5:1 against the composited input/selection surface. |
| Local listening | Saved hidden prompt and revealed answer remain unchanged, with no playback, exposure, rating or reload. Essential text meets 4.5:1. |
| Kanji vocabulary recordings | Disclosed examples remain open and unchanged; changing colors does not fetch or play recordings. Word, reading, meaning and status text meet 4.5:1. |
| Progress and dashboard target | Board data and counts remain unchanged, with no extra reads. Essential text meets 4.5:1; the filled meter meets 3:1 against its remaining track. |
| Shared native controls | Actual focused and focused-selected button text meets 4.5:1 against composited fills; the plugin's explicit focus outline meets 3:1. |

The first matrix found that the level meter adjusted its fill against the card background instead of the adjacent tinted track. Correcting that surface changed Miasma's fill/track contrast from **2.768:1 to 3.009:1**, and Rose Pine's from **2.532:1 to 3.027:1**. The final matrix passed all **88 palette-specific cases plus eight Qt lifecycle outcomes**, across four Python wrappers, without QML warnings. The two additional meter measurements are diagnostic evidence, not extra product test cases.

This checks settled sRGB color relationships, including translucent control fills; it does not measure antialiased pixels, actual screen-reader speech, the native input-border painter, custom user control tokens, full application chrome, monitor calibration, scaling, or physical input/audio. Other synthetic palette and layout fixtures remain separate. Local palette hashes, per-surface logs and before/after meter evidence were retained in `/home/martin/.cache/tmp/wanikani-stock-palette-qa-mn_mbg1e`.
