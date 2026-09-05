"""Actual Qt decoder/end signals; generated tone and mock RPC, no human-hearing claim."""
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")
QML = r'''
import QtQuick
import QtTest
import QtMultimedia
Item {
  QtObject {
    id: owner
    property var service: backend
    property bool opened: false
    property string view: "dictation"
    property string contentAccess: "authored-only"
    property int navigationSequence: 0
    property var snapshot: ({})
    property int audioSequence: 0
    property string audioContext: ""
    property string audioState: ""
    property string audioNotice: ""
    function stopAudio() { core.cancelAudio(); audioSequence++; player.stop(); audioContext="" }
  }
  QtObject {
    id: backend
    property bool ready: true
    property bool locked: false
    property int completions: 0
    property int clips: 0
    property var session: null
    function request(method, args, callback) {
      if (method === "dictation_state") {
        callback(true,{status:{available:1},session:session})
      } else if (method === "dictation_media") {
        clips++
        session=Object.assign({},session,{revision:session.revision+1})
        callback(true,{handle:"opaque-clip",session_id:session.id,revision:session.revision,
          playback_token:"attempt-"+clips,uri:__URI__,voice:"Authored tone",session:session})
      } else if (method === "dictation" && args.action === "heard") {
        if(args.playback_token !== "attempt-"+clips)
          throw new Error("Stale completion token")
        completions++
        session=Object.assign({},session,{revision:session.revision+1,heard:true})
        callback(true,{session:session})
      } else {
        throw new Error("Unexpected write: "+method)
      }
    }
  }
  MediaPlayer { id: player; audioOutput: AudioOutput { volume: 0 } }
  DictationState { id: core; controller: owner; player: player }
  TestCase {
    name: "DictationActualDecoder"
    when: windowShown
    function init() {
      owner.opened=false
      backend.completions=0;backend.clips=0
      backend.session={id:"authored-session",revision:1,phase:"question",index:0,total:1,
        media_handle:"opaque-clip",heard:false,draft:"",draft_cursor:0,preedit:"",draft_revision:0,
        input_error:"",feedback:null,subject:null,summary:{matched:0,again:0,skipped:0},
        undo_available:false,local_only:true,intervals:null}
      owner.opened=true
      tryVerify(function(){return core.session!==null&&!core.loading})
      compare(player.playbackState,MediaPlayer.StoppedState)
      compare(backend.clips,0)
    }
    function cleanup() { owner.opened=false;owner.stopAudio() }
    function test_decoded_end_enables_check_once_and_replay_does_not_ack_again() {
      verify(!core.canCheck)
      core.play()
      tryVerify(function(){return core.playing},3000)
      verify(!core.canCheck)
      tryVerify(function(){return core.canCheck},6000)
      compare(player.error,MediaPlayer.NoError)
      verify(player.duration>=500)
      compare(backend.completions,1)
      compare(core.ticket,null)
      core.play()
      tryVerify(function(){return core.playing},3000)
      tryCompare(player,"mediaStatus",MediaPlayer.EndOfMedia,6000)
      compare(backend.completions,1)
    }
    function test_close_during_decoding_cannot_ack_or_autoplay_after_resume() {
      core.play()
      tryVerify(function(){return core.playing},3000)
      owner.opened=false
      wait(900)
      compare(backend.completions,0)
      compare(player.playbackState,MediaPlayer.StoppedState)
      owner.opened=true
      tryVerify(function(){return core.session!==null&&!core.loading})
      compare(backend.clips,1)
      verify(!core.canCheck)
      compare(player.playbackState,MediaPlayer.StoppedState)
    }
  }
}
'''


@unittest.skipUnless(os.environ.get("WANIKANI_DECODER_QA") == "1" and RUNNER.exists() and shutil.which("ffmpeg"),
    "Opt-in muted decoder check requires accessible desktop audio IPC: WANIKANI_DECODER_QA=1")
class DictationDecoderTests(unittest.TestCase):
    def test_production_adapter_with_real_muted_decoder_signals(self):
        with tempfile.TemporaryDirectory(prefix="wanikani-dictation-decoder-") as temporary:
            directory = Path(temporary)
            wav = directory / "authored.wav"
            with wave.open(str(wav), "wb") as handle:
                handle.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                handle.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(i * math.tau * 440 / 22050))) for i in range(16538)))
            clip = directory / "authored.mp3"
            encoded = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(wav), str(clip)],
                capture_output=True, text=True, timeout=15)
            self.assertEqual(0, encoded.returncode, encoded.stderr)
            shutil.copy(ROOT / "qml" / "DictationState.qml", directory / "DictationState.qml")
            (directory / "tst_decoder.qml").write_text(QML.replace("__URI__", json.dumps(clip.as_uri())))
            env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic", "QT_MEDIA_BACKEND": "ffmpeg"}
            try:
                result = subprocess.run([str(RUNNER), "-input", str(directory)], env=env,
                    capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired as error:
                self.fail("Decoder fixture timed out: " + str(error.stdout) + "\n" + str(error.stderr))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("4 passed", result.stdout)
            self.assertNotIn("ReferenceError", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
