import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Stub out discord/pytz before importing top_issues, since bot.run() fires at
# module level and those packages may not be installed in the test environment.
for _mod in ('discord', 'discord.ext', 'discord.ext.commands', 'pytz'):
    sys.modules.setdefault(_mod, MagicMock())
sys.argv = ['top_issues.py', 'dummy_token']

import top_issues  # noqa: E402

sys.argv = sys.argv[
    :1
]  # restore so unittest doesn't treat 'dummy_token' as a test name
from top_issues import (
    BIN_MAGIC,
    BIN_VERSION,
    Issue,
    Tag,
    _decode_str_table,
    _encode_str_table,
    _encode_delta_entry,
    _issues_to_state,
    _read_bin_file,
    update_snapshots_bin,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def make_issue(id_: int, status: str, tags: list[str]) -> Issue:
    return Issue(
        id=id_,
        name=f'Issue {id_}',
        status=status,
        url=f'https://example.com/{id_}',
        votes=0,
        tags=[Tag(name=t, emoji='x') for t in tags],
        message_count=0,
    )


def write_bin(path: Path, statuses: list, tags: list, snapshots: list) -> None:
    """Write a fresh .bin file from a list of (timestamp_ms, [Issue]) pairs."""
    header = (
        BIN_MAGIC
        + bytes([BIN_VERSION])
        + _encode_str_table(statuses)
        + _encode_str_table(tags)
    )
    status_idx = {s: i for i, s in enumerate(statuses)}
    tag_idx = {t: i for i, t in enumerate(tags)}
    prev, body = {}, b''
    for ts_ms, issues in snapshots:
        curr = _issues_to_state(issues, status_idx, tag_idx)
        body += _encode_delta_entry(ts_ms, prev, curr)
        prev = curr
    path.write_bytes(header + body)


# ── string table ─────────────────────────────────────────────────────────────


class TestStringTable(unittest.TestCase):
    def test_round_trip_empty(self):
        buf = _encode_str_table([])
        result, offset = _decode_str_table(buf, 0)
        self.assertEqual(result, [])
        self.assertEqual(offset, 1)

    def test_round_trip(self):
        strings = ['closed', 'open', 'pending', 'unknown']
        buf = _encode_str_table(strings)
        result, _ = _decode_str_table(buf, 0)
        self.assertEqual(result, strings)

    def test_appended_after_other_data(self):
        prefix = b'\xff\xfe'
        buf = prefix + _encode_str_table(['a', 'bb'])
        result, offset = _decode_str_table(buf, len(prefix))
        self.assertEqual(result, ['a', 'bb'])
        self.assertEqual(offset, len(buf))


# ── _read_bin_file ────────────────────────────────────────────────────────────


class TestReadBinFile(unittest.TestCase):
    def test_nonexistent_returns_empty(self):
        statuses, tags, raw, state = _read_bin_file(Path('/tmp/_no_such_file_.bin'))
        self.assertEqual((statuses, tags, raw, state), ([], [], b'', {}))

    def test_initial_snapshot_state(self):
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            path = Path(f.name)
        issue = make_issue(101, 'open', ['Blocker', 'Crash'])
        write_bin(path, ['closed', 'open'], ['Blocker', 'Crash'], [(1000, [issue])])

        statuses, tags, _, state = _read_bin_file(path)
        self.assertIn(101, state)
        s_int, tb = state[101]
        self.assertEqual(statuses[s_int], 'open')
        self.assertTrue(tb & (1 << tags.index('Blocker')))
        self.assertTrue(tb & (1 << tags.index('Crash')))

    def test_delta_removal_applied(self):
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            path = Path(f.name)
        issues = [make_issue(1, 'open', []), make_issue(2, 'open', [])]
        write_bin(
            path,
            ['open'],
            [],
            [
                (1000, issues),
                (2000, [make_issue(1, 'open', [])]),  # issue 2 removed
            ],
        )
        _, _, _, state = _read_bin_file(path)
        self.assertIn(1, state)
        self.assertNotIn(2, state)

    def test_delta_status_change(self):
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            path = Path(f.name)
        write_bin(
            path,
            ['closed', 'open'],
            [],
            [
                (1000, [make_issue(1, 'open', [])]),
                (2000, [make_issue(1, 'closed', [])]),
            ],
        )
        statuses, _, _, state = _read_bin_file(path)
        self.assertEqual(statuses[state[1][0]], 'closed')


# ── update_snapshots_bin ─────────────────────────────────────────────────────


class TestUpdateSnapshotsBin(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_update(self, issues_per_channel: dict):
        with patch.object(top_issues, 'root_dir', self.root):
            update_snapshots_bin(issues_per_channel)

    def bin_path(self, channel: str) -> Path:
        return self.root / f'snapshot-{channel}.bin'

    def read_state(self, channel: str):
        return _read_bin_file(self.bin_path(channel))

    # basic lifecycle

    def test_creates_file_on_first_run(self):
        self.run_update({'bugs': [make_issue(1, 'open', ['Blocker'])]})
        self.assertTrue(self.bin_path('bugs').exists())

    def test_unchanged_does_not_grow_file(self):
        issues = [make_issue(1, 'open', ['Blocker'])]
        self.run_update({'bugs': issues})
        size = self.bin_path('bugs').stat().st_size
        self.run_update({'bugs': issues})
        self.assertEqual(self.bin_path('bugs').stat().st_size, size)

    def test_changed_status_appends(self):
        self.run_update({'bugs': [make_issue(1, 'open', [])]})
        size = self.bin_path('bugs').stat().st_size
        self.run_update({'bugs': [make_issue(1, 'closed', [])]})
        self.assertGreater(self.bin_path('bugs').stat().st_size, size)

    def test_new_issue_appends(self):
        self.run_update({'bugs': [make_issue(1, 'open', [])]})
        size = self.bin_path('bugs').stat().st_size
        self.run_update(
            {'bugs': [make_issue(1, 'open', []), make_issue(2, 'open', [])]}
        )
        self.assertGreater(self.bin_path('bugs').stat().st_size, size)

    # state correctness

    def test_removed_issue_absent_from_state(self):
        self.run_update(
            {'bugs': [make_issue(1, 'open', []), make_issue(2, 'open', [])]}
        )
        self.run_update({'bugs': [make_issue(1, 'open', [])]})
        _, _, _, state = self.read_state('bugs')
        self.assertIn(1, state)
        self.assertNotIn(2, state)

    def test_state_correct_after_multiple_runs(self):
        self.run_update(
            {'bugs': [make_issue(1, 'open', ['Blocker']), make_issue(2, 'pending', [])]}
        )
        self.run_update(
            {'bugs': [make_issue(1, 'closed', []), make_issue(3, 'open', ['Crash'])]}
        )

        statuses, tags, _, state = self.read_state('bugs')
        self.assertNotIn(2, state)

        s1, tb1 = state[1]
        self.assertEqual(statuses[s1], 'closed')
        self.assertEqual(tb1, 0)

        s3, tb3 = state[3]
        self.assertEqual(statuses[s3], 'open')
        self.assertTrue(tb3 & (1 << tags.index('Crash')))

    # string table extension

    def test_new_tag_preserved_in_table_and_state(self):
        self.run_update({'bugs': [make_issue(1, 'open', ['Blocker'])]})
        self.run_update({'bugs': [make_issue(1, 'open', ['Blocker', 'Crash'])]})

        statuses, tags, _, state = self.read_state('bugs')
        self.assertIn('Crash', tags)
        _, tb = state[1]
        self.assertTrue(tb & (1 << tags.index('Crash')))

    def test_existing_tag_bits_survive_table_extension(self):
        self.run_update({'bugs': [make_issue(1, 'open', ['Blocker'])]})
        statuses_before, tags_before, _, _ = self.read_state('bugs')
        blocker_bit_before = tags_before.index('Blocker')

        self.run_update(
            {
                'bugs': [
                    make_issue(1, 'open', ['Blocker']),
                    make_issue(2, 'open', ['Crash']),
                ]
            }
        )
        statuses_after, tags_after, _, state = self.read_state('bugs')

        # Blocker's bit position must not have shifted
        self.assertEqual(tags_after.index('Blocker'), blocker_bit_before)
        _, tb1 = state[1]
        self.assertTrue(tb1 & (1 << blocker_bit_before))

    def test_new_status_added_to_table(self):
        self.run_update({'bugs': [make_issue(1, 'open', [])]})
        self.run_update({'bugs': [make_issue(1, 'unknown', [])]})

        statuses, _, _, state = self.read_state('bugs')
        self.assertIn('unknown', statuses)
        s1, _ = state[1]
        self.assertEqual(statuses[s1], 'unknown')

    # multiple channels independent

    def test_multiple_channels_written_independently(self):
        self.run_update(
            {
                'bugs': [make_issue(1, 'open', ['Blocker'])],
                'features': [make_issue(2, 'open', ['Simple'])],
            }
        )
        self.assertTrue(self.bin_path('bugs').exists())
        self.assertTrue(self.bin_path('features').exists())

        _, _, _, bugs_state = self.read_state('bugs')
        _, _, _, features_state = self.read_state('features')
        self.assertIn(1, bugs_state)
        self.assertNotIn(2, bugs_state)
        self.assertIn(2, features_state)
        self.assertNotIn(1, features_state)


if __name__ == '__main__':
    unittest.main()
