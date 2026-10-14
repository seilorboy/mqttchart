"""Run with: python -m unittest discover -s tests -p test_mqtt_app.py"""
from datetime import datetime
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mqtt"))
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location(
    "mqtt_archive", Path(__file__).resolve().parents[1] / "mqtt" / "app.py"
)
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class MqttArchiveTests(unittest.TestCase):
    def test_payload_roundtrip(self):
        for payload, encoding, expected in [
            (b'{"energy_kwh":1}', 'utf-8', '{"energy_kwh":1}'),
            (b'\xff\x00', 'base64', '/wA='),
            (b'', 'utf-8', ''),
        ]:
            row = archive.serialize(dict(received_at=datetime(2026, 1, 1), payload=payload))
            self.assertEqual(row['encoding'], encoding)
            self.assertEqual(row['payload'], expected)
            self.assertTrue(row['received_at'].endswith('+00:00'))

    @patch.object(archive, 'database')
    def test_commit_precedes_ack(self, database):
        conn = database.return_value.__enter__.return_value
        client = MagicMock()
        order = MagicMock()
        order.attach_mock(conn.commit, 'commit')
        order.attach_mock(client.ack, 'ack')
        archive.on_message(client, None, SimpleNamespace(
            topic='han/test', payload=b'123', qos=1, retain=False, mid=42,
        ))
        self.assertEqual([call[0] for call in order.mock_calls], ['commit', 'ack'])
        client.ack.assert_called_once_with(42, 1)

    @patch.object(archive.os, '_exit', side_effect=SystemExit)
    @patch.object(archive, 'database')
    def test_failed_commit_is_not_acknowledged(self, database, exit_process):
        database.return_value.__enter__.return_value.commit.side_effect = archive.mysql.connector.Error('failed')
        client = MagicMock()
        with self.assertRaises(SystemExit):
            archive.on_message(client, None, SimpleNamespace(
                topic='han/test', payload=b'123', qos=1, retain=False, mid=42,
            ))
        client.ack.assert_not_called()
        exit_process.assert_called_once_with(1)

    @patch.object(archive, 'database')
    def test_api_limits_and_serialization(self, database):
        cur = database.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [dict(id=1, received_at=datetime(2026, 1, 1), payload=b'hello')]
        client = archive.app.test_client()
        response = client.get('/api/messages?limit=99999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['messages'][0]['payload'], 'hello')
        self.assertEqual(cur.execute.call_args.args[1], (500,))
        self.assertEqual(client.get('/api/messages?limit=oops').status_code, 400)

    @patch.object(archive, 'database', side_effect=archive.mysql.connector.Error('secret'))
    def test_database_outage(self, database):
        response = archive.app.test_client().get('/api/messages')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.text)


if __name__ == '__main__':
    unittest.main()
