"""Collar for QGIS: native spatial workspace integration."""
def classFactory(iface):
    from .plugin import CollarPlugin
    return CollarPlugin(iface)
