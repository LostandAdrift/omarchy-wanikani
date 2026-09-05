import copy
import json
import unittest
from unittest.mock import patch

from test_backend import EngineFixture, NOW
from wanikani.common import UserError, stamp
from wanikani.engine import Engine
from wanikani.store import Store


class SearchTests(EngineFixture, unittest.TestCase):
    def reopen(self):
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)

    def test_exact_match_ranks_across_entire_catalogue_before_limit(self):
        sample = self.store.subject(2)
        with self.store.transaction():
            for index in range(170):
                item = copy.deepcopy(sample)
                item['id'] = 100 + index
                item['data']['characters'] = '山' + str(index)
                self.store.put(item)
            exact = copy.deepcopy(sample)
            exact['id'] = 999
            exact['data']['characters'] = '山169'
            exact['object'] = 'vocabulary'
            self.store.put(exact)
        self.assertEqual(999, self.engine.search('山169', 1)[0]['id'])

    def test_unicode_width_and_katakana_fold_for_reading(self):
        self.assertTrue(any(item['id'] == 2 for item in self.engine.search('ｻﾝ')))
        self.assertTrue(any(item['id'] == 2 for item in self.engine.search('ＳＡＮ', reading_query='さん')))
        self.assertTrue(any(item['id'] == 2 for item in self.engine.search('ＭＯＵＮＴＡＩＮ')))

    def test_romaji_hint_does_not_replace_english_query(self):
        results = self.engine.search('mountain', reading_query='もんたいん')
        self.assertEqual(2, results[0]['id'])
        self.assertEqual('exact', results[0]['match'])
        self.assertEqual([], self.engine.search('unmatched', reading_query='mountain'))

    def test_local_synonyms_and_pending_draft_override(self):
        self.store.put({'id': 30, 'object': 'study_material', 'data': {
            'subject_id': 2, 'meaning_synonyms': ['summit']}})
        self.assertEqual(2, self.engine.search('summit')[0]['id'])
        self.store.set('material_draft_2', {'meaning_synonyms': ['peak']})
        self.assertEqual([], self.engine.search('summit'))
        self.assertEqual(2, self.engine.search('peak')[0]['id'])
        self.store.set('material_draft_2', {'meaning_synonyms': []})
        self.assertEqual([], self.engine.search('peak'))

    def test_filters_are_local_and_preserve_access_boundaries(self):
        self.engine.pin(2, True)
        self.assertEqual([2], [x['id'] for x in self.engine.search('', filters={'state': 'saved'})])
        self.assertTrue(all(x['type'] == 'vocabulary' for x in self.engine.search('', filters={'type': 'vocabulary'})))
        self.assertTrue(all(x['assignment']['started_at'] for x in self.engine.search('', filters={'state': 'learned'})))
        item = self.store.subject(2)
        item['data']['hidden_at'] = stamp(NOW)
        self.store.put(item)
        self.assertEqual([], self.engine.search('mountain', filters={'state': 'saved'}))
        item['data']['hidden_at'] = None
        item['data']['level'] = 60
        self.store.put(item)
        user = self.store.get('user')
        user['data']['subscription']['max_level_granted'] = 3
        self.store.set('user', user)
        self.assertEqual([], self.engine.search('mountain', filters={'state': 'saved'}))

    def test_due_filter_excludes_pending_graded_cycle(self):
        self.assertEqual(5, len(self.engine.search('', filters={'state': 'due'})))
        completed = self.complete(limit=1)
        self.assertEqual(4, len(self.engine.search('', filters={'state': 'due'})))
        pending = self.store.rows('SELECT subject_id FROM outbox')[0][0]
        self.engine.pin(pending, True)
        self.assertTrue(self.engine.search('', filters={'state': 'saved'})[0]['pending'])

    def test_selection_surfaces_longest_contained_word(self):
        results = self.engine.search('火山が見えます。')
        self.assertEqual('火山', results[0]['characters'])
        self.assertEqual('in_selection', results[0]['match'])

    def test_literal_query_and_validation(self):
        for query in ('%', '_', '\\', 'meaning_synonyms', 'accepted_answer'):
            with self.subTest(query=query):
                self.assertEqual([], self.engine.search(query))
        self.assertEqual([], self.engine.search(''))
        for filters in ({'type': 'wrong'}, {'state': 'pending'}, ['saved']):
            with self.assertRaises(UserError):
                self.engine.search('山', filters=filters)
        with self.assertRaises(UserError):
            self.engine.search('山', limit='many')

    def test_subject_update_replaces_old_folded_content(self):
        subject = self.store.subject(2)
        subject['data']['characters'] = '丘'
        subject['data']['meanings'] = [{'meaning': 'Hill', 'accepted_answer': True}]
        subject['data']['readings'] = [{'reading': 'キュウ', 'accepted_answer': True}]
        self.store.put(subject)
        self.assertEqual([], self.engine.search('mountain'))
        self.assertEqual([], self.engine.search('さん'))
        for query in ('丘', 'ＨＩＬＬ', 'きゅう'):
            self.assertEqual(2, self.engine.search(query)[0]['id'])

    def test_subject_type_change_removes_its_old_form(self):
        subject = self.store.subject(2)
        subject['object'] = 'vocabulary'
        self.store.put(subject)
        self.assertIsNone(self.store.resource('kanji', 2))
        rows = self.store.rows("SELECT kind FROM search_documents WHERE id='2'")
        self.assertEqual(['vocabulary'], [row[0] for row in rows])
        self.assertEqual('vocabulary', self.engine.search('mountain')[0]['type'])

    def test_document_failure_rolls_back_authoritative_subject_update(self):
        original = self.store.subject(2)
        changed = copy.deepcopy(original)
        changed['data']['meanings'] = [{'meaning': 'changed', 'accepted_answer': True}]
        with patch.object(self.store, '_put_search_document', side_effect=RuntimeError('test interruption')):
            with self.assertRaises(RuntimeError):
                self.store.put(changed)
        self.assertEqual(original, self.store.subject(2))
        self.assertEqual([], self.engine.search('changed'))
        self.assertEqual(2, self.engine.search('mountain')[0]['id'])

    def test_direct_resource_deletion_removes_document_and_never_resurrects(self):
        self.store.execute("DELETE FROM resources WHERE kind='kanji' AND id='2'")
        self.assertEqual([], self.store.rows("SELECT id FROM search_documents WHERE id='2'"))
        self.assertEqual([], self.engine.search('mountain'))
        self.reopen()
        self.assertEqual([], self.store.rows("SELECT id FROM search_documents WHERE id='2'"))
        self.assertEqual([], self.engine.search('mountain'))

    def test_bulk_resource_deletion_clears_all_derived_account_content(self):
        self.assertGreater(self.store.rows('SELECT COUNT(*) FROM search_documents')[0][0], 0)
        self.store.execute('DELETE FROM resources')
        self.assertEqual(0, self.store.rows('SELECT COUNT(*) FROM search_documents')[0][0])
        self.reopen()
        self.assertEqual([], self.store.rows('SELECT * FROM search_documents'))

    def test_missing_search_table_and_indexes_migrate_without_losing_draft(self):
        self.engine.start('reviews', 1)
        self.engine.draft('preserved answer')
        self.store.execute('DROP INDEX search_characters')
        self.store.execute('DROP INDEX resource_search_identity')
        self.store.execute('DROP TABLE search_documents')
        self.store.execute('PRAGMA user_version=1')
        self.reopen()
        self.assertEqual(16, self.store.rows('SELECT COUNT(*) FROM search_documents')[0][0])
        indexes = {row[0] for row in self.store.rows("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertTrue({'search_characters', 'resource_search_identity'} <= indexes)
        self.assertEqual('preserved answer', self.engine.session_view()['draft'])
        self.assertEqual(2, self.engine.search('ＭＯＵＮＴＡＩＮ')[0]['id'])
        self.assertEqual(2, self.store.rows('PRAGMA user_version')[0][0])

    def test_normal_restart_reuses_documents_without_refolding_catalogue(self):
        with patch.object(Store, '_put_search_document', side_effect=AssertionError('unexpected rebuild')):
            self.reopen()
        self.assertEqual(2, self.engine.search('mountain')[0]['id'])

    def test_direct_access_change_is_checked_against_authoritative_resource(self):
        subject = self.store.subject(2)
        subject['data']['hidden_at'] = stamp(NOW)
        self.store.execute("UPDATE resources SET body=? WHERE kind='kanji' AND id='2'", (json.dumps(subject),))
        self.assertEqual([], self.engine.search('mountain'))
        subject['data']['hidden_at'] = None
        subject['data']['level'] = 60
        self.store.execute("UPDATE resources SET body=? WHERE kind='kanji' AND id='2'", (json.dumps(subject),))
        user = self.store.get('user')
        user['data']['subscription']['max_level_granted'] = 3
        self.store.set('user', user)
        self.assertEqual([], self.engine.search('mountain'))

    def test_assignment_deletion_updates_status_filters(self):
        self.assertTrue(self.engine.search('mountain', filters={'state': 'learned'}))
        self.store.execute("DELETE FROM resources WHERE kind='assignment' AND id='102'")
        self.assertEqual([], self.engine.search('mountain', filters={'state': 'learned'}))
        self.assertEqual([], self.engine.search('mountain', filters={'state': 'due'}))
        self.assertEqual(2, self.engine.search('mountain')[0]['id'])
