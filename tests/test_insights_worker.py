"""The lazy activity route is read-only and uses worker-owned account facts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_backend import NOW
from wanikani.common import UserError, stamp
from worker import Worker


class InsightsWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.messages = []
        with patch('worker.Keyring', return_value=Mock()):
            self.worker = Worker(Path(self.directory.name), self.messages.append)
        self.engine = self.worker.engine
        self.engine.clock = lambda: NOW
        self.engine.store.set('account_id', 'authored-activity-account')
        self.engine.store.set('user', {'object': 'user', 'data': {
            'id': 'authored-activity-account', 'username': 'Private learner', 'level': 2,
            'subscription': {'type': 'lifetime', 'max_level_granted': 60}}})
        self.worker.changed = Mock(side_effect=AssertionError('Read-only activity emitted a state change'))
        self.worker.session_changed = Mock(side_effect=AssertionError('Read-only activity emitted a study change'))
        self.guard = patch('socket.create_connection', side_effect=AssertionError('No live network in activity tests'))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def tearDown(self):
        self.worker.stopping = True
        self.worker.readiness.stop()
        self.engine.store.close()
        self.directory.cleanup()

    def request(self, args=None):
        self.messages.clear()
        self.worker.handle({'v': 1, 'id': 'activity', 'method': 'learning_insights', 'args': args or {}})
        self.assertEqual(1, len(self.messages))
        self.assertTrue(self.messages[0]['ok'])
        return self.messages[0]['data']

    def test_route_reports_real_local_completion_without_private_answer_or_writes(self):
        store = self.engine.store
        store.event('authored', 2, 'subject_complete', stamp(NOW), {
            'mode': 'reviews', 'errors': {'meaning': 0, 'reading': 0}, 'answer': 'PRIVATE ANSWER'})
        before = store.db.total_changes
        value = self.request()
        self.assertEqual(1, value['windows']['7']['subject_completions']['reviews'])
        self.assertEqual('recorded_on_this_device', value['scope'])
        self.assertNotIn('PRIVATE ANSWER', json.dumps(value))
        self.assertNotIn('Private learner', json.dumps(value))
        self.assertEqual(before, store.db.total_changes)
        self.assertEqual([], store.rows('SELECT * FROM outbox'))

    def test_caller_cannot_forge_available_study_suggestions(self):
        with patch.object(self.engine, 'snapshot', return_value={'reviews': 0, 'lessons': 0}), \
                patch('wanikani.listening.status', return_value={'available': 0}):
            value = self.request({'availability': {'reviews': 999, 'listening': 999}, 'now': NOW + 999999})
        self.assertEqual([], value['suggestions'])
        self.assertEqual(stamp(NOW), value['as_of'])

    def test_listening_clock_restriction_does_not_hide_recorded_activity(self):
        for error in (UserError('Listening clock needs refresh'), OSError('Authored media failure')):
            with self.subTest(error=type(error).__name__), patch('wanikani.listening.status', side_effect=error):
                value = self.request()
            self.assertEqual(30, len(value['daily']))
            self.assertEqual(0, value['windows']['30']['listening_sessions_completed'])


if __name__ == '__main__':
    unittest.main()
