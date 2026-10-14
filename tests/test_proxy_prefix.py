from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mqtt'))
import app
from waitress.proxy_headers import proxy_headers_middleware
from werkzeug.test import Client
from werkzeug.wrappers import Response


class References(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.urls = []
        self.scripts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.urls.extend(attrs[k] for k in ('href', 'src', 'data-api-url') if k in attrs)
        if tag == 'script':
            self.scripts.append(attrs.get('src'))


class PrefixTests(unittest.TestCase):
    @patch.object(app, 'database')
    def test_navigation_assets_and_api_with_and_without_prefix(self, database):
        cursor = database.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchmany.return_value = []
        cursor.fetchall.return_value = []
        # Exercise Waitress' default header handling as well as Flask/ProxyFix.
        client = Client(proxy_headers_middleware(app.app), Response)
        for prefix in ('', '/mqttchart'):
            headers = {'X-Forwarded-Prefix': prefix} if prefix else {}
            for path, api in (('/', '/api/solar'), ('/messages', '/api/messages')):
                response = client.get(path, headers=headers, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
                self.assertEqual(response.status_code, 200)
                refs = References(response.text)
                self.assertIn(prefix + api, refs.urls)
                self.assertTrue(refs.scripts)
                self.assertTrue(all(refs.scripts), 'No inline scripts: compatible with script-src self')
                for url in refs.urls:
                    if prefix:
                        self.assertTrue(url.startswith(prefix + '/'), url)
                    # Nginx strips /mqttchart/ before forwarding the request.
                    upstream = url[len(prefix):]
                    result = client.get(upstream, headers=headers, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
                    self.assertEqual(result.status_code, 200, url)
                    result.close()
                response.close()

    def test_only_prefix_header_is_trusted(self):
        with app.app.test_client() as client:
            response = client.get('/', headers={'X-Forwarded-Prefix': '/mqttchart',
                                                'X-Forwarded-Host': 'untrusted.example'})
            self.assertNotIn('untrusted.example', response.text)
            self.assertIn('/mqttchart/static/solar.js', response.text)


if __name__ == '__main__':
    unittest.main()
