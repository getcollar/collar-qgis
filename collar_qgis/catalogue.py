"""Stable layer identities across discovery, old projects, and refresh."""

import copy

OPERATIONAL_LAYERS = [
    {'id': 'holes', 'name': 'Drillholes', 'entityType': 'hole', 'geometry': 'Point'},
    {
        'id': 'proposed_pad',
        'name': 'Proposed pads',
        'entityType': 'proposed_pad',
        'geometry': 'MultiPolygon',
    },
    {
        'id': 'proposed_sump',
        'name': 'Proposed sumps',
        'entityType': 'proposed_sump',
        'geometry': 'MultiPolygon',
    },
    {
        'id': 'disturbance',
        'name': 'Recorded disturbance',
        'entityType': 'disturbance',
        'geometry': 'MultiPolygon',
    },
]
OPERATIONAL_IDS = {item['id'] for item in OPERATIONAL_LAYERS}


def separated_specs(spec):
    if spec['id'] != 'operational':
        return [spec]
    return [
        dict(item, editable=False, source=spec['source'].split('?')[0] + '?layer=' + item['id'])
        for item in OPERATIONAL_LAYERS
    ]


def layer_features(spec, features):
    selected = []
    operational = bool(spec.get('entityType')) or spec.get('id') == 'operational'
    for original in features:
        properties = original.get('properties', {})
        if operational and properties.get('entity_type') == 'rig':
            continue
        if spec.get('entityType') and properties.get('entity_type') != spec['entityType']:
            continue
        feature = copy.deepcopy(original)
        if operational:
            for key in [
                'assignedRigId',
                'rigCode',
                'rigStatus',
                'isCurrentRigHole',
                'rigNextHoleId',
            ]:
                feature.get('properties', {}).pop(key, None)
        # One polygon layer per purpose, even when footprints have multiple parts.
        if spec.get('geometry') == 'MultiPolygon' and feature['geometry']['type'] == 'Polygon':
            feature['geometry'] = {
                'type': 'MultiPolygon',
                'coordinates': [feature['geometry']['coordinates']],
            }
        selected.append(feature)
    return selected
