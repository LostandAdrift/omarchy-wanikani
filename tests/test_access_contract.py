import unittest
from pathlib import Path

from test_backend import EngineFixture, FakeApi, NOW
from wanikani.common import UserError, stamp
from wanikani.practice import catalogue
from wanikani.readiness import calculate
from wanikani.sync import Synchronizer


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
