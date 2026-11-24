import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collar_qgis.catalogue import OPERATIONAL_LAYERS, layer_features, separated_specs

POLYGON = {
    'type': 'Polygon',
    'coordinates': [[[121, -30], [121.01, -30], [121.01, -30.01], [121, -30]]],
}


class CatalogueTests(unittest.TestCase):
    def test_same_geometry_is_partitioned_by_purpose_and_rigs_are_excluded(self):
        features = [
            {
                'id': kind,
                'geometry': POLYGON,
                'properties': {'entity_type': kind, 'rigCode': 'RC01'},
            }
            for kind in ['proposed_pad', 'proposed_sump', 'disturbance', 'rig']
        ]
        for spec in OPERATIONAL_LAYERS[1:]:
            rows = layer_features(spec, features)
            self.assertEqual([row['id'] for row in rows], [spec['entityType']])
            self.assertEqual(rows[0]['geometry']['type'], 'MultiPolygon')
            self.assertNotIn('rigCode', rows[0]['properties'])
        self.assertEqual(features[0]['geometry']['type'], 'Polygon')
        self.assertEqual(features[0]['properties']['rigCode'], 'RC01')

    def test_legacy_sources_expand_into_four_stable_identities(self):
        specs = separated_specs(
            {'id': 'operational', 'source': '/api/v1/qgis/projects/p/operational'}
        )
        self.assertEqual(
            [item['id'] for item in specs],
            ['holes', 'proposed_pad', 'proposed_sump', 'disturbance'],
        )
        self.assertTrue(all(not item['editable'] for item in specs))
        self.assertTrue(specs[1]['source'].endswith('?layer=proposed_pad'))
        spec = {'id': 'access_track', 'source': '/features'}
        self.assertEqual(separated_specs(spec), [spec])

    def test_user_reference_attributes_are_not_removed_as_operational_data(self):
        feature = {
            'id': 'custom',
            'geometry': POLYGON,
            'properties': {'rigCode': 'custom reference value'},
        }
        self.assertEqual(layer_features({'id': 'cloud:custom'}, [feature]), [feature])
