from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mqtt'))
import app
from solar import aggregate, topic_map

PREFIX = 'shellies/shellyem3-C8C9A316D627'
START = datetime(2026, 10, 14, 10)


def row(phase, metric, value, seconds=0, ident=1, prefix=PREFIX):
    return dict(id=ident, topic=f'{prefix}/emeter/{phase}/{metric}',
                payload=value, received_at=START + timedelta(seconds=seconds))


class SolarTests(unittest.TestCase):
    def summarize(self, rows):
        return aggregate(iter(rows), PREFIX, START, START + timedelta(hours=1), 10)

    def test_all_three_phases_and_correct_power_topic(self):
        rows = [row(p, m, str((p+1)*10).encode())
                for p in range(3) for m in ('power', 'current', 'voltage')]
        result = self.summarize(rows)
        self.assertEqual(result['samples'], 9)
        self.assertEqual(len(topic_map(PREFIX)), 15)
        for phase in result['phases']:
            for metric in ('power', 'current', 'voltage'):
                self.assertEqual(phase['series'][metric][0]['value'], phase['phase'] * 10)
        result = self.summarize([row(0, 'current', b'2'), row(0, 'power', b'-450')])
        self.assertEqual(result['phases'][0]['latest']['power']['value'], -450)
        self.assertEqual(result['phases'][0]['latest']['current']['value'], 2)

    def test_energy_wh_to_kwh_and_latest_not_sum(self):
        result = self.summarize([row(0, 'total', b'2500', 20), row(0, 'total', b'1500', 10),
                                 row(0, 'total_returned', b'6000', 25)])
        phase = result['phases'][0]
        self.assertEqual(phase['latest']['total']['value'], 2.5)
        self.assertEqual(phase['latest']['total_returned']['value'], 6)
        self.assertNotIn('total', phase['series'])
        self.assertEqual(result['phases'][1]['latest'], {})

    def test_bucket_averages_gaps_and_tie_break(self):
        result = self.summarize([row(0, 'power', b'20', 1), row(0, 'power', b'40', 2),
                                 row(0, 'power', b'0', 35, 3), row(0, 'power', b'4', 35, 2)])
        points = result['phases'][0]['series']['power']
        self.assertEqual([p['value'] for p in points], [30, 2])
        self.assertEqual(result['phases'][0]['latest']['power']['value'], 0)
        self.assertTrue(points[0]['time'].endswith('+00:00'))

    def test_invalid_and_unrelated_messages(self):
        rows = [row(0, 'power', value) for value in (b'NaN', b'inf', b'1e999', b'{}', b'', b'\xff')]
        rows += [row(0, 'power', b'1', prefix='other'), row(3, 'power', b'1'),
                 row(0, 'power', b'1', -1), row(0, 'power', b'1', 3600)]
        result = self.summarize(rows)
        self.assertEqual(result['samples'], 0)
        self.assertEqual(result['skipped'], 6)
        self.assertEqual(result['phases'][0]['series']['power'], [])

    @patch.object(app, 'database')
    def test_endpoint_reads_in_batches_and_validates_range(self, database):
        cursor = database.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        # Use a fresh UTC timestamp without relying on the machine timezone.
        from datetime import timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        sample = row(1, 'voltage', b'231.2')
        sample['received_at'] = now
        cursor.fetchmany.side_effect = [[sample], []]
        response = app.app.test_client().get('/api/solar?hours=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['phases'][1]['latest']['voltage']['value'], 231.2)
        self.assertEqual(response.json['bucket_seconds'], 10)
        self.assertIn('received_at >= %s', cursor.execute.call_args.args[0])
        self.assertEqual(len(cursor.execute.call_args.args[1]), 17)
        for value in ('0', '25', 'oops'):
            self.assertEqual(app.app.test_client().get('/api/solar?hours=' + value).status_code, 400)

    def test_pages_and_assets(self):
        client = app.app.test_client()
        for path in ('/', '/messages', '/static/solar.js', '/static/solar.css'):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()


if __name__ == '__main__':
    unittest.main()
