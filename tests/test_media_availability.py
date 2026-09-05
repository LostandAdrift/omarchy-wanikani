"""All study surfaces agree on the minimum owned media-file contract."""
import unittest

from test_backend import EngineFixture, NOW, UserError
from wanikani.common import stamp
from wanikani.media_files import available_file
from wanikani.practice import catalogue
from wanikani.readiness import calculate


class MediaAvailabilityTests(EngineFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.media = self.path.parent / 'media'
        self.media.mkdir()
        subject = self.store.subject(1)
        subject['data']['characters'] = None
        subject['data']['character_images'] = [{'url': 'https://wanikani.com/authored.svg'}]
        self.store.put(subject)
        self.engine.pin(1, True)

    def record(self, path, url='https://wanikani.com/authored.svg'):
        self.store.execute('INSERT OR REPLACE INTO media VALUES(?,?,?,?)', (url, str(path), 512, NOW))

    def test_missing_empty_outside_nested_and_symlink_files_are_unavailable_everywhere(self):
        empty = self.media / 'empty.svg'
        empty.write_bytes(b'')
        outside = self.path.parent / 'external.svg'
        outside.write_bytes(b'authored outside fixture')
        target = self.media / 'target.svg'
        target.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        symlink = self.media / 'link.svg'
        symlink.symlink_to(target)
        nested = self.media / 'nested'
        nested.mkdir()
        child = nested / 'nested.svg'
        child.write_bytes(b'authored nested fixture')
        for path in (empty, outside, symlink, nested, child, self.media / 'missing.svg'):
            with self.subTest(path=path.name):
                self.record(path)
                before = list(self.store.db.iterdump())
                self.assertIsNone(available_file(self.media, str(path)))
                self.assertEqual([], self.engine.details(1)['images'])
                self.assertEqual(1, calculate(self.engine)['reviews']['missing_images'])
                for scope in ('all', 'page'):
                    item = catalogue(self.engine, 'saved', readiness_scope=scope)['items'][0]
                    self.assertFalse(item['ready'])
                    self.assertEqual([], item['images'])
                with self.assertRaises(UserError) as raised:
                    self.engine.ensure_study_content(self.store.subject(1))
                self.assertEqual('content_unavailable', raised.exception.code)
                self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertTrue(symlink.is_symlink())
        self.assertTrue(outside.exists())

    def test_valid_alternate_is_available_for_due_and_upcoming_reviews(self):
        first = self.media / 'empty.svg'
        first.write_bytes(b'')
        alternate = self.media / 'alternate.svg'
        alternate.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.record(first)
        self.record(alternate, 'https://wanikani.com/alternate.svg')
        subject = self.store.subject(1)
        subject['data']['character_images'].append({'url': 'https://wanikani.com/alternate.svg'})
        self.store.put(subject)
        self.assertEqual([alternate.as_uri()], self.engine.details(1)['images'])
        self.engine.ensure_study_content(subject)
        self.assertTrue(catalogue(self.engine, 'saved')['items'][0]['ready'])
        self.assertEqual(0, calculate(self.engine)['reviews']['missing_images'])
        assignment = self.store.related('assignment', 1)
        assignment['data']['available_at'] = stamp(NOW + 3600)
        self.store.put(assignment)
        self.assertEqual(0, calculate(self.engine)['upcoming_reviews']['missing_images'])
        alternate.write_bytes(b'')
        self.assertEqual(1, calculate(self.engine)['upcoming_reviews']['missing_images'])

    def test_optional_audio_uses_the_same_nonempty_regular_file_check(self):
        url = 'https://wanikani.com/authored.mp3'
        subject = self.store.subject(4)
        subject['data']['pronunciation_audios'] = [{'url': url}]
        self.store.put(subject)
        empty = self.media / 'empty.mp3'
        empty.write_bytes(b'')
        self.record(empty, url)
        self.assertEqual([], self.engine.details(4)['audio'])
        result = calculate(self.engine)['reviews']
        self.assertEqual((1, 0), (result['audio_total'], result['audio_cached']))
        empty.write_bytes(b'authored media byte fixture')
        self.assertEqual([empty.as_uri()], [item['url'] for item in self.engine.details(4)['audio']])
        self.assertEqual(1, calculate(self.engine)['reviews']['audio_cached'])

    def test_malformed_relative_and_nul_paths_do_not_raise_or_become_available(self):
        for path in (None, False, 17, [], {}, 'relative.svg', str(self.media / 'nul\x00.svg')):
            with self.subTest(path=path):
                self.assertIsNone(available_file(self.media, path))


if __name__ == '__main__':
    unittest.main()
