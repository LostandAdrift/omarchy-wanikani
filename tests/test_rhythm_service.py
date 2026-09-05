"""Source-derived Service reminder scheduling; execDetached is an inert recorder."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path('/usr/lib/qt6/bin/qmltestrunner')


def function(source, name):
    match = re.search(r'(?ms)^  function ' + re.escape(name) + r'\(.*?^  \}', source)
    if not match:
        raise AssertionError('Review function boundary: ' + name)
    return match.group(0)


QML = r'''
import QtQuick
import QtTest
Item {
  ServiceCore { id: service }
  TestCase {
    name: "RhythmService"
    function report(toast,next) {
      return {next_at:next===undefined?null:next,status:"ready",config:{enabled:true},notification:toast?{
        id:"authored-claim",title:"Authored Japanese break",body:"Five short reviews are ready.",
        actions:[{view:"reviews",limit:5}]}:null}
    }
    function init() {
      service.ready=false
      service.pending=[]
      service.notifications=[]
      service.notificationHydrated=true
      service.locked=false
      service.dnd=false
      service.fullscreen=false
      service.studying=false
      service.snapshot={demo:false,vacation:false,username:"authored",max_level:3,session_epoch:"one"}
      service.rhythm=null
      service.rhythmFetching=false
      service.rhythmDirty=false
      service.rhythmEvent="startup"
      service.stopTimers()
      service.ready=true
    }
    function cleanup() { service.ready=false;service.stopTimers() }
    function reply(index,ok,data) { service.pending[index].callback(ok,data,ok?"":"Authored failure") }
    function claim() { service.considerNotification();service.claimRhythm() }
    function test_coalesced_claim_commits_before_one_delivery() {
      service.considerNotification()
      service.considerNotification()
      service.considerNotification()
      tryVerify(function(){return service.pending.length===1})
      service.claimRhythm()
      compare(service.pending.length,1)
      compare(service.pending[0].method,"rhythm_claim")
      compare(service.pending[0].args.context.event,"startup")
      compare(service.notifications.length,0)
      reply(0,true,report(true))
      compare(service.notifications.length,1)
      compare(service.notifications[0].slice(0,9),["omarchy","notification","send","--app-name","WaniKani","--urgency","low","Authored Japanese break","Five short reviews are ready."])
      compare(JSON.parse(service.notifications[0][service.notifications[0].length-1]),{view:"reviews",limit:5})
      wait(80)
      compare(service.pending.length,1)
      compare(service.notifications.length,1)
    }
    function test_unhydrated_context_is_sent_and_fails_closed() {
      service.notificationHydrated=false
      service.claimRhythm()
      compare(service.pending[0].args.context.hydrated,false)
      reply(0,true,report(true))
      compare(service.notifications.length,0)
      service.notificationHydrated=true
      tryVerify(function(){return service.pending.length===2})
      reply(1,true,report(false))
      compare(service.notifications.length,0)
    }
    function test_context_change_after_claim_drops_toast_data() {
      return ["locked","dnd","fullscreen","studying","hydration","account","demo","vacation","restart"].map(function(edge){return {tag:edge,edge:edge}})
    }
    function test_context_change_after_claim_drops_toast(data) {
      claim()
      var callback=service.pending[0].callback
      if (["locked","dnd","fullscreen","studying"].indexOf(data.edge)>=0) service[data.edge]=true
      if(data.edge==="hydration")service.notificationHydrated=false
      if(data.edge==="account")service.snapshot=Object.assign({},service.snapshot,{username:"different"})
      if(data.edge==="demo")service.snapshot=Object.assign({},service.snapshot,{demo:true})
      if(data.edge==="vacation")service.snapshot=Object.assign({},service.snapshot,{vacation:true})
      if(data.edge==="restart")service.ready=false
      callback(true,report(true),"")
      compare(service.notifications.length,0)
      verify(!service.rhythmFetching)
      if(service.rhythmDirty && service.ready) {
        tryVerify(function(){return service.pending.length===2})
        compare(service.pending[1].method,"rhythm_claim")
        reply(1,true,report(false))
      }
      wait(70)
      compare(service.notifications.length,0)
    }
    function test_transient_suppression_before_reply_also_drops_toast() {
      claim()
      service.locked=true
      service.locked=false
      reply(0,true,report(true))
      compare(service.notifications.length,0)
      tryVerify(function(){return service.pending.length===2})
      reply(1,true,report(false))
      compare(service.notifications.length,0)
    }
    function test_special_baseline_event_survives_followup_coalescing() {
      for(var event of ["startup","wake","clock_change","reconnect"]) {
        service.pending=[]
        service.considerNotification(event)
        service.considerNotification("state")
        service.claimRhythm()
        compare(service.pending[0].args.context.event,event)
        reply(0,true,report(false))
      }
    }
    function test_deadline_fires_once_and_failure_does_not_retry_expired_time() {
      service.rhythm=report(false,Date.now()/1000+0.04)
      tryVerify(function(){return service.pending.length===1},1800)
      verify(service.rhythmFetching)
      reply(0,false,null)
      verify(!service.rhythmFetching)
      wait(1250)
      compare(service.pending.length,1,"A failed claim must not rearm the expired deadline every second")
      verify(!service.deadlineRunning)
    }
    function test_deadline_rejects_nonfinite_or_past_timestamps() {
      for(var at of [null,Date.now()/1000-1,0,Infinity,NaN]) {
        service.rhythm=report(false,at)
        verify(!service.deadlineRunning,String(at)+" is not a future deadline")
      }
      service.rhythm=report(false,Date.now()/1000+3600)
      verify(service.deadlineRunning)
    }
    function test_preview_and_configure_are_not_delivery_paths() {
      var callbacks=[]
      service.previewRhythm({mode:"times"},function(ok,data,message){callbacks.push({ok:ok,data:data})})
      service.configureRhythm({enabled:false},function(ok,data,message){callbacks.push({ok:ok,data:data})})
      compare(service.pending[0].method,"rhythm_preview")
      compare(service.pending[1].method,"rhythm_configure")
      compare(service.pending[1].args.patch.enabled,false)
      reply(0,true,report(true))
      reply(1,true,report(true))
      compare(callbacks.length,2)
      compare(service.notifications.length,0)
      wait(70)
      compare(service.pending.length,2)
    }
    function test_late_configure_does_not_restore_previous_account_rhythm() {
      service.configureRhythm({enabled:false},function(){})
      service.snapshot=Object.assign({},service.snapshot,{username:"other"})
      reply(0,true,report(false))
      compare(service.rhythm,null)
      compare(service.notifications.length,0)
    }
  }
}
'''


def build(directory):
    source=(ROOT/'Service.qml').read_text()
    behavior='\n'.join(function(source,name) for name in
        ('rhythmContext','considerNotification','claimRhythm','previewRhythm','configureRhythm'))
    # This is the sole replacement of a production function body. The fixture
    # records the exact argv instead of importing or running Quickshell.
    behavior=behavior.replace('Quickshell.execDetached(', 'root.captureNotification(')
    handlers='\n'.join(re.search(r'(?m)^  on'+name+r'Changed:.*$',source).group(0) for name in
        ('NotificationHydrated','Dnd','Locked','Fullscreen','Studying'))
    context=re.search(r'(?m)^  readonly property string contentAccess:.*$',source).group(0)
    context_handler=re.search(r'(?ms)^  onContentAccessChanged: \{.*?^  \}',source).group(0)
    timers=[]
    for name in ('rhythmDelay','rhythmDeadline'):
        match=re.search(r'(?ms)^  Timer \{\n    id: '+name+r'\n.*?^  \}',source)
        if not match: raise AssertionError('Review Service timer boundary: '+name)
        timers.append(match.group(0))
    (directory/'ServiceCore.qml').write_text('''import QtQuick
Item {
 id: root
 property bool ready: false
 property bool notificationHydrated: false
 property bool locked: false
 property bool dnd: false
 property bool fullscreen: false
 property bool studying: false
 property var snapshot: ({})
 property var rhythm: null
 property bool rhythmFetching: false
 property bool rhythmDirty: true
 property string rhythmEvent: "startup"
 property var ambientItems: []
 property string pluginId: "authored-plugin"
 property var pending: []
 property var notifications: []
 readonly property bool deadlineRunning: rhythmDeadline.running
 function stopTimers() { rhythmDelay.stop();rhythmDeadline.stop() }
 function refreshAmbient() {}
 function request(method,args,callback) { pending=pending.concat([{method:method,args:args,callback:callback}]) }
 function captureNotification(args) { notifications=notifications.concat([args]) }
'''+context+'\n'+context_handler+'\n'+handlers+'\n'+behavior+'\n'+'\n'.join(timers)+'\n}\n')
    (directory/'tst_RhythmService.qml').write_text(QML)


@unittest.skipUnless(RUNNER.is_file(),'QtTest runtime is not installed')
class RhythmServiceTests(unittest.TestCase):
    def test_source_derived_reminder_adapter(self):
        with tempfile.TemporaryDirectory(prefix='wanikani-rhythm-service-') as temporary:
            directory=Path(temporary)
            build(directory)
            result=subprocess.run([str(RUNNER),'-input',str(directory)],capture_output=True,text=True,timeout=35,
                env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_QPA_PLATFORMTHEME':'','QT_QUICK_CONTROLS_STYLE':'Basic'})
        output=result.stdout+result.stderr
        self.assertEqual(result.returncode,0,output)
        self.assertNotIn('QWARN',output)


if __name__=='__main__':
    unittest.main()
