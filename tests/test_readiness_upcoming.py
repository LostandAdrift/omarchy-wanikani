"""Next-day offline preparation uses exact scheduling and future access."""
import copy
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from test_backend import EngineFixture, NOW
from wanikani.common import stamp
from wanikani.readiness import GROUPS, OfflineReadiness, calculate


class UpcomingReadinessTests(EngineFixture, unittest.TestCase):
    def clear_assignments(self):
        self.store.execute("DELETE FROM resources WHERE kind='assignment'")

    def due(self, sid, available, level=1, started=None, burned=None):
        subject = copy.deepcopy(self.store.subject(2))
        subject['id'] = sid
        subject['data'].update(level=level, pronunciation_audios=[], character_images=[])
        self.store.put(subject)
        assignment = {'id': sid + 50000, 'object': 'assignment', 'data': {
            'subject_id': sid, 'started_at': stamp(NOW - 86400) if started is None else started,
            'unlocked_at': stamp(NOW - 86400), 'available_at': available,
            'burned_at': burned, 'hidden': False}}
        self.store.put(assignment)
        return subject, assignment

    def cache(self, url, name):
        path = Path(self.temp.name) / 'media' / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'Independently authored cached fixture.')
        self.store.execute('INSERT INTO media VALUES(?,?,?,?)', (url, str(path), path.stat().st_size, NOW))
        return path

    def test_upcoming_is_separate_from_due_now_and_lessons(self):
        result = calculate(self.engine)
        self.assertTrue(result['complete'])
        self.assertEqual((5, 3, 4), tuple(result[mode]['ready'] for mode in GROUPS))
        self.assertTrue(all(result[mode]['total_complete'] for mode in GROUPS))
        self.assertEqual((5, 3), (self.engine.assignments('reviews', True), self.engine.assignments('lessons', True)))

    def test_exact_fractional_boundaries_and_timezone_offsets(self):
        self.clear_assignments()
        deltas = (-.000001, 0, .000001, 3600, 86400, 86400.000001)
        for index, (delta, offset) in enumerate((delta, offset) for delta in deltas for offset in (-7, 0, 5.5)):
            value = datetime.fromtimestamp(NOW + delta, timezone(timedelta(hours=offset))).isoformat()
            self.due(100 + index, value)
        result = calculate(self.engine)
        self.assertEqual(6, result['reviews']['total'])
        self.assertEqual(9, result['upcoming_reviews']['total'])
        self.assertEqual(9, result['upcoming_reviews']['ready'])
        self.assertTrue(result['complete'])

    def test_daylight_saving_horizon_is_86400_seconds(self):
        self.clear_assignments()
        now = datetime(2026, 11, 1, 0, 0, tzinfo=ZoneInfo('America/New_York')).timestamp()
        self.engine.clock = lambda: now
        for index, delta in enumerate((86400, 86400.000001, 90000)):
            self.due(100 + index, datetime.fromtimestamp(now + delta, ZoneInfo('America/New_York')).isoformat())
        result = calculate(self.engine)
        self.assertEqual(1, result['upcoming_reviews']['ready'])
        self.assertEqual(0, result['reviews']['total'])

    def test_clock_is_captured_once_and_optional_access_time_does_not_advance_it(self):
        calls = []
        def clock():
            calls.append(None)
            return NOW + len(calls) - 1
        self.engine.clock = clock
        result = calculate(self.engine)
        self.assertEqual(stamp(NOW), result['checked_at'])
        self.assertEqual(1, len(calls))
        self.assertEqual(60, self.engine.max_level(NOW + 86400))
        self.assertEqual(1, len(calls))

    def test_future_subscription_expiry_is_applied_at_review_time(self):
        self.clear_assignments()
        for sid, due in ((100, NOW + 3599), (101, NOW + 3600), (102, NOW + 7200)):
            self.due(sid, stamp(due), level=8)
        self.due(103, stamp(NOW + 7200), level=3)
        user = self.store.get('user')
        user['data']['subscription'].update(type='recurring', period_ends_at=stamp(NOW + 3600))
        self.store.set('user', user)
        result = calculate(self.engine)
        self.assertEqual(2, result['upcoming_reviews']['ready'])
        self.assertEqual(60, self.engine.max_level())
        self.assertEqual(3, self.engine.max_level(NOW + 3600))
        self.assertEqual(stamp(NOW + 3600), self.engine.user()['subscription']['period_ends_at'])

    def test_lifetime_unknown_and_malformed_expiry_preserve_effective_grants(self):
        self.clear_assignments()
        self.due(100, stamp(NOW + 3600), level=8)
        self.due(101, stamp(NOW + 3600), level=2)
        cases = [('lifetime', stamp(NOW - 1), 60, 2), ('recurring', None, 60, 1),
            ('recurring', 'invalid', 60, 1), ('unknown', stamp(NOW + 7200), 60, 1),
            ('recurring', stamp(NOW + 3600), 2, 1), ('recurring', stamp(NOW + 86400), 60, 2)]
        for kind, expiry, grant, expected in cases:
            with self.subTest(kind=kind, expiry=expiry, grant=grant):
                user = self.store.get('user')
                user['data']['subscription'].update(type=kind, period_ends_at=expiry, max_level_granted=grant)
                self.store.set('user', user)
                result = calculate(self.engine)
                self.assertEqual(expected, result['upcoming_reviews']['ready'])

    def test_busy_graded_cycles_are_excluded_but_material_and_archived_work_are_not(self):
        self.clear_assignments()
        states = ['pending', 'inflight', 'uncertain', 'blocked', 'conflicted', 'confirmed', 'discarded']
        for index, state in enumerate(states):
            for offset, kind in ((0, 'review'), (100, 'lesson'), (200, 'material')):
                sid = 100 + index + offset
                self.due(sid, stamp(NOW + 3600))
                self.store.execute('INSERT INTO outbox VALUES(?,?,?,?,?,?,?)',
                    ('op-' + str(sid), kind, sid, state, '{}', NOW, ''))
        result = calculate(self.engine)
        self.assertEqual(11, result['upcoming_reviews']['ready'])

    def test_strict_access_hidden_burned_unstarted_and_invalid_times_are_excluded(self):
        self.clear_assignments()
        for index, level in enumerate((True, False, 0, -1, '1', 1.0, None, 61)):
            self.due(100 + index, stamp(NOW + 3600), level=level)
        for index, value in enumerate(('not a timestamp', None, 123, [], '2026-02-30T00:00:00Z')):
            self.due(200 + index, value)
        subject, assignment = self.due(300, stamp(NOW + 3600))
        subject['data']['hidden_at'] = stamp(NOW)
        self.store.put(subject)
        _, assignment = self.due(301, stamp(NOW + 3600))
        assignment['data']['hidden'] = True
        self.store.put(assignment)
        self.due(302, stamp(NOW + 3600), burned=stamp(NOW - 1))
        _, assignment = self.due(303, stamp(NOW + 3600))
        assignment['data'].update(started_at=None, unlocked_at=stamp(NOW + 3600))
        self.store.put(assignment)
        self.assertEqual(0, calculate(self.engine)['upcoming_reviews']['total'])

    def test_required_images_and_validated_text_are_distinct_from_optional_audio(self):
        self.clear_assignments()
        subject, _ = self.due(100, stamp(NOW + 3600))
        subject['object'] = 'radical'
        self.store.execute("DELETE FROM resources WHERE kind='kanji' AND id='100'")
        subject['data'].update(characters=None, readings=[], character_images=[
            {'url': 'https://wanikani.com/missing.svg'}, {'url': 'https://wanikani.com/alternate.png'}])
        self.store.put(subject)
        vocabulary, _ = self.due(101, stamp(NOW + 3600))
        vocabulary['data']['pronunciation_audios'] = [{'url': 'https://wanikani.com/audio.mp3'}]
        self.store.put(vocabulary)
        missing = calculate(self.engine)['upcoming_reviews']
        self.assertEqual((1, 1, 1, 0), tuple(missing[key] for key in ('ready', 'missing_images', 'audio_total', 'audio_cached')))
        self.cache('https://wanikani.com/alternate.png', 'alternate.png')
        ready = calculate(self.engine)
        self.assertEqual(2, ready['upcoming_reviews']['ready'])
        self.assertIn('optional', ready['message'])
        vocabulary['data']['meanings'][0]['accepted_answer'] = 'yes'
        self.store.put(vocabulary)
        self.assertEqual(1, calculate(self.engine)['upcoming_reviews']['missing_text'])
        vocabulary['data']['meanings'][0]['accepted_answer'] = True
        self.store.put(vocabulary)
        self.store.set('material_draft_101', {'meaning_synonyms': 'malformed'})
        self.assertEqual(1, calculate(self.engine)['upcoming_reviews']['missing_text'])

    def test_shared_content_budget_checks_due_reviews_then_lessons_then_upcoming(self):
        result = calculate(self.engine, max_items=9)
        self.assertFalse(result['complete'])
        self.assertEqual((5, 3, 1), tuple(result[mode]['checked'] for mode in GROUPS))
        self.assertEqual((5, 3, 4), tuple(result[mode]['total'] for mode in GROUPS))
        self.clear_assignments()
        for sid in range(100, 105):
            self.due(sid, stamp(NOW + 3600))
        result = calculate(self.engine, max_items=3)
        self.assertFalse(result['complete'])
        self.assertEqual((3, 5), (result['upcoming_reviews']['checked'], result['upcoming_reviews']['total']))

    def test_schedule_cap_and_deadline_never_claim_exact_totals(self):
        with patch('wanikani.readiness.MAX_SCHEDULE', 5):
            result = calculate(self.engine)
        self.assertFalse(result['complete'])
        self.assertFalse(any(result[mode]['total_complete'] for mode in GROUPS))
        self.assertIn('totals are not yet known', result['message'])
        self.assertLessEqual(sum(result[mode]['total'] for mode in GROUPS), 5)
        timed = calculate(self.engine, budget_seconds=0)
        self.assertFalse(timed['complete'])
        self.assertEqual(0, sum(timed[mode]['checked'] for mode in GROUPS))
        self.assertFalse(any(timed[mode]['total_complete'] for mode in GROUPS))

    def test_changed_assignment_cannot_be_reported_ready_from_stale_projection(self):
        rows = self.store.rows
        changed = []
        def concurrent_rows(sql, args=()):
            if 'AS material' in sql and not changed:
                changed.append(True)
                assignment = self.store.related('assignment', 1)
                assignment['data']['available_at'] = stamp(NOW + 7200)
                self.store.put(assignment)
            return rows(sql, args)
        with patch.object(self.store, 'rows', side_effect=concurrent_rows):
            result = calculate(self.engine)
        self.assertFalse(result['complete'])
        self.assertEqual(0, result['reviews']['checked'])

    def test_foreground_cached_result_stays_scan_free_and_independent(self):
        cached = OfflineReadiness(self.engine)
        cached.value = calculate(self.engine)
        with patch.object(self.store, 'rows', side_effect=AssertionError('Foreground scan')):
            result = cached.get()
        result['upcoming_reviews']['ready'] = 999
        self.assertEqual(4, cached.get()['upcoming_reviews']['ready'])
        json.dumps(result)

    def test_large_upcoming_group_keeps_content_batches_small_and_total_budget_shared(self):
        self.clear_assignments()
        with self.store.transaction():
            for sid in range(100, 400):
                self.due(sid, stamp(NOW + 3600))
        rows = self.store.rows
        batches = []
        def observed_rows(sql, args=()):
            result = rows(sql, args)
            if 'AS material' in sql:
                batches.append(len(result))
            return result
        with patch.object(self.store, 'rows', side_effect=observed_rows):
            result = calculate(self.engine, max_items=129)
        self.assertEqual([128, 1], batches)
        self.assertFalse(result['complete'])
        self.assertEqual((129, 300), (result['upcoming_reviews']['ready'], result['upcoming_reviews']['total']))
        self.assertTrue(result['upcoming_reviews']['total_complete'])

    def test_projection_uses_schedule_and_subject_access_indexes(self):
        rows = self.store.rows
        plans = []
        def observed_rows(sql, args=()):
            if 'LIMIT ?' in sql and 'resource_assignment_schedule' in sql:
                plans.extend(str(row['detail']) for row in rows('EXPLAIN QUERY PLAN ' + sql, args))
            return rows(sql, args)
        with patch.object(self.store, 'rows', side_effect=observed_rows):
            calculate(self.engine)
        self.assertTrue(any('resource_assignment_schedule' in step for step in plans), plans)
        self.assertTrue(any('resource_search_identity' in step for step in plans), plans)

    def test_subscription_change_during_check_discards_previously_accessible_counts(self):
        for change in ('grant', 'expiry', 'clock'):
            with self.subTest(change=change):
                user = self.store.get('user')
                user['data']['subscription'].update(type='recurring', max_level_granted=60,
                    period_ends_at=stamp(NOW + 7200))
                self.store.set('user', user)
                self.engine.clock_offset = 0
                rows = self.store.rows
                changed = []
                def concurrent_rows(sql, args=()):
                    result = rows(sql, args)
                    if 'AS material' in sql and not changed:
                        changed.append(True)
                        if change == 'clock':
                            self.engine.clock_offset = 60
                        else:
                            current = self.store.get('user')
                            if change == 'grant':
                                current['data']['subscription']['max_level_granted'] = 1
                            else:
                                # Both old and new end-of-horizon grants are 3.
                                current['data']['subscription']['period_ends_at'] = stamp(NOW + 1800)
                            self.store.set('user', current)
                    return result
                with patch.object(self.store, 'rows', side_effect=concurrent_rows):
                    result = calculate(self.engine)
                self.assertFalse(result['complete'])
                self.assertEqual(0, sum(result[mode]['ready'] for mode in GROUPS))
                self.assertFalse(any(result[mode]['total_complete'] for mode in GROUPS))
                self.assertIn('changed during the check', result['message'])

    def test_access_change_between_calculation_and_background_publication_is_invalidated(self):
        updates, arrived = [], threading.Event()
        def changed(value):
            updates.append(value)
            arrived.set()
        cache = OfflineReadiness(self.engine, changed)
        def calculate_then_change(*args):
            result = calculate(*args)
            user = self.store.get('user')
            user['data']['subscription']['max_level_granted'] = 1
            self.store.set('user', user)
            return result
        with patch('wanikani.readiness.calculate', side_effect=calculate_then_change):
            cache.refresh()
            self.assertTrue(arrived.wait(2))
        cache.stop()
        self.assertFalse(updates[-1]['complete'])
        self.assertEqual(0, sum(updates[-1][mode]['ready'] for mode in GROUPS))


if __name__ == '__main__':
    unittest.main()
