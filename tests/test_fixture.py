import json
import unittest
from pathlib import Path


class ContributorFixtureTests(unittest.TestCase):
    def test_minimal_geojson_is_valid_and_fictional(self):
        path = Path(__file__).parent / 'fixtures' / 'outback_minerals_minimal.geojson'
        collection = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(collection['type'], 'FeatureCollection')
        self.assertEqual(len(collection['features']), 3)
        self.assertEqual(
            {feature['geometry']['type'] for feature in collection['features']},
            {'Point', 'LineString', 'Polygon'},
        )
        self.assertIn('IBRC26041', path.read_text(encoding='utf-8'))
