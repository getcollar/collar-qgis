import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'sync', Path(__file__).parents[1] / 'collar_qgis' / 'sync.py'
)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def feature(**values):
    return {
        'id': 'f',
        'revision': 1,
        'kind': 'marker',
        'name': 'IBRC26042',
        'notes': None,
        'editable': True,
        'geometry': {'type': 'Point', 'coordinates': [121, -30]},
        **values,
    }


class SyncTests(unittest.TestCase):
    def test_read_only_fields_do_not_become_changes(self):
        self.assertEqual(
            sync.changes_between(
                {'f': feature()}, {'f': feature(revision=2, state='drilling')}, {}
            ),
            [],
        )

    def test_retry_identity_survives_serialisation_and_changes_on_payload_edit(self):
        identities = {}
        before = {'f': feature()}
        edited = {'f': feature(name='Changed')}
        first = sync.changes_between(before, edited, identities)
        import json

        self.assertEqual(
            sync.changes_between(before, edited, json.loads(json.dumps(identities))), first
        )
        second = sync.changes_between(before, {'f': feature(name='Changed again')}, identities)
        self.assertNotEqual(first[0][1]['changeId'], second[0][1]['changeId'])

    def test_added_updated_deleted_and_applied_conflicts(self):
        before = {'f': feature(), 'removed': feature(id='removed')}
        current = {'f': feature(name='Changed'), 'new': feature(id=None, revision=None)}
        pending = sync.changes_between(before, current, {})
        self.assertEqual([c['action'] for _, c in pending], ['update', 'create', 'delete'])
        results = [
            {
                'changeId': c['changeId'],
                'status': 'conflict' if key == 'f' else 'applied',
                'id': key,
                'revision': 2,
            }
            for key, c in pending
        ]
        after = sync.acknowledge(before, pending, results)
        self.assertEqual(after['f'], before['f'])
        self.assertNotIn('removed', after)
        self.assertEqual(after['new']['id'], 'new')
        self.assertEqual(
            len(sync.changes_between(after, {'f': current['f'], 'new': after['new']}, {})), 1
        )

    def test_acknowledgement_retains_edits_made_during_network_request(self):
        before = {'f': feature()}
        submitted = sync.changes_between(before, {'f': feature(name='Sent')}, {})
        after = sync.acknowledge(
            before,
            submitted,
            [
                {
                    'changeId': submitted[0][1]['changeId'],
                    'status': 'applied',
                    'id': 'f',
                    'revision': 2,
                }
            ],
        )
        remaining = sync.changes_between(after, {'f': feature(name='Later')}, {})
        self.assertEqual(remaining[0][1]['revision'], 2)
        self.assertEqual(remaining[0][1]['attributes']['name'], 'Later')

    def test_protected_edit_or_delete_never_publish(self):
        for current in [{}, {'f': feature(name='Changed')}]:
            with self.assertRaises(ValueError):
                sync.changes_between({'f': feature(editable=False)}, current, {})


if __name__ == '__main__':
    unittest.main()


class BatchTests(unittest.TestCase):
    def test_batches_respect_server_vertex_limits(self):
        queue = [
            (None, str(i), {'geometry': {'coordinates': [[121, -30] for _ in range(1000)]}})
            for i in range(8)
        ]
        self.assertEqual(sync.batch_length(queue), 5)
        with self.assertRaises(ValueError):
            sync.batch_length([(None, 'large', {'geometry': {'coordinates': [[121, -30]] * 1001}})])
        track_queue = [
            (
                None,
                't',
                {
                    'kind': 'managed_tracks',
                    'geometry': {'coordinates': [[121, -30] for _ in range(5000)]},
                },
            )
        ]
        self.assertEqual(sync.batch_length(track_queue), 1)
        with self.assertRaises(ValueError):
            sync.batch_length(
                [
                    (
                        None,
                        'huge',
                        {
                            'kind': 'managed_tracks',
                            'geometry': {'coordinates': [[121, -30]] * 5001},
                        },
                    )
                ]
            )

    def test_managed_track_attributes_are_synced(self):
        before = {
            't': feature(
                kind='managed_tracks',
                type='access_track',
                stage='actual',
                status='published',
                widthM=4,
            )
        }
        current = {
            't': feature(
                kind='managed_tracks',
                type='drill_access',
                stage='proposed',
                status='published',
                widthM=5,
                name='Changed',
            )
        }
        pending = sync.changes_between(before, current, {})
        self.assertEqual(pending[0][1]['attributes']['type'], 'drill_access')
        self.assertEqual(pending[0][1]['attributes']['stage'], 'proposed')
        self.assertEqual(pending[0][1]['attributes']['widthM'], 5.0)
