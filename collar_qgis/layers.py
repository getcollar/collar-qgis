"""Persistent local working copies; snapshots and connection IDs never contain tokens."""
import json
import hashlib
import os
import uuid
from pathlib import Path
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (QgsApplication, QgsProject, QgsVectorLayer, QgsFeature, QgsField,
                       QgsGeometry, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsSymbol, QgsRendererCategory,
                       QgsCategorizedSymbolRenderer, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, QgsDefaultValue, QgsJsonUtils, QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsSingleSymbolRenderer, QgsTextFormat, QgsTextBufferSettings, Qgis)
from .sync import changes_between, acknowledge

FIELDS = [('client_key', QVariant.String), ('id', QVariant.String), ('revision', QVariant.Int),
          ('kind', QVariant.String), ('name', QVariant.String), ('notes', QVariant.String),
          ('type', QVariant.String), ('stage', QVariant.String), ('status', QVariant.String),
          ('widthM', QVariant.Double),
          ('editable', QVariant.Bool), ('state', QVariant.String), ('qgis_revision', QVariant.String), ('details', QVariant.String)]

TRACK_TYPE_STYLES = {
    'access_track': {'color': '#43946e', 'width': 3},
    'drill_access': {'color': '#5375b9', 'width': 3},
    'haul_road': {'color': '#ae7939', 'width': 4},
    'walking_track': {'color': '#9060aa', 'width': 2, 'dashed': True},
    'other': {'color': '#737c75', 'width': 3},
}
TRACK_TYPE_LABELS = {
    'access_track': 'Access Track',
    'drill_access': 'Drill Access',
    'haul_road': 'Haul Road',
    'walking_track': 'Walking Track',
    'other': 'Other',
}


def snapshot(layer):
    result = {}
    for feature in layer.getFeatures():
        if not feature['client_key'] or str(feature['client_key']) == 'NULL' or feature['client_key'] in result:
            raise ValueError('Every local feature needs a unique client_key. Use the QGIS feature form defaults.')
        row = {name: feature[name] for name, _ in FIELDS}
        for name in row:
            if row[name] is None or str(row[name]) == 'NULL':
                row[name] = None
        row['geometry'] = json.loads(feature.geometry().asJson(15))
        result[feature['client_key']] = row
    return result


def stored(layer, key, default):
    return json.loads(layer.customProperty('collar/' + key, json.dumps(default)))


def pending(layer):
    identities = stored(layer, 'identities', {})
    changes = changes_between(stored(layer, 'baseline', {}), snapshot(layer), identities)
    layer.setCustomProperty('collar/identities', json.dumps(identities))
    return changes


def connected_layers(organisation=None, project=None):
    return [layer for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty('collar/managed', False)
            and not layer.customProperty('collar/legacy_archived', False)
            and (organisation is None or layer.customProperty('collar/organisation') == organisation)
            and (project is None or layer.customProperty('collar/project') == project)]


def dirty(layer):
    return layer.isEditable() or (not layer.readOnly() and bool(pending(layer)))


def add_features(layer, features, kind, editing=False):
    additions = []
    for item in features:
        p = item.get('properties', {})
        feature = QgsFeature(layer.fields())
        geometry = QgsJsonUtils.geometryFromGeoJson(json.dumps(item['geometry']))
        if geometry.isEmpty():
            raise ValueError('A Collar feature has empty geometry')
        feature.setGeometry(geometry)
        identifier = str(item.get('id') or p.get('id') or uuid.uuid4())
        width = p.get('widthM')
        if width is None:
            width = p.get('width_m')
        values = [
            identifier,
            p.get('id', identifier),
            p.get('revision', 1),
            p.get('kind', kind),
            p.get('name') or p.get('holeCode') or p.get('holeId') or identifier,
            p.get('notes') if p.get('notes') is not None else p.get('description'),
            p.get('type') or ('access_track' if kind == 'managed_tracks' else None),
            p.get('stage') or ('actual' if kind == 'managed_tracks' else None),
            p.get('status') or ('published' if kind == 'managed_tracks' else None),
            float(width) if isinstance(width, (int, float)) else None,
            p.get('editable', False),
            p.get('operationalState') or p.get('state'),
            p.get('qgisRevision'),
            json.dumps(p),
        ]
        for (name, _), value in zip(FIELDS, values):
            feature.setAttribute(name, value)
        for key, value in p.items():
            if key not in {name for name, _ in FIELDS} and layer.fields().indexFromName(key) >= 0 and isinstance(value, (str, int, float, bool)):
                feature.setAttribute(key, value)
        additions.append(feature)
    outcome = layer.addFeatures(additions) if editing else layer.dataProvider().addFeatures(additions)
    ok = outcome[0] if isinstance(outcome, tuple) else outcome
    if not ok:
        raise ValueError('Could not save the local working layer')
    layer.updateExtents()


DEFAULT_MAP_STYLE = {
    'holeColors': {'planned':'#9aa896','preparation':'#d4a012','ready':'#2e7d5b','drilling':'#4f7ba2',
                   'drilled':'#6b7f62','rehab_required':'#d9c8a9','complete':'#3e5b49'},
    'holeLabel': {'color':'#000000','haloColor':'#ffffff','size':14},
    'layers': {'disturbance':'#d4a012','disturbanceOutline':'#f5c84c','proposedPad':'#5b7fb0','proposedSump':'#c17a28'},
    'fillOpacity': {'disturbance':0.24,'proposedPad':0.18,'proposedSump':0.4},
}
DEFAULT_FEATURE_STYLES = {
    'managed_tracks': {'color': '#43946e'},
    'clearing':{'color':'#d4a012'}, 'work_area':{'color':'#8d6e4a'},
    'rehab_area':{'color':'#4f9a6a'}, 'boundary':{'color':'#5b7fb0','dashed':True},
    'annotation':{'color':'#a35fb0'}, 'marker':{'color':'#d0453b'}, 'other':{'color':'#6b7280'},
}


def default_style(layer, config=None):
    config = config or stored(layer, 'style', {})
    style = {key:{**value, **config.get('mapStyle', {}).get(key, {})} for key,value in DEFAULT_MAP_STYLE.items()}
    feature_styles = {**DEFAULT_FEATURE_STYLES, **config.get('featureStyles', {})}
    category = layer.customProperty('collar/category')
    if layer.geometryType() == 0 and category in ['holes', 'operational']:
        categories = []
        for key, colour in style['holeColors'].items():
            symbol = QgsMarkerSymbol.createSimple({'name':'circle','color':colour,'outline_color':'#ffffff','outline_width':'1','outline_width_unit':'Pixel','size':'9','size_unit':'Pixel'})
            categories.append(QgsRendererCategory(key, symbol, key.replace('_', ' ').title()))
        fallback = QgsMarkerSymbol.createSimple({'color':style['holeColors']['planned'],'size':'9','size_unit':'Pixel'})
        categories.append(QgsRendererCategory(None, fallback, 'Other'))
        layer.setRenderer(QgsCategorizedSymbolRenderer('state', categories))
        labels = QgsPalLayerSettings()
        labels.fieldName = 'name'
        text = QgsTextFormat()
        text.setFont(QFont("Open Sans"))
        text.setSize(style['holeLabel']['size'])
        text.setSizeUnit(Qgis.RenderUnit.Pixels)
        text.setColor(QColor(style['holeLabel']['color']))
        halo = QgsTextBufferSettings()
        halo.setEnabled(True)
        # QGIS strokes centred on the glyph edge; MapLibre specifies outward halo radius.
        # See QgsTextRenderer::renderDeferredBuffer (QPen width / 2 extends outward).
        halo.setSize(2 * max(1.6, style['holeLabel']['size'] * 0.17))
        halo.setOpacity(1.0)
        halo.setFillBufferInterior(True)
        halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        halo.setSizeUnit(Qgis.RenderUnit.Pixels)
        halo.setColor(QColor(style['holeLabel']['haloColor']))
        text.setBuffer(halo)
        labels.setFormat(text)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
        layer.setLabelsEnabled(True)
    elif category == 'managed_tracks' and layer.geometryType() == 1:
        track_styles = {**TRACK_TYPE_STYLES, **config.get('trackStyles', {})}
        categories = []
        for key, meta in track_styles.items():
            props = {
                'line_color': meta.get('color', '#43946e'),
                'line_style': 'dash' if meta.get('dashed') or key == 'walking_track' or key == 'proposed' else 'solid',
                'line_width': str(meta.get('width', 3)),
                'line_width_unit': 'Pixel',
            }
            if key == 'walking_track' or meta.get('dashed'):
                props['line_style'] = 'dash'
            categories.append(
                QgsRendererCategory(
                    key,
                    QgsLineSymbol.createSimple(props),
                    TRACK_TYPE_LABELS.get(key, key.replace('_', ' ').title()),
                )
            )
        # Proposed tracks: keep type colour but always dash via a second rule on stage when possible.
        fallback = QgsLineSymbol.createSimple(
            {'line_color': '#43946e', 'line_style': 'solid', 'line_width': '3', 'line_width_unit': 'Pixel'}
        )
        categories.append(QgsRendererCategory(None, fallback, 'Other'))
        layer.setRenderer(QgsCategorizedSymbolRenderer('type', categories))
        labels = QgsPalLayerSettings()
        labels.fieldName = 'name'
        text = QgsTextFormat()
        text.setFont(QFont('Open Sans'))
        text.setSize(11)
        text.setSizeUnit(Qgis.RenderUnit.Pixels)
        text.setColor(QColor('#1f2a24'))
        halo = QgsTextBufferSettings()
        halo.setEnabled(True)
        halo.setSize(2.2)
        halo.setOpacity(1.0)
        halo.setFillBufferInterior(True)
        halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        halo.setSizeUnit(Qgis.RenderUnit.Pixels)
        halo.setColor(QColor('#ffffff'))
        text.setBuffer(halo)
        labels.setFormat(text)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
        layer.setLabelsEnabled(True)
    else:
        key = {'proposed_pad':'proposedPad', 'proposed_sump':'proposedSump', 'disturbance':'disturbance'}.get(category)
        feature = feature_styles.get(category, {'color':'#6b7280'})
        colour = style['layers'][key] if key else feature['color']
        opacity = style['fillOpacity'][key] if key else 0.2
        outline = style['layers']['disturbanceOutline'] if category == 'disturbance' else colour
        dashed = category == 'proposed_pad' or feature.get('dashed', False)
        if layer.geometryType() == 2:
            fill = QColor(colour)
            fill.setAlphaF(opacity)
            rgba = ','.join(str(value) for value in fill.getRgb())
            symbol = QgsFillSymbol.createSimple({'color':rgba,'outline_color':outline,'outline_style':'dash' if dashed else 'solid','outline_width':'1.5','outline_width_unit':'Pixel'})
        elif layer.geometryType() == 1:
            symbol = QgsLineSymbol.createSimple({'line_color':colour,'line_style':'dash' if dashed else 'solid','line_width':'2.5','line_width_unit':'Pixel'})
        else:
            symbol = QgsMarkerSymbol.createSimple({'color':colour,'outline_color':'#ffffff','size':'7','size_unit':'Pixel'})
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.setLabelsEnabled(False)
    layer.setCustomProperty('collar/style', json.dumps(config))
    layer.triggerRepaint()


def create_layer(name, geometry_type, features, organisation, project, category, editable, project_name=None, style=None):
    layer = QgsVectorLayer(geometry_type + '?crs=EPSG:4326', name, 'memory')
    layer.dataProvider().addAttributes([QgsField(n, t) for n, t in FIELDS])
    layer.updateFields()
    extras = {}
    reserved = {n for n, _ in FIELDS} | {'fid'}
    for item in features:
        for key, value in item.get('properties', {}).items():
            if key not in reserved and len(key) <= 60 and key.isidentifier() and len(extras) < 100 and isinstance(value, (str, int, float, bool)):
                extras[key] = QVariant.Bool if isinstance(value, bool) else QVariant.Double if isinstance(value, (int, float)) else QVariant.String
    layer.dataProvider().addAttributes([QgsField(n, t) for n, t in extras.items()])
    layer.updateFields()
    add_features(layer, features, category)
    root = Path(QgsApplication.qgisSettingsDirPath()) / 'collar'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = root / hashlib.sha256(organisation.encode()).hexdigest() / hashlib.sha256(project.encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (str(uuid.uuid4()) + '.gpkg')
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.layerName = 'features'
    result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(path), QgsProject.instance().transformContext(), options)
    if result[0] != QgsVectorFileWriter.NoError:
        raise ValueError('Could not create a persistent QGIS working copy')
    os.chmod(path, 0o600)
    layer = QgsVectorLayer(str(path) + '|layername=features', name, 'ogr')
    if not layer.isValid():
        raise ValueError('Could not open the local working copy')
    for key, value in [('managed', True), ('organisation', organisation), ('project', project),
                       ('category', category), ('geometry', geometry_type)]:
        layer.setCustomProperty('collar/' + key, value)
    layer.setCustomProperty('collar/baseline', json.dumps(snapshot(layer)))
    defaults = [('client_key', 'uuid()'), ('kind', "'" + category + "'"), ('editable', 'true')]
    if category == 'managed_tracks':
        defaults.extend([
            ('type', "'access_track'"),
            ('stage', "'actual'"),
            ('status', "'published'"),
        ])
    for field, expression in defaults:
        layer.setDefaultValueDefinition(layer.fields().indexFromName(field), QgsDefaultValue(expression))
    form = layer.editFormConfig()
    editable_fields = {'name', 'notes'}
    if category == 'managed_tracks':
        editable_fields.update({'type', 'stage', 'status', 'widthM'})
    elif category not in ['holes', 'proposed_pad', 'proposed_sump', 'disturbance']:
        editable_fields.add('kind')
    for index, field in enumerate(layer.fields()):
        form.setReadOnly(index, field.name() not in editable_fields)
    layer.setEditFormConfig(form)
    layer.setReadOnly(not editable)
    default_style(layer, style)
    root = QgsProject.instance().layerTreeRoot()
    group_name = 'Collar · ' + (project_name or project)
    group = next((item for item in root.children() if hasattr(item, 'customProperty') and item.customProperty('collar/project') == project and item.customProperty('collar/organisation') == organisation), None)
    if group is None:
        group = root.insertGroup(0, group_name)
        group.setCustomProperty('collar/project', project)
        group.setCustomProperty('collar/organisation', organisation)
    QgsProject.instance().addMapLayer(layer, False)
    rank = {'holes':0,'proposed_sump':1,'proposed_pad':2,'disturbance':3}
    position = next((index for index,node in enumerate(group.children()) if hasattr(node,'layer') and node.layer() and rank.get(node.layer().customProperty('collar/category'),4) > rank.get(category,4)), len(group.children()))
    group.insertLayer(position, layer)
    if root.hasCustomLayerOrder():
        order = [item for item in root.customLayerOrder() if item.id() != layer.id()]
        first_basemap = next((i for i,item in enumerate(order) if item.customProperty('collar/basemap') or (item.customProperty('collar/organisation') == organisation and item.customProperty('collar/project') == project and rank.get(item.customProperty('collar/category'),4) > rank.get(category,4))),len(order))
        order.insert(first_basemap, layer)
        root.setCustomLayerOrder(order)
    return layer


def replace(layer, features):
    if dirty(layer):
        raise ValueError('Local edits are pending. Sync or review them before refreshing.')
    readonly = layer.readOnly()
    layer.setReadOnly(False)
    if not layer.startEditing():
        layer.setReadOnly(readonly)
        raise ValueError('Could not begin the local layer refresh')
    try:
        if not layer.deleteFeatures([f.id() for f in layer.getFeatures()]):
            raise ValueError('Could not refresh the local working copy')
        add_features(layer, features, layer.customProperty('collar/category'), editing=True)
        if not layer.commitChanges():
            raise ValueError('Could not save the refreshed working copy')
    except Exception:
        layer.rollBack()
        raise
    finally:
        layer.setReadOnly(readonly)
    layer.setCustomProperty('collar/baseline', json.dumps(snapshot(layer)))
    layer.triggerRepaint()


def apply_results(layer, submitted, results):
    baseline = acknowledge(stored(layer, 'baseline', {}), submitted, results)
    # Preserve local edits made after the submitted snapshot while assigning server IDs.
    changes = {}
    id_index, revision_index = layer.fields().indexFromName('id'), layer.fields().indexFromName('revision')
    for feature in layer.getFeatures():
        row = baseline.get(feature['client_key'])
        if row:
            changes[feature.id()] = {id_index: row['id'], revision_index: row['revision']}
    if changes and not layer.dataProvider().changeAttributeValues(changes):
        raise ValueError('Server changes saved; local IDs could not be updated. Retry sync to recover.')
    layer.setCustomProperty('collar/baseline', json.dumps(baseline))
    layer.triggerRepaint()


def export_vector(source, category):
    if not isinstance(source, QgsVectorLayer) or not source.crs().isValid():
        raise ValueError('Select a vector layer with a valid CRS')
    if source.featureCount() > 5000:
        raise ValueError('Publish up to 5,000 features at a time')
    transform = QgsCoordinateTransform(source.crs(), QgsCoordinateReferenceSystem('EPSG:4326'), QgsProject.instance())
    features = []
    track = category == 'managed_tracks'
    for feature in source.getFeatures():
        geometry = QgsGeometry(feature.geometry())
        if geometry.isEmpty() or not geometry.isGeosValid():
            raise ValueError('Fix empty or invalid geometries before publishing')
        geometry.transform(transform)
        value = json.loads(geometry.asJson(15))
        allowed = ['LineString', 'MultiLineString'] if track else ['Point', 'LineString', 'Polygon', 'MultiPolygon']
        if value['type'] not in allowed:
            raise ValueError(
                'Tracks require line geometry' if track else
                'Convert multipart points or geometry collections to supported geometry first'
            )
        properties = {'kind': category, 'editable': True}
        for name in ['name', 'notes', 'type', 'stage', 'status', 'widthM']:
            if source.fields().indexFromName(name) < 0:
                continue
            raw = feature[name]
            if raw is None or str(raw) == 'NULL':
                properties[name] = None
            elif name == 'widthM':
                try:
                    properties[name] = float(raw)
                except (TypeError, ValueError):
                    properties[name] = None
            else:
                properties[name] = str(raw)
        if track:
            properties.setdefault('type', 'access_track')
            properties.setdefault('stage', 'actual')
            properties.setdefault('status', 'published')
            if not properties.get('name'):
                raise ValueError('Give every track a name before publishing')
        features.append({'type':'Feature', 'id':str(uuid.uuid4()), 'geometry':value, 'properties':properties})
    if not features:
        raise ValueError('The selected layer is empty')
    return features


def archive_combined_layer(layer):
    """Keep original data and user styling, but stop treating the old view as live."""
    if layer.customProperty('collar/category') != 'operational' or not layer.readOnly() or dirty(layer):
        return False
    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
    if node is None:
        return False
    parent = node.parent()
    archive = next((child for child in parent.children() if hasattr(child, 'addChildNode') and child.name() == 'Previous combined layers'), None)
    if archive is None:
        archive = parent.addGroup('Previous combined layers')
    copy = node.clone()
    copy.setItemVisibilityChecked(False)
    archive.addChildNode(copy)
    parent.removeChildNode(node)
    archive.setExpanded(False)
    archive.setItemVisibilityChecked(False)
    layer.setCustomProperty('collar/legacy_archived', True)
    return True
