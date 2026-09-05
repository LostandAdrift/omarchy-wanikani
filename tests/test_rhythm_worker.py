"""Desktop reminder messages cannot forge account facts or delay study receipts."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW
from wanikani.common import epoch
from wanikani.demo import populate
from worker import Worker


class RhythmWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.messages = []
        self.worker = Worker(Path(self.temp.name), self.messages.append)
        populate(self.worker.engine.store, NOW)
        self.worker.engine.clock = lambda: NOW
        self.worker.engine.connected = True
        self.worker.engine.status = 'online'
        self.worker.readiness.refresh = Mock()
        self.worker.readiness.get = Mock(return_value={})

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.worker.engine.store.close()
        self.temp.cleanup()

    def request(self, method, args=None, rid=None):
        self.messages.clear()
        self.worker.handle({'v':1,'id':rid or method,'method':method,'args':args or {}})
        return self.messages[0]['data']

    def test_shell_context_cannot_replace_account_time_counts_or_vacation(self):
        engine = self.worker.engine
        result = self.worker.rhythm_context({'context':{'now':0,'review_count':999,'account_ready':False,
            'clock_untrusted':True,'vacation':True,'dnd':True,'event':'timer'}})
        self.assertEqual(NOW, result['now'])
        self.assertEqual(engine.snapshot()['reviews'], result['review_count'])
        self.assertTrue(result['account_ready'])
        self.assertFalse(result['vacation'])
        self.assertFalse(result['clock_untrusted'])
        self.assertTrue(result['dnd'])
        self.assertEqual(epoch(engine.snapshot()['next_reviews_at']), result['next_review_at'])

    def test_disconnected_and_untrusted_clock_are_explicit_suppression(self):
        self.worker.engine.connected = False
        self.assertFalse(self.worker.rhythm_context({})['account_ready'])
        self.worker.engine.clock_untrusted = True
        self.assertTrue(self.worker.rhythm_context({})['clock_untrusted'])

    def test_preview_configure_and_claim_do_not_emit_catalogue_events(self):
        context = {'hydrated':True,'locked':False,'dnd':False,'fullscreen':False,'studying':False}
        for method, args in (
            ('rhythm_preview',{'context':context}),
            ('rhythm_configure',{'context':context,'patch':{'mode':'times'}}),
            ('rhythm_claim',{'context':context})):
            with self.subTest(method=method), patch.object(self.worker, 'changed', side_effect=AssertionError('unneeded snapshot event')):
                result = self.request(method,args)
                self.assertIn('next_at',result)
                self.assertEqual(1,len(self.messages))
        self.assertEqual([],self.worker.engine.store.rows('SELECT * FROM outbox'))

    def test_study_activity_is_recorded_coarsely_without_catalogue_work(self):
        self.request('start',{'mode':'practice','subjects':[2],'limit':1})
        self.assertEqual(NOW,self.worker.engine.store.get('last_study_at'))
        with patch.object(self.worker.engine,'snapshot',side_effect=AssertionError('answer scanned catalogue')), \
                patch.object(self.worker.engine.store,'set',wraps=self.worker.engine.store.set) as setter:
            self.request('answer',{'text':'mountain'})
        self.assertNotIn('last_study_at',[call.args[0] for call in setter.call_args_list])

    def test_reminder_timestamp_failure_cannot_hide_a_committed_answer(self):
        self.request('start',{'mode':'practice','subjects':[2],'limit':1})
        self.worker.engine.store.set('last_study_at',0)
        original = self.worker.engine.store.set
        def failing(key,value):
            if key=='last_study_at':
                raise OSError('authored reminder-only storage failure')
            return original(key,value)
        with patch.object(self.worker.engine.store,'set',side_effect=failing):
            result = self.request('answer',{'text':'mountain'})
        self.assertEqual('feedback',result['phase'])
        self.assertTrue(result['feedback']['correct'])
        self.assertEqual('feedback',self.worker.engine.session_view()['phase'])


if __name__ == '__main__':
    unittest.main()
