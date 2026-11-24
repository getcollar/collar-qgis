"""Optional public XYZ imagery. Collar credentials are never attached to tile requests."""

from urllib.parse import quote, unquote

from qgis.core import Qgis, QgsBilinearRasterResampler, QgsMessageLog, QgsProject, QgsRasterLayer

from .imagery import MAX_ZOOM, ImageryService

ESRI_TILES = 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
_service = None

ESRI_ATTRIBUTION = (
    'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
)


def imagery_uri():
    global _service
    if _service is None:
        try:
            _service = ImageryService()
        except OSError as error:
            raise ValueError(
                'Could not enable Collar imagery. Allow QGIS to use local connections, or add your own basemap.'
            ) from error
    return (
        'type=xyz&url='
        + quote(_service.url, safe='')
        + '&zmin=0&zmax='
        + str(MAX_ZOOM)
        + '&crs=EPSG:3857'
    )


def ensure_attribution(layer):
    metadata = layer.metadata()
    if not metadata.title():
        metadata.setTitle('Esri World Imagery')
    if ESRI_ATTRIBUTION not in metadata.rights():
        metadata.setRights(metadata.rights() + [ESRI_ATTRIBUTION])
    if not metadata.abstract():
        metadata.setAbstract(
            'Online basemap. ' + ESRI_ATTRIBUTION + '. Provider terms and attribution apply.'
        )
    layer.setMetadata(metadata)
    layer.serverProperties().setAttribution(ESRI_ATTRIBUTION)
    layer.serverProperties().setAttributionUrl(
        'https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9'
    )


def update_managed_basemap(layer):
    uri = imagery_uri()
    if layer.source() != uri:
        renderer = layer.renderer().clone() if layer.renderer() else None
        metadata = layer.metadata()
        layer.setDataSource(uri, layer.name(), 'wms')
        if renderer:
            layer.setRenderer(renderer)
        layer.setMetadata(metadata)
    layer.resampleFilter().setZoomedInResampler(QgsBilinearRasterResampler())
    ensure_attribution(layer)
    layer.triggerRepaint()


def restore_esri_basemaps(*_):
    for layer in QgsProject.instance().mapLayers().values():
        if (
            isinstance(layer, QgsRasterLayer)
            and layer.customProperty('collar/basemap') == 'esri_world_imagery'
        ):
            try:
                update_managed_basemap(layer)
            except ValueError as error:
                QgsMessageLog.logMessage(str(error), 'Collar', Qgis.MessageLevel.Warning)


def stop_imagery():
    global _service
    if _service is not None:
        _service.close()
        _service = None


def has_raster_basemap():
    return any(
        layer.type() == Qgis.LayerType.Raster
        for layer in QgsProject.instance().mapLayers().values()
    )


def has_esri_basemap():
    return any(
        layer.customProperty('collar/basemap') == 'esri_world_imagery'
        or (
            isinstance(layer, QgsRasterLayer)
            and 'World_Imagery/MapServer/tile' in unquote(layer.source())
        )
        for layer in QgsProject.instance().mapLayers().values()
    )


def add_esri_basemap():
    project = QgsProject.instance()
    for layer in project.mapLayers().values():
        if layer.customProperty('collar/basemap') == 'esri_world_imagery' or (
            isinstance(layer, QgsRasterLayer)
            and 'World_Imagery/MapServer/tile' in unquote(layer.source())
        ):
            if layer.customProperty('collar/basemap') == 'esri_world_imagery':
                update_managed_basemap(layer)
            return layer
    uri = imagery_uri()
    layer = QgsRasterLayer(uri, 'Esri World Imagery', 'wms')
    if not layer.isValid():
        raise ValueError(
            'Could not add Esri imagery. Check the QGIS WMS/XYZ provider, or add your own basemap in QGIS.'
        )
    layer.setCustomProperty('collar/basemap', 'esri_world_imagery')
    layer.resampleFilter().setZoomedInResampler(QgsBilinearRasterResampler())
    metadata = layer.metadata()
    metadata.setTitle('Esri World Imagery')
    metadata.setRights([ESRI_ATTRIBUTION])
    metadata.setAbstract(
        'Online basemap. '
        + ESRI_ATTRIBUTION
        + '. Source: https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9. Provider terms and attribution apply.'
    )
    layer.setMetadata(metadata)
    layer.serverProperties().setAttribution(ESRI_ATTRIBUTION)
    layer.serverProperties().setAttributionUrl(
        'https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9'
    )
    project.addMapLayer(layer, False)
    project.layerTreeRoot().addLayer(layer)
    # A custom layer order may be enabled independently of the Layers panel.
    root = project.layerTreeRoot()
    if root.hasCustomLayerOrder():
        order = [item for item in root.customLayerOrder() if item.id() != layer.id()]
        root.setCustomLayerOrder(order + [layer])
    return layer
