import os
import sys
import tempfile
from pathlib import Path

from qgis.core import QgsApplication, QgsProject, QgsRasterLayer, QgsVectorLayerUtils

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qgis.PyQt.QtWidgets import QMainWindow

app = QgsApplication([], False, tempfile.mkdtemp(prefix='collar-qgis-profile-'))
if os.environ.get('QGIS_PLUGINPATH'):
    QgsApplication.setPluginPath(os.environ['QGIS_PLUGINPATH'])
app.initQgis()
if os.environ.get('QGIS_PLUGINPATH'):
    from qgis.core import QgsProviderRegistry
    from qgis.PyQt.QtCore import QDir

    QgsProviderRegistry.instance().setLibraryDirectory(QDir(os.environ['QGIS_PLUGINPATH']))
profile = tempfile.mkdtemp(prefix='collar-qgis-smoke-')
QgsApplication.qgisSettingsDirPath = staticmethod(lambda: profile)
from collar_qgis.layers import apply_results, create_layer, pending, replace
from collar_qgis.plugin import CollarPlugin

f = {
    'type': 'Feature',
    'id': 'f',
    'geometry': {'type': 'Point', 'coordinates': [121, -30]},
    'properties': {
        'id': 'f',
        'revision': 1,
        'kind': 'marker',
        'name': 'Marker',
        'notes': None,
        'editable': True,
    },
}
layer = create_layer('Test', 'Point', [f], 'test-org', 'test-project', 'marker', True)
assert pending(layer) == [], pending(layer)
layer.startEditing()
feature = next(layer.getFeatures())
layer.changeAttributeValue(feature.id(), layer.fields().indexFromName('name'), 'Changed')
assert layer.commitChanges()
changes = pending(layer)
assert changes[0][1]['attributes']['name'] == 'Changed', changes
apply_results(
    layer,
    changes,
    [{'changeId': changes[0][1]['changeId'], 'status': 'applied', 'id': 'f', 'revision': 2}],
)
assert pending(layer) == [], pending(layer)
f['properties']['revision'] = 2
replace(layer, [f])
assert pending(layer) == [], pending(layer)
# Project persistence must restore the working copy and connection without a credential.
project_path = tempfile.mktemp(suffix='.qgz')
QgsProject.instance().setFileName(project_path)
assert QgsProject.instance().write()
QgsProject.instance().clear()
assert QgsProject.instance().read(project_path)
loaded = next(iter(QgsProject.instance().mapLayers().values()))
assert loaded.isValid()
assert pending(loaded) == [], pending(loaded)
print('Persistent layers, edits, acknowledgement, refresh and project reopening passed')


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()

    def mainWindow(self):
        return self.window

    def messageBar(self):
        return self

    def pushSuccess(self, *a):
        pass

    def pushWarning(self, *a):
        pass

    def setActiveLayer(self, layer):
        self.active = layer

    def activeLayer(self):
        return getattr(self, 'active', None)

    def mapCanvas(self):
        return self.canvas

    def addPluginToMenu(self, *a):
        pass

    def addPluginToVectorMenu(self, *a):
        pass

    def addToolBarIcon(self, *a):
        pass

    def addCustomActionForLayerType(self, *a):
        pass

    def addDockWidget(self, area, dock):
        self.window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        self.window.removeDockWidget(dock)

    def removePluginMenu(self, *a):
        pass

    def removePluginVectorMenu(self, *a):
        pass

    def removeToolBarIcon(self, *a):
        pass

    def removeCustomActionForLayerType(self, *a):
        pass


iface = FakeIface()
plugin = CollarPlugin(iface)


class MemorySettings:
    def __init__(self):
        self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value


class MemoryToken:
    auth_id = ''

    def read(self):
        return 'test-token' if self.auth_id else None

    def clear(self):
        self.auth_id = ''


plugin.preferences_store = MemorySettings()
plugin.store = MemoryToken()
plugin.initGui()
assert plugin.dock
# Signed-in identity comes from /me; no identity or credential is saved as a UI preference.
from qgis.PyQt.QtCore import Qt

from collar_qgis.ui import preferences

assert not plugin.connect_button.isHidden() and plugin.signout_button.isHidden()
assert not plugin.timer.isActive()
original_call = plugin.call
original_orgs = plugin.fetch_organisations
seen = []
plugin.store.auth_id = 'test-auth'
plugin.call = lambda method, path, body, done, **kwargs: (
    seen.append(path),
    done({'user': {'name': '<b>Demo planner</b>', 'email': 'kai@collar.local'}}),
)
plugin.fetch_organisations = lambda: None
plugin.fetch_identity()
assert seen == ['/api/v1/me']
assert plugin.connection_state == 'connected' and plugin.timer.isActive()
assert plugin.connect_button.isHidden() and not plugin.signout_button.isHidden()
assert plugin.account_name.text() == '<b>Demo planner</b>'
assert plugin.account_name.textFormat() == Qt.TextFormat.PlainText
plugin.set_busy(True)
assert plugin.connect_button.isHidden()
plugin.set_busy(False)
# Save/Cancel and a single separate settings window, with a bounded timer interval.
plugin.show_settings()
settings = plugin.settings_dialog
settings.interval.setCurrentIndex(settings.interval.findData(300))
settings.reject()
assert plugin.preferences['seconds'] == 120 and plugin.preferences_store.data == {}
plugin.show_settings()
assert plugin.settings_dialog is settings and settings.interval.currentData() == 120
settings.interval.setCurrentIndex(settings.interval.findData(300))
settings.basemap.setChecked(False)
settings.accept()
assert plugin.timer.interval() == 300000
assert preferences(plugin.preferences_store) == {'enabled': True, 'seconds': 300, 'basemap': False}
assert set(plugin.preferences_store.data) == {
    'collar/autoRefreshEnabled',
    'collar/refreshSeconds',
    'collar/includeBasemap',
}
plugin.show_settings()
settings.enabled.setChecked(False)
settings.accept()
assert not plugin.timer.isActive()
plugin.preferences_store.data['collar/refreshSeconds'] = -1
assert preferences(plugin.preferences_store)['seconds'] == 120
plugin.preferences_store.data['collar/refreshSeconds'] = 'invalid'
assert preferences(plugin.preferences_store)['seconds'] == 120
# Expired sessions never show Connect until local sign-out; identity is cleared on sign-out.
plugin.update_connection('expired')
assert not plugin.timer.isActive() and plugin.connect_button.isHidden()
plugin.call = original_call
plugin.fetch_organisations = original_orgs
import collar_qgis.plugin as plugin_module

original_request = plugin_module.request


class DeferredTask:
    http_status = None
    connection_error = False


callbacks = []
tasks = []


def deferred_request(method, path, token, organisation, body, callback):
    task = DeferredTask()
    callbacks.append(callback)
    tasks.append(task)
    return task


plugin_module.request = deferred_request
plugin.call('GET', '/api/v1/me', None, lambda result: None)
tasks[-1].http_status = 401
callbacks[-1](None, 'Session expired. Sign out, then connect to Collar again.')
assert plugin.connection_state == 'expired' and not plugin.timer.isActive()
assert plugin.connect_button.isHidden()
plugin.call('GET', '/api/v1/me', None, lambda result: None)
tasks[-1].connection_error = True
callbacks[-1](None, 'Could not reach Collar.')
assert plugin.connection_state == 'issue' and plugin.connect_button.isHidden()
plugin.call('GET', '/api/v1/me', None, lambda result: None)
callbacks[-1]({}, None)
assert plugin.connection_state == 'connected'
plugin_module.request = lambda method, path, token, organisation, body, callback: callback({}, None)
plugin.signout()
plugin_module.request = original_request
assert plugin.identity is None and plugin.account_email.text() == ''
assert not plugin.connect_button.isHidden() and plugin.signout_button.isHidden()
assert not plugin.timer.isActive()
# Render fictional demo content for native layout review.
plugin.store.auth_id = 'test-auth'
plugin.identity = {'name': 'Demo planner', 'email': 'kai@collar.local'}
plugin.update_connection('connected')
plugin.status.setText('Choose a project to load your layers.')
iface.window.resize(440, 1050)
iface.window.show()
app.processEvents()
plugin.dock.grab().save('/tmp/collar-qgis-panel.png')
plugin.show_settings()
app.processEvents()
settings.grab().save('/tmp/collar-qgis-settings.png')
settings.reject()
print(
    'Identity, safe account rendering, connection controls, settings persistence and refresh timers passed'
)
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QDialog

# Exercise Qt 5/6-scoped dialog enums and read-only conflict comparison panels.
QTimer.singleShot(
    0, lambda: [widget.reject() for widget in app.topLevelWidgets() if isinstance(widget, QDialog)]
)
change = {
    'changeId': 'test',
    'action': 'update',
    'kind': 'marker',
    'attributes': {'name': 'Local'},
    'geometry': f['geometry'],
}
plugin.review_conflicts(
    [((loaded, 'f', change), {'status': 'conflict', 'current': {'name': 'Remote', 'revision': 2}})],
    ['Changed in Collar'],
)
assert iface.active is loaded
# Native feature-form defaults generate a stable client key without exposing reserved fields.
new = QgsVectorLayerUtils.createFeature(loaded)
assert new['client_key'] and str(new['client_key']) != 'NULL'
assert loaded.editFormConfig().readOnly(loaded.fields().indexFromName('revision'))
# Reopening and refreshing an older combined project separates footprints by purpose.
from qgis.core import Qgis
from qgis.PyQt.QtGui import QColor

from collar_qgis.basemaps import add_esri_basemap, has_raster_basemap
from collar_qgis.layers import archive_combined_layer, connected_layers

loaded.setCustomProperty('collar/managed', False)
plugin.organisations.blockSignals(True)
plugin.organisations.addItem('Outback Minerals', 'test-org')
plugin.projects.blockSignals(True)
plugin.projects.addItem('Ironbark', 'test-project')
plugin.style_config = {
    'mapStyle': {
        'holeColors': {'ready': '#123456'},
        'layers': {'proposedPad': '#123abc'},
        'fillOpacity': {'proposedPad': 0.3},
    },
    'featureStyles': {},
}
polygon = {
    'type': 'Polygon',
    'coordinates': [[[121, -30], [121.001, -30], [121.001, -30.001], [121, -30]]],
}
operational = [
    {
        'type': 'Feature',
        'id': 'hole:h',
        'geometry': {'type': 'Point', 'coordinates': [121, -30]},
        'properties': {
            'id': 'h',
            'entity_type': 'hole',
            'holeId': 'IBRC26042',
            'operationalState': 'ready',
            'qgisRevision': 'a' * 64,
        },
    },
    {
        'type': 'Feature',
        'id': 'pad:h',
        'geometry': polygon,
        'properties': {'id': 'pad:h', 'entity_type': 'proposed_pad', 'holeCode': 'IBRC26042'},
    },
    {
        'type': 'Feature',
        'id': 'sump:h:s',
        'geometry': polygon,
        'properties': {'id': 'sump:h:s', 'entity_type': 'proposed_sump', 'holeCode': 'IBRC26042'},
    },
    {
        'type': 'Feature',
        'id': 'disturbance:h',
        'geometry': polygon,
        'properties': {
            'id': 'disturbance:h',
            'entity_type': 'disturbance',
            'holeCode': 'IBRC26042',
        },
    },
]
legacy = create_layer(
    'Old combined polygons',
    'Polygon',
    operational[1:],
    'test-org',
    'test-project',
    'operational',
    False,
)
legacy.setCustomProperty('collar/source', '/api/v1/qgis/projects/test-project/operational')
plugin.call = lambda method, path, body, callback, **kwargs: callback(
    {'type': 'FeatureCollection', 'features': operational}
)
plugin.notify = lambda text: None
plugin.refresh()
by_category = {
    layer.customProperty('collar/category'): layer
    for layer in connected_layers('test-org', 'test-project')
}
assert set(by_category) == {'holes', 'proposed_pad', 'proposed_sump', 'disturbance'}, by_category
assert all(layer.featureCount() == 1 for layer in by_category.values())
assert legacy.customProperty('collar/legacy_archived')
assert legacy.featureCount() == 3
assert not QgsProject.instance().layerTreeRoot().findLayer(legacy.id()).isVisible()
assert by_category['proposed_pad'].name() == 'Proposed pads'
assert by_category['proposed_pad'].renderer().symbol().color().name() == '#123abc'
assert abs(by_category['proposed_pad'].renderer().symbol().color().alphaF() - 0.3) < 0.01
ready_category = next(
    item for item in by_category['holes'].renderer().categories() if item.value() == 'ready'
)
assert ready_category.symbol().color().name() == '#123456', ready_category.symbol().color().name()
by_category['proposed_pad'].renderer().symbol().setColor(QColor('#ff00ff'))
style_before = by_category['proposed_pad'].renderer().dump()
plugin.refresh()
assert by_category['proposed_pad'].renderer().dump() == style_before
assert all(layer.featureCount() == 1 for layer in by_category.values())
assert len(connected_layers('test-org', 'test-project')) == 4
# Hole labels follow the same halo width rule as the web, including custom label settings.
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsRectangle
from qgis.gui import QgsMapCanvas, QgsMapToolPan

from collar_qgis.layers import default_style

hole_layer = by_category['holes']
custom_style = {'mapStyle': {'holeLabel': {'size': 20, 'color': '#123456', 'haloColor': '#fedcba'}}}
default_style(hole_layer, custom_style)
label = hole_layer.labeling().settings().format()
assert label.size() == 20 and label.color().name() == '#123456'
assert abs(label.buffer().size() - 6.8) < 0.001
assert label.buffer().color().name() == '#fedcba' and label.buffer().opacity() == 1
assert label.buffer().fillBufferInterior()
# Exercise the actual nonmodal review and canvas overlays with a projected map.
iface.canvas = QgsMapCanvas()
iface.canvas.resize(720, 480)
iface.canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3857'))
iface.canvas.setLayers([hole_layer])
projected = QgsCoordinateTransform(
    hole_layer.crs(), iface.canvas.mapSettings().destinationCrs(), QgsProject.instance()
)
origin = projected.transform(QgsPointXY(121, -30))
iface.canvas.setExtent(
    QgsRectangle(origin.x() - 250, origin.y() - 170, origin.x() + 250, origin.y() + 170)
)
previous_tool = QgsMapToolPan(iface.canvas)
iface.canvas.setMapTool(previous_tool)
iface.setActiveLayer(hole_layer)
feature = next(hole_layer.getFeatures())
hole_layer.selectByIds([feature.id()])
geometry_before = feature.geometry().asWkt()
requests = []
plugin.call = lambda method, path, body, callback, **kwargs: requests.append(
    (method, path, body, callback)
)
plugin.propose_move()
review = plugin.move_review
assert review is not None and review.isVisible()
assert not plugin.organisations.isEnabled() and not plugin.projects.isEnabled()
assert requests == [] and not review.submit_button.isEnabled()
assert iface.canvas.mapTool() is review.tool and hole_layer.readOnly()
proposed = projected.transform(QgsPointXY(121.001, -30.001))
review.pick(proposed, Qt.MouseButton.RightButton)
assert review.target is None
review.pick(proposed, Qt.MouseButton.LeftButton)
assert abs(review.target.x() - 121.001) < 0.000001
assert abs(review.target.y() + 30.001) < 0.000001
assert review.proposed_marker.isVisible() and review.line.isVisible()
assert len(review.line.asGeometry().asPolyline()) == 2
assert 'Distance:' in review.coordinates.text() and requests == []
review.reason.setPlainText('x' * 2001)
assert not review.submit_button.isEnabled()
review.reason.setPlainText('Avoid the mapped drainage line.')
assert review.submit_button.isEnabled()
iface.canvas.show()
iface.canvas.refresh()
# Render a real label against a contrasting background to review the custom halo.
from qgis.core import QgsMapRendererParallelJob

hole_layer.removeSelection()
render_settings = iface.canvas.mapSettings()
render_settings.setBackgroundColor(QColor('#53624f'))
render_job = QgsMapRendererParallelJob(render_settings)
render_job.start()
render_job.waitForFinished()
assert not render_job.renderedImage().isNull()
render_job.renderedImage().save('/tmp/collar-qgis-hole-label.png')
hole_layer.selectByIds([feature.id()])
app.processEvents()
review.grab().save('/tmp/collar-qgis-move-review.png')
iface.canvas.grab().save('/tmp/collar-qgis-move-preview.png')
review.submit_button.click()
assert len(requests) == 1 and review.busy and not review.cancel_button.isEnabled()
method, path, payload, complete = requests[-1]
assert method == 'POST' and path.endswith('/holes/h/move')
assert abs(payload['lng'] - 121.001) < 0.000001 and payload['revision'] == 'a' * 64
assert payload['comment'] == 'Avoid the mapped drainage line.'
review.submit_button.click()
assert len(requests) == 1
# Failed requests retain the review; retry keeps its idempotency key.
plugin.error('Synthetic request failure')
assert (
    plugin.move_review is review and review.target is not None and review.submit_button.isEnabled()
)
review.submit_button.click()
assert len(requests) == 2 and requests[-1][2]['clientId'] == payload['clientId']
requests[-1][3]({'status': 'pending'})
assert plugin.move_review is None and review.cleaned
assert iface.canvas.mapTool() is previous_tool
assert (
    next(hole_layer.getFeatures()).geometry().asWkt() == geometry_before and hole_layer.readOnly()
)
# Cancel creates no request and removes both markers and the line.
plugin.propose_move()
review = plugin.move_review
review.pick(proposed, Qt.MouseButton.LeftButton)
review.reason.setPlainText('Cancelled proposal')
count = len(requests)
review.cancel_button.click()
assert plugin.move_review is None and review.cleaned and len(requests) == count
assert iface.canvas.mapTool() is previous_tool and plugin.organisations.isEnabled()
# Removing the source layer invalidates the review rather than submitting stale context.
plugin.propose_move()
review = plugin.move_review
review.layers_removed([hole_layer.id()])
assert plugin.move_review is None and review.cleaned
print(
    'Projected move preview, marker/line, review-before-submit, retry, cancel and source cleanup passed'
)
operational_without_sumps = [
    row for row in operational if row['properties']['entity_type'] != 'proposed_sump'
]
plugin.call = lambda method, path, body, callback, **kwargs: callback(
    {'type': 'FeatureCollection', 'features': operational_without_sumps}
)
plugin.refresh()
assert by_category['proposed_sump'].featureCount() == 0
plugin.refresh()
assert by_category['proposed_sump'].featureCount() == 0
protected_local = create_layer(
    'Local legacy draft',
    'Polygon',
    operational[1:],
    'test-org',
    'test-project',
    'operational',
    True,
)
assert not archive_combined_layer(protected_local)
assert not protected_local.customProperty('collar/legacy_archived', False)
# XYZ provider setup is validated without rendering or requesting customer map tiles.
root = QgsProject.instance().layerTreeRoot()
root.setHasCustomLayerOrder(True)
root.setCustomLayerOrder(list(QgsProject.instance().mapLayers().values()))
from qgis.core import QgsProviderRegistry

assert 'wms' in QgsProviderRegistry.instance().providerList(), (
    'Load the QGIS provider plugins for the XYZ basemap test'
)
basemap = add_esri_basemap()
assert basemap.isValid() and has_raster_basemap()
assert basemap.providerType() == 'wms'
assert 'authcfg' not in basemap.source() and 'token' not in basemap.source()
assert 'Esri' in basemap.metadata().rights()[0]
assert 'Esri' in basemap.serverProperties().attribution()
assert root.children()[-1].layerId() == basemap.id()
assert root.customLayerOrder()[-1].id() == basemap.id()
assert add_esri_basemap().id() == basemap.id()
assert (
    len(
        [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if layer.type() == Qgis.LayerType.Raster
        ]
    )
    == 1
)
# Missing Esri levels use a correctly cropped parent, including a cold high-zoom open.
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice
from qgis.PyQt.QtGui import QImage, QPainter

from collar_qgis import basemaps, imagery

image = QImage(256, 256, QImage.Format.Format_ARGB32)
image.fill(QColor('#ff0000'))
painter = QPainter(image)
painter.fillRect(128, 0, 128, 128, QColor('#00ff00'))
painter.fillRect(0, 128, 128, 128, QColor('#0000ff'))
painter.fillRect(128, 128, 128, 128, QColor('#ffff00'))
painter.end()
encoded = QByteArray()
encoded_buffer = QBuffer(encoded)
encoded_buffer.open(QIODevice.OpenModeFlag.WriteOnly)
assert image.save(encoded_buffer, 'PNG')
tile_bytes = bytes(encoded)
fetches = []


def synthetic_tile(z, x, y):
    fetches.append((z, x, y))
    if z > 0:
        raise imagery.MissingTile()
    return tile_bytes


cache = imagery.TileCache(synthetic_tile)
# At z2 x3 y2, the source is the lower-right quadrant of the z0 tile.
result = QImage.fromData(cache.tile(2, 3, 2))
assert result.pixelColor(128, 128).name() == '#ffff00'
assert fetches == [(2, 3, 2), (1, 1, 1), (0, 0, 0)]
fetches.clear()
assert QImage.fromData(cache.tile(2, 3, 2)).pixelColor(128, 128).name() == '#ffff00'
assert fetches == []  # Both missing levels and the parent were cached.
for coords in [(20, 0, 0), (2, 4, 0), (2, -1, 0), (2, 0, 4)]:
    try:
        cache.tile(*coords)
        raise AssertionError('Invalid coordinates accepted')
    except ValueError:
        pass
cache.close()
assert cache.size == 0 and not cache.cache and not cache.missing
# The byte budget evicts old entries instead of retaining an unbounded tile pyramid.
original_budget = imagery.MAX_CACHE
imagery.MAX_CACHE = 2 * len(tile_bytes)
bounded = imagery.TileCache(lambda *coords: tile_bytes)
try:
    for tx in range(5):
        bounded.tile(3, tx, 0)
    assert bounded.size <= imagery.MAX_CACHE and len(bounded.cache) == 2
    assert list(bounded.cache) == [(3, 3, 0), (3, 4, 0)]
finally:
    imagery.MAX_CACHE = original_budget
    bounded.close()
# Rate limits/auth failures cannot be hidden by unlimited parent retries.
failures = []


def denied_tile(*coords):
    failures.append(coords)
    raise HTTPError('https://services.arcgisonline.com', 429, 'Rate limited', {}, None)


try:
    imagery.TileCache(denied_tile).tile(19, 0, 0)
    raise AssertionError('Rate limit ignored')
except HTTPError:
    pass
assert len(failures) == 1
for bad_data in [b'not an image', b'x' * (imagery.MAX_IMAGE + 1)]:
    try:
        imagery.TileCache(lambda *coords: bad_data).tile(0, 0, 0)
        raise AssertionError('Invalid image accepted')
    except ValueError:
        pass
# The runtime listener only serves fixed, validated tile routes and shuts down cleanly.
service = imagery.ImageryService(synthetic_tile)
try:
    tile_url = service.url.replace('{z}', '2').replace('{x}', '3').replace('{y}', '2')
    with urlopen(tile_url, timeout=3) as response:
        assert response.status == 200 and response.headers['Content-Type'] == 'image/png'
        assert QImage.fromData(response.read()).pixelColor(128, 128).name() == '#ffff00'
    invalid_urls = [
        tile_url + '?url=https://example.com',
        tile_url.replace('/esri/2/3/2.png', '/esri/20/0/0.png'),
        tile_url.replace('/esri/2/3/2.png', '/other'),
    ]
    for url in invalid_urls:
        try:
            urlopen(url, timeout=3)
            raise AssertionError('Arbitrary route accepted')
        except HTTPError as error:
            assert error.code == 400
    try:
        urlopen(Request(tile_url, headers={'Host': 'untrusted.example'}), timeout=3)
        raise AssertionError('Host accepted')
    except HTTPError as error:
        assert error.code == 400
finally:
    service.close()
assert not service.thread.is_alive()
# Upgrade existing managed layers in place; existing user basemaps are not modified.
old_id = basemap.id()
old_opacity = 0.65
basemap.renderer().setOpacity(old_opacity)
basemap.setDataSource(
    'type=xyz&url='
    + __import__('urllib.parse', fromlist=['quote']).quote(basemaps.ESRI_TILES, safe='')
    + '&zmin=0&zmax=19&crs=EPSG:3857',
    basemap.name(),
    'wms',
)
basemap.renderer().setOpacity(old_opacity)
basemaps.restore_esri_basemaps()
assert basemap.id() == old_id and basemap.isValid()
assert '127.0.0.1' in __import__('urllib.parse', fromlist=['unquote']).unquote(basemap.source())
assert abs(basemap.renderer().opacity() - old_opacity) < 0.001
assert (
    'Esri' in basemap.metadata().rights()[0] and 'Esri' in basemap.serverProperties().attribution()
)
assert basemap.resampleFilter().zoomedInResampler().type() == 'bilinear'
assert 'authcfg' not in basemap.source() and 'token' not in basemap.source()
port = basemaps._service.server.server_port
basemaps.stop_imagery()
basemaps.restore_esri_basemaps()
assert basemap.isValid() and basemaps._service.thread.is_alive()
# Render at well beyond native z19, starting cold, through the real QGIS XYZ provider.
basemaps.stop_imagery()
basemaps._service = imagery.ImageryService(synthetic_tile)
basemaps.restore_esri_basemaps()
from qgis.core import QgsMapSettings
from qgis.PyQt.QtCore import QSize

settings = QgsMapSettings()
settings.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3857'))
settings.setLayers([basemap])
settings.setOutputSize(QSize(256, 256))
settings.setExtent(
    QgsRectangle(origin.x() - 0.5, origin.y() - 0.5, origin.x() + 0.5, origin.y() + 0.5)
)
settings.setBackgroundColor(QColor('#ff00ff'))
basemap.renderer().setOpacity(1)
fetches.clear()
job = QgsMapRendererParallelJob(settings)
job.start()
# Keep the UI event loop available for QGIS's network request manager.
from qgis.PyQt.QtCore import QEventLoop

loop = QEventLoop()
job.finished.connect(loop.quit)
QTimer.singleShot(15000, loop.quit)
if job.isActive():
    loop.exec()
if job.isActive():
    job.cancel()
rendered = job.renderedImage()
assert not job.errors(), [(error.layerID, error.message) for error in job.errors()]
assert not rendered.isNull() and rendered.pixelColor(128, 128).name() == '#ffff00', (
    rendered.pixelColor(128, 128).name()
)
assert fetches and max(z for z, x, y in fetches) == 19
rendered.save('/tmp/collar-qgis-overzoom.png')
# User-supplied Esri XYZ sources are left untouched by automatic migration.
user_basemap = QgsRasterLayer(
    'type=xyz&url='
    + __import__('urllib.parse', fromlist=['quote']).quote(basemaps.ESRI_TILES, safe='')
    + '&zmax=17',
    'User imagery',
    'wms',
)
QgsProject.instance().addMapLayer(user_basemap)
user_source = user_basemap.source()
basemaps.restore_esri_basemaps()
assert user_basemap.source() == user_source
QgsProject.instance().removeMapLayer(user_basemap.id())
print(
    'Imagery parent crop, cold-start fallback, cache bounds, request validation, migration and service lifecycle passed'
)
print('Runtime: ' + Qgis.QGIS_VERSION)
print(
    'Separate footprint layers, legacy migration, organisation styling, style preservation and optional XYZ basemap passed'
)
iface.setActiveLayer(hole_layer)
hole_layer.selectByIds([next(hole_layer.getFeatures()).id()])
plugin.propose_move()
unload_review = plugin.move_review
imagery_service = basemaps._service
plugin.unload()
assert basemaps._service is None and not imagery_service.thread.is_alive()
assert unload_review.cleaned and plugin.move_review is None
print('Native panel construction and unload passed')
from collar_qgis import network

assert network._error_code('NoError') is not None
probe = network.RequestTask('GET', '/api/v1/me', None, None, None, lambda *_: None)
probe_request = probe._network_request()
assert probe_request.url().toString() == 'https://app.getcollar.io/api/v1/me'
assert probe_request.attribute(
    network._attribute('RedirectPolicyAttribute')
) == network._redirect_policy('ManualRedirectPolicy')


class FakeReply:
    def __init__(self, status=200, content=b'{"ok":true}'):
        self.status = status
        self.body = content

    def attribute(self, attribute):
        return self.status

    def content(self):
        return QByteArray(self.body)


class FakeBlockingRequest:
    NoError = 0
    ErrorCode = type('ErrorCode', (), {'NoError': 0})
    status = 200
    content = b'{"ok":true}'
    outcome = 0

    def get(self, request, force_refresh, feedback):
        assert request.url().toString().startswith('https://app.getcollar.io/api/')
        assert bytes(request.rawHeader(b'Authorization')) == b'Bearer synthetic-test-token'
        if request.url().toString().endswith('/qgis/projects'):
            assert bytes(request.rawHeader(b'X-Organisation-Id')) == b'test-org'
        assert request.attribute(
            network._attribute('RedirectPolicyAttribute')
        ) == network._redirect_policy('ManualRedirectPolicy')
        return self.outcome

    def reply(self):
        return FakeReply(self.status, self.content)


original = network.QgsBlockingNetworkRequest
network.QgsBlockingNetworkRequest = FakeBlockingRequest
try:
    outcomes = []
    task = network.RequestTask(
        'GET',
        '/api/v1/qgis/projects',
        'synthetic-test-token',
        'test-org',
        None,
        lambda result, error: outcomes.append((result, error)),
    )
    assert task.run()
    task.finished(True)
    assert outcomes == [({'ok': True}, None)]
    assert task.token is None and task.result is None and task.callback is None
    cancelled = network.RequestTask(
        'GET', '/api/v1/qgis/projects', 'synthetic-test-token', None, None, lambda *_: None
    )
    cancelled.cancel()
    assert not cancelled.run() and cancelled.token is None
    FakeBlockingRequest.status = 401
    FakeBlockingRequest.content = b'{}'
    FakeBlockingRequest.outcome = 1
    expired = network.RequestTask(
        'GET', '/api/v1/me', 'synthetic-test-token', None, None, lambda *_: None
    )
    assert not expired.run() and expired.http_status == 401 and not expired.connection_error
    assert expired.token is None
    FakeBlockingRequest.status = None
    offline = network.RequestTask(
        'GET', '/api/v1/me', 'synthetic-test-token', None, None, lambda *_: None
    )
    assert not offline.run() and offline.connection_error and offline.http_status is None
    assert offline.token is None
    print(
        'Bounded request completion, cancellation, credential release and redirect rejection passed'
    )
finally:
    network.QgsBlockingNetworkRequest = original
# Browser confirmation waits for secure token storage; rejected grants never show success.
from collar_qgis.auth import BrowserLogin


class FakeSocket:
    def __init__(self, state):
        self.props = {}
        self.data = (
            'GET /callback?code=00000000-0000-0000-0000-000000000000&state='
            + state
            + ' HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n'
        ).encode()
        self.output = b''

    def property(self, key):
        return self.props.get(key)

    def setProperty(self, key, value):
        self.props[key] = value

    def readAll(self):
        data, self.data = self.data, b''
        return data

    def write(self, data):
        self.output += data

    def disconnectFromHost(self):
        pass


browser = BrowserLogin()
browser.state = 'synthetic-state'
browser.verifier = 'synthetic-verifier'
browser.redirect = 'http://127.0.0.1:1234/callback'
grants = []
browser.ready.connect(grants.append)
valid = FakeSocket('synthetic-state')
browser.read(valid)
assert len(grants) == 1 and valid.output == b''
browser.read(valid)
assert len(grants) == 1  # Additional socket data cannot exchange the code twice.
browser.complete(True)
assert b'200 OK' in valid.output and b'Connected successfully' in valid.output
assert b'synthetic-state' not in valid.output and b'synthetic-verifier' not in valid.output
assert b'Content-Security-Policy' in valid.output and b'no-store' in valid.output
invalid = FakeSocket('wrong-state')
browser.read(invalid)
assert len(grants) == 1 and b'400 Bad Request' in invalid.output
assert b'Connected successfully' not in invalid.output
failed = FakeSocket('synthetic-state')
browser.read(failed)
browser.complete(False)
assert (
    b'Connection not completed' in failed.output and b'Connected successfully' not in failed.output
)
browser.stop()
print(
    'Browser callback state validation, single exchange, delayed success and failure pages passed'
)
iface.canvas.setLayers([])
iface.canvas.close()
iface.canvas.deleteLater()
from qgis.PyQt.QtCore import QCoreApplication, QEvent

QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
QgsProject.instance().clear()
app.exitQgis()
