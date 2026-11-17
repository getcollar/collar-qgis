"""Temporary canvas preview; only explicit Submit creates a relocation request."""
import math
import uuid
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QProgressBar)
from qgis.core import (Qgis, QgsProject, QgsPointXY, QgsGeometry, QgsDistanceArea,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem)
from qgis.gui import QgsMapToolEmitPoint, QgsVertexMarker, QgsRubberBand
from .ui import style


class MoveReview(QDialog):
    submitted = pyqtSignal(dict)

    def __init__(self, parent, canvas, layer, feature):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Tool)
        self.setWindowTitle('Collar · Review proposed hole move')
        self.setObjectName('CollarSettings')
        self.setStyleSheet(style())
        self.setMinimumWidth(380)
        self.canvas, self.layer_id = canvas, layer.id()
        self.previous_tool = canvas.mapTool()
        self.target = None
        self.busy = False
        self.cleaned = False
        self.client_id, self.last_content = str(uuid.uuid4()), None
        self.wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        transform = QgsCoordinateTransform(layer.crs(), self.wgs84, QgsProject.instance())
        self.origin = transform.transform(QgsPointXY(feature.geometry().asPoint()))
        self.revision = str(feature['qgis_revision'])
        self.tool = QgsMapToolEmitPoint(canvas)
        self.tool.canvasClicked.connect(self.pick)
        self.original_marker = QgsVertexMarker(canvas)
        self.original_marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
        self.original_marker.setIconSize(14)
        self.original_marker.setPenWidth(3)
        self.original_marker.setColor(QColor('#173f35'))
        self.original_marker.setFillColor(QColor('#ffffff'))
        self.proposed_marker = QgsVertexMarker(canvas)
        self.proposed_marker.setIconType(QgsVertexMarker.ICON_CROSS)
        self.proposed_marker.setIconSize(24)
        self.proposed_marker.setPenWidth(4)
        self.proposed_marker.setColor(QColor('#dc7626'))
        self.proposed_marker.hide()
        self.line = QgsRubberBand(canvas, Qgis.GeometryType.Line)
        self.line.setColor(QColor('#dc7626'))
        self.line.setWidth(3)
        self.line.setLineStyle(Qt.PenStyle.DashLine)
        self.line.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        title = QLabel('Propose a new hole location')
        title.setStyleSheet('font-size:18px;font-weight:600')
        layout.addWidget(title)
        self.hole_label = QLabel(str(feature['name'] or feature['id']))
        self.hole_label.setTextFormat(Qt.TextFormat.PlainText)
        self.hole_label.setWordWrap(True)
        layout.addWidget(self.hole_label)
        self.instruction = QLabel('Click a new position on the QGIS map. An orange cross and dashed line will show your proposal. Click again to adjust it.')
        self.instruction.setWordWrap(True)
        layout.addWidget(self.instruction)
        self.choose_button = QPushButton('Choose location on map')
        self.choose_button.clicked.connect(self.choose_location)
        layout.addWidget(self.choose_button)
        self.coordinates = QLabel('Original: {:.6f}, {:.6f}\nProposed: choose a position on the map'.format(self.origin.y(), self.origin.x()))
        self.coordinates.setTextFormat(Qt.TextFormat.PlainText)
        self.coordinates.setWordWrap(True)
        layout.addWidget(self.coordinates)
        layout.addWidget(QLabel('Reason for the move (required · up to 2,000 characters)'))
        self.reason = QPlainTextEdit()
        self.reason.setPlaceholderText('Explain why this hole should move…')
        self.reason.setMaximumHeight(100)
        self.reason.textChanged.connect(self.update_submit)
        layout.addWidget(self.reason)
        hint = QLabel('The original hole remains unchanged. Submit sends a proposal to Collar for another authorised planner to approve.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.feedback = QLabel('Choose a location and enter a reason before submitting.')
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button = QPushButton('Submit proposal')
        self.submit_button.setProperty('primary', True)
        self.submit_button.clicked.connect(self.submit)
        self.submit_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        row.addWidget(self.submit_button)
        layout.addLayout(row)
        self.canvas.destinationCrsChanged.connect(self.draw_preview)
        QgsProject.instance().layersWillBeRemoved.connect(self.layers_removed)
        self.finished.connect(self.cleanup)
        self.draw_preview()
        self.choose_location()

    def choose_location(self):
        if not self.busy:
            self.canvas.setMapTool(self.tool)
            self.feedback.setText('Click the map to choose or adjust the proposed position. Nothing is sent until you select Submit proposal.')

    def pick(self, point, button):
        if self.busy or button != Qt.MouseButton.LeftButton:
            return
        try:
            transform = QgsCoordinateTransform(self.canvas.mapSettings().destinationCrs(), self.wgs84, QgsProject.instance())
            target = transform.transform(QgsPointXY(point))
            if not (math.isfinite(target.x()) and math.isfinite(target.y()) and -180 <= target.x() <= 180 and -90 < target.y() < 90):
                raise ValueError('Choose a valid location on the map.')
            measure = QgsDistanceArea()
            measure.setSourceCrs(self.wgs84, QgsProject.instance().transformContext())
            measure.setEllipsoid('WGS84')
            distance = measure.measureLine(self.origin, target)
            if distance < 0.01:
                raise ValueError('Choose a position different from the original hole.')
            self.target = target
            self.draw_preview()
            self.coordinates.setText('Original: {:.6f}, {:.6f}\nProposed: {:.6f}, {:.6f}\nDistance: {:,.1f} m'.format(self.origin.y(), self.origin.x(), target.y(), target.x(), distance))
            self.feedback.setText('Review the orange marker and dashed line. Click the map again to adjust the location, or enter a reason and submit.')
        except Exception:
            # An invalid click must not leave a previous valid target submittable.
            self.target = None
            self.proposed_marker.hide()
            self.line.hide()
            self.coordinates.setText('Proposed: choose a valid position different from the original hole.')
            self.feedback.setText('That position cannot be used. Choose another location on the map.')
        self.update_submit()

    def draw_preview(self):
        if self.cleaned:
            return
        try:
            transform = QgsCoordinateTransform(self.wgs84, self.canvas.mapSettings().destinationCrs(), QgsProject.instance())
            original = transform.transform(self.origin)
            self.original_marker.setCenter(original)
            if self.target is not None:
                proposed = transform.transform(self.target)
                self.proposed_marker.setCenter(proposed)
                self.proposed_marker.show()
                self.line.setToGeometry(QgsGeometry.fromPolylineXY([original, proposed]), None)
                self.line.show()
        except Exception:
            self.feedback.setText('The preview cannot be displayed in this map projection. Cancel and choose a suitable project CRS.')
            self.target = None
            self.proposed_marker.hide()
            self.line.hide()
            self.update_submit()

    def update_submit(self):
        self.submit_button.setEnabled(not self.busy and self.target is not None and 0 < len(self.reason.toPlainText().strip()) <= 2000)

    def set_busy(self, busy):
        self.busy = busy
        self.progress.setVisible(busy)
        self.reason.setEnabled(not busy)
        self.choose_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not busy)
        if busy:
            self.feedback.setText('Sending your proposal to Collar…')
        self.update_submit()

    def submit(self):
        if not self.submit_button.isEnabled():
            return
        content = (self.target.x(), self.target.y(), self.reason.toPlainText().strip())
        if self.last_content is not None and content != self.last_content:
            self.client_id = str(uuid.uuid4())
        self.last_content = content
        self.submitted.emit({'clientId':self.client_id, 'revision':self.revision,
                             'lng':content[0], 'lat':content[1], 'comment':content[2]})

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def dispose(self):
        self.busy = False
        self.reject()

    def layers_removed(self, ids):
        if self.layer_id in ids:
            self.dispose()

    def cleanup(self, *_):
        if self.cleaned:
            return
        self.cleaned = True
        self.canvas.destinationCrsChanged.disconnect(self.draw_preview)
        QgsProject.instance().layersWillBeRemoved.disconnect(self.layers_removed)
        if self.canvas.mapTool() is self.tool:
            if self.previous_tool:
                self.canvas.setMapTool(self.previous_tool)
            else:
                self.canvas.unsetMapTool(self.tool)
        for item in (self.original_marker, self.proposed_marker, self.line):
            self.canvas.scene().removeItem(item)
        self.tool.deleteLater()
