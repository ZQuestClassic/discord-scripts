"""
Converts snapshot-bugs.json and snapshot-features.json to delta-encoded binary.

Output: snapshot-bugs.bin, snapshot-features.bin

Both files share the same status/tag string tables (built from all data) so
indices are consistent across channels.

─── File layout ──────────────────────────────────────────────────────────────

Header:
  magic          4 bytes   "SNAP"
  version        1 byte    = 2
  status_count   uint8
  [status_i]     uint8 len + UTF-8 bytes   (sorted)
  tag_count      uint8
  [tag_i]        uint8 len + UTF-8 bytes   (sorted)

Sequential snapshot entries (delta from previous state):
  timestamp_ms   uint64 LE
  entry_length   uint32 LE   bytes after this field
  added_count    uint16 LE   new issues + changed issues (upserted)
  removed_count  uint16 LE   issue IDs no longer present
  [issue_record × added_count]
  [uint64 × removed_count]

Issue record (17 bytes):
  id             uint64 LE
  status         uint8       index into status table
  tags           uint64 LE   bitmask; bit i set ↔ tag i present

─── Reading ──────────────────────────────────────────────────────────────────

Maintain a dict {id: (status, tag_bits)}. For each entry:
  1. delete removed IDs
  2. upsert added records
The dict is now the full snapshot state at timestamp_ms.
"""

import json
import os
import struct

MAGIC = b'SNAP'
VERSION = 2


def build_tables(all_snapshots: list) -> tuple[list, list]:
    statuses, tags = set(), set()
    for snap in all_snapshots:
        for issue in snap['issues']:
            statuses.add(issue.get('status', 'unknown'))
            for t in issue.get('tags', []):
                tags.add(t['name'])
    return sorted(statuses), sorted(tags)


def encode_string_table(strings: list) -> bytes:
    buf = bytes([len(strings)])
    for s in strings:
        b = s.encode('utf-8')
        buf += bytes([len(b)]) + b
    return buf


def encode_header(statuses: list, tags: list) -> bytes:
    return MAGIC + bytes([VERSION]) + encode_string_table(statuses) + encode_string_table(tags)


def issue_record(issue: dict, status_idx: dict, tag_idx: dict) -> tuple[int, int]:
    status = status_idx[issue.get('status', 'unknown')]
    tag_bits = 0
    for t in issue.get('tags', []):
        name = t['name']
        if name in tag_idx:
            tag_bits |= 1 << tag_idx[name]
    return status, tag_bits


def convert(snapshots: list, output_path: str,
            statuses: list, tags: list,
            status_idx: dict, tag_idx: dict) -> None:
    stat_added = stat_removed = stat_unchanged = 0

    with open(output_path, 'wb') as f:
        f.write(encode_header(statuses, tags))
        prev: dict[int, tuple[int, int]] = {}

        for snap in snapshots:
            timestamp_ms = int(snap['time'] * 1000)

            curr: dict[int, tuple[int, int]] = {
                iss['id']: issue_record(iss, status_idx, tag_idx)
                for iss in snap['issues']
            }

            added   = [(id_, s, tb) for id_, (s, tb) in curr.items() if prev.get(id_) != (s, tb)]
            removed = [id_ for id_ in prev if id_ not in curr]

            stat_added     += len(added)
            stat_removed   += len(removed)
            stat_unchanged += len(curr) - len(added)

            added_bytes   = b''.join(struct.pack('<QBQ', id_, s, tb) for id_, s, tb in added)
            removed_bytes = b''.join(struct.pack('<Q', id_) for id_ in removed)
            payload = struct.pack('<HH', len(added), len(removed)) + added_bytes + removed_bytes

            f.write(struct.pack('<QI', timestamp_ms, len(payload)))
            f.write(payload)

            prev = curr

    size = os.path.getsize(output_path)
    print(f'  {output_path}: {size:,} bytes ({size / 1_048_576:.2f} MB)')
    print(f'    upserted: {stat_added:,}   removed: {stat_removed:,}   unchanged: {stat_unchanged:,}')


def main() -> None:
    print('Loading...')
    with open('snapshot-bugs.json') as f:
        bugs = json.load(f)
    with open('snapshot-features.json') as f:
        features = json.load(f)

    print('Building string tables from all data...')
    statuses, tags = build_tables(bugs + features)
    assert len(tags) <= 64, f'Too many tags for uint64 bitmask: {len(tags)}'
    print(f'  {len(statuses)} statuses: {statuses}')
    print(f'  {len(tags)} tags: {tags}')

    status_idx = {s: i for i, s in enumerate(statuses)}
    tag_idx    = {t: i for i, t in enumerate(tags)}

    print()
    convert(bugs,     'snapshot-bugs.bin',     statuses, tags, status_idx, tag_idx)
    convert(features, 'snapshot-features.bin', statuses, tags, status_idx, tag_idx)


if __name__ == '__main__':
    main()
