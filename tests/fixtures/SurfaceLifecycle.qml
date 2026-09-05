import QtQuick
import QtTest
import "UnicodeText.mjs" as UnicodeText
TestCase {
  id: test
  name: "SurfaceLifecycle"
  property var objects: []
  readonly property var testService: service
  QtObject {
    id: service
    property var snapshot: ({})
    property var requests: []
    property var pending: []
    property bool hold: false
    property bool ready: true
    property bool locked: false
    function result(args) {
      return {items:[{id:1,label:"Authored voice",description:"",ready:true}],offset:args.offset||0,
        counts:{},ready_counts:{},total:1,ready_total:1}
    }
    function request(method,args,callback) {
      requests=requests.concat([{method:method,args:args}])
      if (!callback) return
      if (hold) pending=pending.concat([{callback:callback,args:args}])
      else callback(true,result(args),"")
    }
    function reply() {
      var item=pending[0]
      pending=pending.slice(1)
      item.callback(true,result(item.args),"")
    }
  }
  QtObject {
    id: controller
    property var service: testService
    property bool opened: true
    property bool busy: false
    property string view: "lookup"
    property string contentAccess: "fixture"
    property string query: ""
    property bool queryTruncated: false
    property var detail: null
    property var session: null
    property bool searching: false
    property int searchSequence: 0
    property int plays: 0
    property var actions: []
    readonly property var snapshot: service.snapshot
    function play(subject) { plays++ }
    function studyAction(method,args) { actions=actions.concat([{method:method,args:args}]) }
    function search(text) { query=text; searchSequence++; service.request("search",{text:text}) }
  }
  function make(name) {
    var component=Qt.createComponent(name+"Core.qml")
    compare(component.status,Component.Ready,component.errorString())
    var item=component.createObject(test,name==="Panel"?{service:service}:{controller:controller})
    verify(item!==null)
    objects=objects.concat([item])
    return item
  }
  function init() {
    controller.opened=true;controller.busy=false;controller.plays=0;controller.actions=[]
    controller.session=null;controller.detail=null;controller.query="";controller.searching=false
    controller.searchSequence=0;controller.contentAccess="fixture"
    service.hold=false;service.ready=true;service.locked=false;service.requests=[];service.pending=[]
    service.snapshot={settings:{autoplay_audio:true,voice_actor_id:1},state_revision:1,last_sync:"initial",cache:{subjects:16}}
  }
  function cleanup() { objects.forEach(function(item){item.destroy()});objects=[];wait(1) }
  function pages() { return [{tag:"recovery",name:"Recovery"},{tag:"practice",name:"Practice"},{tag:"voices",name:"VoiceChoices"}] }
  function test_hidden_pages_refresh_once_on_reopening_data() { return pages() }
  function test_hidden_pages_refresh_once_on_reopening(data) {
    make(data.name);wait(320);compare(service.requests.length,1)
    controller.opened=false
    for(var i=0;i<3;i++) service.snapshot=Object.assign({},service.snapshot,{state_revision:i+2,last_sync:"hidden"+i})
    wait(320);compare(service.requests.length,1)
    controller.opened=true;wait(320);compare(service.requests.length,2)
  }
  function test_constructed_closed_or_unready_never_reads_data() { return pages() }
  function test_constructed_closed_or_unready_never_reads(data) {
    controller.opened=false;service.ready=false
    make(data.name);wait(30);compare(service.requests.length,0)
    controller.opened=true;wait(30);compare(service.requests.length,0)
    service.ready=true;wait(30);compare(service.requests.length,1)
    service.locked=true
    service.snapshot=Object.assign({},service.snapshot,{state_revision:2,last_sync:"locked"})
    wait(320);compare(service.requests.length,1)
    service.locked=false;wait(30);compare(service.requests.length,2)
  }
  function test_one_inflight_read_across_close_and_reopen_data() { return pages() }
  function test_one_inflight_read_across_close_and_reopen(data) {
    service.hold=true;make(data.name);wait(20);compare(service.requests.length,1)
    controller.opened=false;controller.opened=true;wait(30);compare(service.requests.length,1)
    service.reply();wait(30);compare(service.requests.length,2)
    service.reply();wait(30);compare(service.pending.length,0);compare(service.requests.length,2)
  }
  function test_hidden_access_change_clears_rows_without_reads_data() { return pages() }
  function test_hidden_access_change_clears_rows_without_reads(data) {
    var item=make(data.name);wait(30)
    controller.opened=false;controller.contentAccess="new epoch"
    wait(320);compare(service.requests.length,1)
    compare(data.name==="Recovery"?item.page.items.length:data.name==="Practice"?item.library.items.length:item.voices.length,0)
    controller.opened=true;wait(30);compare(service.requests.length,2)
  }
  function test_recovery_ignores_progress_only_events_and_keeps_filters() {
    var item=make("Recovery");wait(20)
    item.kindFilter="material";item.stateFilter="uncertain";item.loadPage(30);wait(20)
    compare(service.requests.length,2)
    service.snapshot=Object.assign({},service.snapshot,{sync_progress:{stage:"subjects"},readiness:{checking:true}})
    wait(320);compare(service.requests.length,2)
    controller.opened=false;controller.opened=true;wait(20)
    compare(service.requests[2].args.offset,30);compare(service.requests[2].args.kind,"material")
    compare(service.requests[2].args.state,"uncertain")
  }
  function test_practice_pending_query_survives_close_without_hidden_read() {
    var item=make("Practice");wait(20)
    item.group="learned";item.loadPage(30);wait(20)
    service.requests=[];item.searchText="mountain";item.editSearch();controller.opened=false
    wait(220);compare(service.requests.length,0)
    controller.opened=true;wait(30);compare(service.requests.length,1)
    compare(service.requests[0].args.query,"mountain");compare(service.requests[0].args.offset,0)
    compare(service.requests[0].args.group,"learned")
  }
  function test_practice_new_filters_coalesce_during_inflight_read() {
    service.hold=true;var item=make("Practice");wait(20)
    item.chooseGroup("learned");item.loadPage(30);wait(20);compare(service.requests.length,1)
    service.reply();wait(20);compare(service.requests.length,2)
    compare(service.requests[1].args.group,"learned");compare(service.requests[1].args.offset,30)
    service.reply();wait(20);compare(item.library.offset,30)
  }
  function test_lookup_enter_cancels_debounce() {
    var item=make("Lookup");wait(20);service.requests=[]
    item.searchText="山";item.editSearch();item.searchNow(item.searchText)
    wait(220);compare(service.requests.length,1);compare(service.requests[0].args.text,"山")
  }
  function test_lookup_close_cancels_debounce_and_reopen_reads_once() {
    var item=make("Lookup");wait(20);service.requests=[]
    item.searchText="山道";item.editSearch();controller.opened=false
    wait(220);compare(service.requests.length,0);compare(controller.query,"山道")
    controller.opened=true;wait(30);compare(service.requests.length,1)
    compare(service.requests[0].args.text,"山道")
  }
  function test_lookup_waits_for_worker_and_preserves_open_details() {
    service.ready=false;make("Lookup");wait(20);compare(service.requests.length,0)
    controller.query="山";service.ready=true;wait(20);compare(service.requests.length,1)
    controller.detail={id:2};service.ready=false;service.ready=true;wait(20)
    compare(service.requests.length,1);compare(controller.detail.id,2)
  }
  function test_lookup_route_payload_prevents_duplicate_initial_read() {
    make("Lookup");controller.search("山");wait(30);compare(service.requests.length,1)
  }
  function test_lookup_selection_capture_invalidates_deferred_initial_query() {
    make("Lookup");controller.searchSequence++;wait(30);compare(service.requests.length,0)
  }
  function test_lookup_codepoint_bound_keeps_surrogate_pair_and_whitespace() {
    var item=make("Lookup");wait(20)
    item.searchText=" "+"山".repeat(254)+"𠮷"+" ";item.editSearch()
    compare(UnicodeText.characters(controller.query).length,256);verify(controller.query.endsWith("𠮷"));verify(controller.query.startsWith(" "))
    verify(controller.queryTruncated)
    item.searchText=" 山\n ";item.editSearch();compare(controller.query," 山\n ");verify(!controller.queryTruncated)
  }
  function test_panel_search_codepoint_bound_keeps_surrogate_pair() {
    var item=make("Panel");item.search("山".repeat(255)+"𠮷"+"水")
    compare(UnicodeText.characters(item.query).length,256);verify(item.query.endsWith("𠮷"));verify(item.queryTruncated)
  }
  function test_panel_search_and_audio_require_visible_ready_unlocked_surface() {
    var item=make("Panel")
    item.opened=false;item.search("山");item.play({audio:[{url:"file:///fixture.wav"}]})
    compare(service.requests.length,0);compare(item.playCount,0)
    item.opened=true;service.ready=false;item.refreshSearch();item.play({audio:[{url:"file:///fixture.wav"}]})
    compare(service.requests.length,0);compare(item.playCount,0)
    service.ready=true;service.locked=true;item.refreshSearch();item.play({audio:[{url:"file:///fixture.wav"}]})
    compare(service.requests.length,0);compare(item.playCount,0)
    service.locked=false;item.refreshSearch();item.play({audio:[{url:"file:///fixture.wav"}]})
    compare(service.requests.length,1);compare(item.playCount,1)
    item.view="study";item.refreshSearch();compare(service.requests.length,1)
  }
  function test_late_search_response_cannot_repopulate_closed_panel() {
    service.hold=true;var item=make("Panel");item.search("山")
    item.opened=false;service.reply();compare(item.results.length,0)
  }
  function session(phase,part) {
    return {id:"fixture",phase:phase,part:part,draft:"",subject:{id:2,type:"kanji",audio:[{url:"file:///fixture.wav"}]},feedback:{correct:true},lesson_index:0}
  }
  function test_late_feedback_does_not_play_after_close_or_lock() {
    make("Study");controller.opened=false;controller.session=session("feedback","reading")
    wait(20);compare(controller.plays,0)
    controller.opened=true;service.locked=true
    var next=session("feedback","reading");next.id="locked fixture";controller.session=next
    wait(20);compare(controller.plays,0)
    service.locked=false;next=session("feedback","reading");next.id="visible fixture";controller.session=next
    wait(20);compare(controller.plays,1)
  }
  function test_image_readiness_gates_answer_advance_and_lesson_navigation() {
    var item=make("Study");item.glyphReady=false;controller.session=session("question","meaning")
    item.submit();compare(controller.actions.length,0)
    item.glyphReady=true;item.answerText="mountain";item.submit()
    compare(controller.actions[0].method,"answer")
    controller.actions=[];controller.session=session("feedback","meaning");item.glyphReady=false
    item.submit();compare(controller.actions.length,0)
    item.glyphReady=true;item.submit();compare(controller.actions[0].method,"advance")
    controller.actions=[];controller.session=session("lesson","meaning");item.glyphReady=false
    item.nextLesson(false);compare(controller.actions.length,0)
    item.nextLesson(true);compare(controller.actions[0].method,"lesson_next");compare(controller.actions[0].args.back,true)
    controller.actions=[];item.glyphReady=true;item.nextLesson(false);compare(controller.actions[0].args.back,false)
    controller.actions=[];controller.opened=false;item.nextLesson(false);item.nextLesson(true);compare(controller.actions.length,0)
  }
}
