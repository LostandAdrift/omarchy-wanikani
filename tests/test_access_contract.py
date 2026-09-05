import copy
import unittest
from pathlib import Path

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.common import UserError, stamp
from wanikani.practice import catalogue
from wanikani.readiness import calculate
from wanikani.sync import Synchronizer
from wanikani.store import Store


class AccessContractTests(EngineFixture, unittest.TestCase):
    def subscription(self, kind, granted=60, end=None, active=True):
        user = self.store.get('user')
        user['data']['subscription'] = {'type': kind, 'max_level_granted': granted,
            'period_ends_at': end, 'active': active}
        self.store.set('user', user)

    def test_unknown_and_free_states_restrict_premium_content_everywhere(self):
        item = self.store.subject(2)
        item['data']['level'] = 4
        self.store.put(item)
        for kind in ('unknown', 'free', 'future-subscription-type', None):
            with self.subTest(kind=kind):
                self.subscription(kind)
                self.assertEqual(3, self.engine.max_level())
                with self.assertRaises(UserError):
                    self.engine.details(2)
                self.assertNotIn(2, [x['id'] for x in self.engine.search('mountain')])
                self.assertNotIn(2, [x['id'] for x in catalogue(self.engine, group='learned')['items']])
                self.assertEqual(4, self.engine.snapshot()['reviews'])
                self.assertEqual(4, calculate(self.engine)['reviews']['total'])

    def test_expiry_is_exact_and_cancellation_keeps_paid_period_access(self):
        self.subscription('recurring', end=stamp(NOW + 1), active=False)
        self.assertEqual(60, self.engine.max_level())
        self.subscription('recurring', end=stamp(NOW))
        self.assertEqual(3, self.engine.max_level())
        self.subscription('recurring', end=stamp(NOW - 1))
        self.assertEqual(3, self.engine.max_level())

    def test_invalid_recurring_expiry_cannot_extend_offline_access(self):
        for end in (None, '', 'not a date'):
            with self.subTest(end=end):
                self.subscription('recurring', end=end)
                self.assertEqual(3, self.engine.max_level())
        self.subscription('lifetime', end=None)
        self.assertEqual(60, self.engine.max_level())

    def test_invalid_or_lower_explicit_grant_never_expands(self):
        for value in (None, '60', True, -1, 61):
            with self.subTest(value=value):
                self.subscription('lifetime', granted=value)
                self.assertEqual(0, self.engine.max_level())
        for kind in ('free', 'unknown', 'recurring'):
            self.subscription(kind, granted=0, end=stamp(NOW - 1))
            self.assertEqual(0, self.engine.max_level())

    def test_zero_grant_never_sends_an_empty_unfiltered_subject_query(self):
        self.subscription('free', granted=0)
        api = FakeApi(self.store)
        calls = []
        original = api.collection
        def collections(endpoint, params=None):
            calls.append((endpoint, params))
            yield from original(endpoint, params)
        api.collection = collections
        sync = Synchronizer(self.engine, api, Path(self.temp.name) / 'media')
        self.assertTrue(sync.run(for_study=True))
        self.assertNotIn('subjects', [endpoint for endpoint, _ in calls])
        self.assertEqual(0, self.store.get('cached_max_level'))
        self.subscription('free', granted=3)
        api.user = self.store.get('user')
        calls.clear()
        self.assertTrue(sync.run(for_study=True))
        self.assertEqual({'levels': '1,2,3'}, next(params for endpoint, params in calls if endpoint == 'subjects'))

    def test_malformed_subject_levels_are_unavailable_on_all_catalogue_surfaces(self):
        original = self.store.subject(2)
        self.engine.pin(2, True)
        for level in (None, '1', True, False, 0, -1, 1.0, 1.5, {}, [], 61):
            with self.subTest(level=level):
                item = copy.deepcopy(original)
                item['data']['level'] = level
                self.store.put(item)
                with self.assertRaises(UserError) as error:
                    self.engine.details(2)
                self.assertEqual('access_restricted', error.exception.code)
                self.assertNotIn(2, [item['id'] for item in self.engine.search('mountain')])
                self.assertNotIn(2, [item['id'] for item in catalogue(self.engine, group='saved')['items']])
                self.assertNotIn(2, [item['id'] for item in self.engine.difficult()])
                self.assertEqual(4, self.engine.snapshot()['reviews'])
                availability = calculate(self.engine)
                self.assertEqual(4, availability['reviews']['total'])
                self.assertEqual(4, availability['reviews']['ready'])

    def test_valid_integer_levels_and_hidden_metadata_are_consistent(self):
        original = self.store.subject(2)
        for level in (1, 3, 60):
            item = copy.deepcopy(original)
            item['data']['level'] = level
            self.store.put(item)
            self.assertEqual(2, self.engine.details(2)['id'])
            self.assertIn(2, [item['id'] for item in self.engine.search('mountain')])
        for hidden in ('', False, 0, [], {}, stamp(NOW)):
            item = copy.deepcopy(original)
            item['data']['hidden_at'] = hidden
            self.store.put(item)
            with self.assertRaises(UserError):
                self.engine.details(2)
            self.assertNotIn(2, [item['id'] for item in self.engine.search('mountain')])
        self.subscription('free', granted=0)
        item = copy.deepcopy(original)
        item['data']['level'] = 0
        self.store.put(item)
        self.assertEqual(0, self.engine.snapshot()['cache']['subjects'])
        self.assertEqual([], self.engine.search('mountain'))

    def test_access_change_blocks_answer_without_altering_saved_draft(self):
        self.engine.start('practice', 1, [2])
        self.engine.draft('Unfinished authored answer')
        before = self.store.session()
        item = self.store.subject(2)
        item['data']['level'] = True
        self.store.put(item)
        with self.assertRaises(UserError) as error:
            self.engine.command('invalid-level-answer', 'answer', {'text': 'mountain'})
        self.assertEqual('access_restricted', error.exception.code)
        self.assertEqual(before, self.store.session())
        self.assertEqual([], self.store.rows('SELECT * FROM events'))
        self.assertEqual([], self.store.rows('SELECT * FROM commands'))

    def test_legacy_access_index_migrates_once_without_touching_durable_state(self):
        self.engine.start('practice', 1, [2])
        self.engine.draft('Retained across index migration')
        before, epoch = self.store.session(), self.store.get('session_epoch')
        with self.store.transaction():
            self.store.execute('DROP INDEX resource_search_identity')
            self.store.execute("""CREATE INDEX resource_search_identity ON resources(
                kind,CAST(id AS INTEGER),id,json_extract(body,'$.data.level'),json_extract(body,'$.data.hidden_at'))
                WHERE kind IN ('radical','kanji','vocabulary','kana_vocabulary')""")
        self.store.close()
        self.store = Store(self.path)
        self.engine.store = self.store
        sql = self.store.rows("SELECT sql FROM sqlite_master WHERE name='resource_search_identity'")[0][0]
        self.assertIn("json_type(body,'$.data.level')", sql)
        rootpage = self.store.rows("SELECT rootpage FROM sqlite_master WHERE name='resource_search_identity'")[0][0]
        self.assertEqual(before, self.store.session())
        self.assertEqual(epoch, self.store.get('session_epoch'))
        self.store.close()
        self.store = Store(self.path)
        self.engine.store = self.store
        self.assertEqual(rootpage, self.store.rows("SELECT rootpage FROM sqlite_master WHERE name='resource_search_identity'")[0][0])
        self.assertEqual(before, self.store.session())
