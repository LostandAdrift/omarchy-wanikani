"""Native practice pages hydrate only visible items without changing selection."""
import copy
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, NOW, UserError, stamp
from wanikani import practice


class PracticePagingTests(EngineFixture, unittest.TestCase):
    def compare(self, **args):
        expected = practice.catalogue(self.engine, **args)
        actual = practice.catalogue(self.engine, **args, readiness_scope="page")
        self.assertEqual(expected['items'], actual['items'])
        for key in ('counts', 'group', 'query', 'offset', 'limit', 'total', 'has_more',
                    'next_offset', 'mistake_days', 'selection_limit', 'graded_paused', 'saved_practice'):
            self.assertEqual(expected[key], actual[key], key)
        self.assertIsNone(actual['ready_counts'])
        self.assertIsNone(actual['ready_total'])
        self.assertEqual('page', actual['readiness_scope'])
        self.assertEqual(sum(item['ready'] for item in actual['items']), actual['page_ready'])
        return actual

    def test_groups_search_sort_and_pages_match_full_validation(self):
        for sid in (2, 6, 4):
            self.engine.pin(sid, True)
        for sid in (2, 4):
            self.store.event('authored', sid, 'answer', stamp(NOW-sid), {'part': 'meaning', 'kind': 'incorrect'})
        for group in practice.GROUPS:
            for query in ('', 'mountain', 'みず', '山が見える', '%', '_', '\\'):
                for offset in (0, 2, 200):
                    with self.subTest(group=group, query=query, offset=offset):
                        self.compare(group=group, query=query, offset=offset, limit=2)

    def test_malformed_answers_and_material_match_without_optimistic_readiness(self):
        original = self.store.subject(4)
        for key, value in (('meanings', None), ('meanings', [True]), ('readings', None),
                           ('readings', [{'reading': 'みず', 'accepted_answer': 1}]), ('auxiliary_meanings', False)):
            item = copy.deepcopy(original)
            item['data'][key] = value
            self.store.put(item)
            result = self.compare(group='learned', query='水')
            self.assertFalse(next(x for x in result['items'] if x['id'] == 4)['ready'])
        self.store.put(original)
        for value in (True, [], {'meaning_synonyms': [False]}, {'meaning_synonyms': 'water'}):
            self.store.set('material_draft_4', value)
            result = self.compare(group='learned', query='水')
            self.assertFalse(next(x for x in result['items'] if x['id'] == 4)['ready'])

    def test_image_presence_changes_are_rechecked_on_each_page(self):
        item = self.store.subject(1)
        item['data']['characters'] = None
        item['data']['character_images'] = [{'url': 'https://assets.wanikani.com/authored.svg'}]
        self.store.put(item)
        self.engine.pin(1, True)
        self.assertFalse(self.compare(group='saved')['items'][0]['ready'])
        image = self.path.parent / 'media' / 'authored.svg'
        image.parent.mkdir(exist_ok=True)
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.store.execute('INSERT INTO media VALUES(?,?,?,?)', ('https://assets.wanikani.com/authored.svg', str(image), image.stat().st_size, NOW))
        self.assertTrue(self.compare(group='saved')['items'][0]['ready'])
        image.unlink()
        self.assertFalse(self.compare(group='saved')['items'][0]['ready'])

    def test_protected_graded_and_pending_work_remain_distinct(self):
        view = self.engine.start('reviews', 1)
        sid = view['subject']['id']
        self.engine.pin(sid, True)
        result = self.compare(group='saved')
        self.assertTrue(result['items'][0]['spoilers_hidden'])
        self.assertEqual('', result['items'][0]['meaning'])
        while view['phase'] != 'complete':
            self.engine.answer(self.correct_answer(view))
            view = self.engine.advance()
        result = self.compare(group='saved')
        self.assertFalse(result['items'][0]['spoilers_hidden'])
        self.assertTrue(result['items'][0]['pending_graded'])

    def test_large_catalogue_validates_only_requested_page_without_a_cache(self):
        subject, assignment = self.store.subject(4), self.store.related('assignment', 4)
        with self.store.transaction():
            for sid in range(100, 9100):
                item = copy.deepcopy(subject)
                item['id'] = sid
                item['data']['level'] = sid % 60 + 1
                item['data']['meaning_mnemonic'] = 'Authored large fixture. ' * 30
                self.store.put(item)
                current = copy.deepcopy(assignment)
                current['id'] = sid+10000
                current['data']['subject_id'] = sid
                self.store.put(current)
        with patch.object(practice, 'validate_subject_answers', wraps=practice.validate_subject_answers) as validate:
            result = practice.catalogue(self.engine, group='learned', limit=30, readiness_scope='page')
            self.assertEqual(30, validate.call_count)
            self.assertEqual(9013, result['total'])
            self.assertEqual(30, result['page_ready'])
        item = self.store.subject(result['items'][0]['id'])
        item['data']['meanings'] = None
        self.store.put(item)
        revised = practice.catalogue(self.engine, group='learned', limit=30, readiness_scope='page')
        self.assertEqual(29, revised['page_ready'])

    def test_page_reads_preserve_all_personal_state(self):
        self.engine.start('practice', 1, [2])
        self.engine.draft('Authored untouched draft')
        before = list(self.store.db.iterdump())
        for group in practice.GROUPS:
            practice.catalogue(self.engine, group=group, readiness_scope='page')
        self.assertEqual(before, list(self.store.db.iterdump()))
        with self.assertRaises(UserError):
            practice.catalogue(self.engine, readiness_scope='unknown')


if __name__ == '__main__':
    unittest.main()
