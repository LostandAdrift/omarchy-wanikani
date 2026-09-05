import QtQuick
import QtTest
import "../../vendor/WanaKana.mjs" as Kana

TestCase {
  name: "KanaInput"
  function test_conversion_data() {
    return [
      {tag:"small kana",input:"juu",expected:"じゅう"},
      {tag:"doubled consonant",input:"gakkou",expected:"がっこう"},
      {tag:"terminal n",input:"san",expected:"さん"},
      {tag:"apostrophe",input:"kan'i",expected:"かんい"},
      {tag:"long vowel",input:"suupaa",expected:"すうぱあ"},
      {tag:"pasted kana",input:"みず",expected:"みず"},
      {tag:"katakana paste",input:"ページ",expected:"ぺーじ"}
    ]
  }
  function test_conversion(data) { compare(Kana.toHiragana(data.input,{convertLongVowelMark:false}),data.expected) }
  function test_composition_keeps_pending_n() { compare(Kana.toHiragana("san",{IMEMode:true}),"さn") }
  function test_cursor_prefix() { compare(Kana.toHiragana("gak",{IMEMode:true}),"がk") }
}
