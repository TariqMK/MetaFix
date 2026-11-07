"""Update check tests use a fake GitHub response and never go online."""
import unittest
from unittest.mock import patch

from metafix import create_app, updates

PAGE = 'https://github.com/TariqMK/MetaFix/releases/tag/v1.4.0'


def release(tag='v1.4.0', url=PAGE):
    return lambda: {'tag_name': tag, 'html_url': url}


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        updates._last_release_url = None

    def test_newer_release_found(self):
        self.assertEqual(updates.check('1.3.9', release()), {'current': '1.3.9', 'latest': '1.4.0', 'newer': True})

    def test_same_or_older_release_is_up_to_date(self):
        self.assertFalse(updates.check('1.4.0', release())['newer'])
        self.assertFalse(updates.check('1.10.0', release())['newer'])

    def test_dev_build_sees_any_release_as_newer(self):
        self.assertTrue(updates.check('0.0.0+dev', release())['newer'])

    def test_network_failure_is_a_readable_error(self):
        def offline():
            raise OSError('no network')
        with self.assertRaisesRegex(ValueError, 'Could not reach GitHub'):
            updates.check('1.0.0', offline)

    def test_unexpected_release_url_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'could not read'):
            updates.check('1.0.0', release(url='https://example.com/evil'))

    def test_open_only_after_newer_release_found(self):
        with self.assertRaisesRegex(ValueError, 'Check for updates first'):
            updates.open_release_page()
        updates.check('1.0.0', release())
        with patch.object(updates.webbrowser, 'open') as opened:
            updates.open_release_page()
        opened.assert_called_once_with(PAGE)

    def test_route_does_not_wait_for_session_lock(self):
        from metafix.session import session_lock
        client = create_app().test_client()
        with patch.object(updates, 'fetch_latest', release()):
            session_lock.acquire()
            try:
                response = client.post('/api/update/check', json={})
            finally:
                session_lock.release()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['newer'])


if __name__ == '__main__':
    unittest.main()
