"""Read Shelly 3EM scalar topics from the existing MQTT archive."""
from datetime import timedelta, timezone
import math

METRICS = ('power', 'current', 'voltage', 'total', 'total_returned')
BUCKETS = {1: 10, 6: 60, 24: 300}


def topic_map(prefix):
    return {f'{prefix}/emeter/{phase}/{metric}': (phase, metric)
            for phase in range(3) for metric in METRICS}


def aggregate(rows, prefix, start, end, bucket_seconds):
    topics = topic_map(prefix)
    phases = [{'phase': i + 1, 'latest': {},
               'series': {m: [] for m in METRICS[:3]}} for i in range(3)]
    buckets = {}
    latest_keys = {}
    accepted = skipped = 0
    for row in rows:
        mapping = topics.get(row['topic'])
        timestamp = row['received_at']
        if mapping is None or not start <= timestamp < end:
            continue
        try:
            value = float(row['payload'])
        except (ValueError, TypeError, OverflowError):
            skipped += 1
            continue
        if not math.isfinite(value):
            skipped += 1
            continue
        phase, metric = mapping
        accepted += 1
        key = (phase, metric)
        order = (timestamp, row['id'])
        if key not in latest_keys or order > latest_keys[key]:
            latest_keys[key] = order
            phases[phase]['latest'][metric] = {
                'value': value / 1000 if metric.startswith('total') else value,
                'time': timestamp.replace(tzinfo=timezone.utc).isoformat(),
            }
        if metric in METRICS[:3]:
            slot = int((timestamp - start).total_seconds() // bucket_seconds)
            key = (phase, metric, slot)
            count, mean = buckets.get(key, (0, 0.0))
            # Weighted form avoids an overflowing intermediate sum.
            buckets[key] = (count + 1, mean * (count / (count + 1)) + value / (count + 1))
    for (phase, metric, slot), (count, mean) in sorted(buckets.items()):
        timestamp = start + timedelta(seconds=slot * bucket_seconds)
        phases[phase]['series'][metric].append({
            'time': timestamp.replace(tzinfo=timezone.utc).isoformat(),
            'value': mean, 'count': count,
        })
    return {'phases': phases, 'samples': accepted, 'skipped': skipped,
            'bucket_seconds': bucket_seconds, 'device': prefix,
            'start': start.replace(tzinfo=timezone.utc).isoformat(),
            'end': end.replace(tzinfo=timezone.utc).isoformat()}
