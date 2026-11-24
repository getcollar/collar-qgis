"""Collar's scoped native interface and local, non-sensitive preferences."""

from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

INTERVALS = [
    (30, '30 seconds'),
    (60, '1 minute'),
    (120, '2 minutes'),
    (300, '5 minutes'),
    (600, '10 minutes'),
    (900, '15 minutes'),
    (1800, '30 minutes'),
    (3600, '1 hour'),
]


def preferences(store):
    enabled = str(store.value('collar/autoRefreshEnabled', 'true')).lower() in ('true', '1')
    basemap = str(store.value('collar/includeBasemap', 'true')).lower() in ('true', '1')
    try:
        seconds = int(store.value('collar/refreshSeconds', 120))
    except (ValueError, TypeError):
        seconds = 120
    return {
        'enabled': enabled,
        'seconds': seconds if seconds in dict(INTERVALS) else 120,
        'basemap': basemap,
    }


def style():
    return """
    QWidget#CollarPanel, QDialog#CollarSettings { background: palette(window); }
    QWidget#CollarHeader { background: #173f35; border-radius: 10px; }
    QWidget#CollarHeader QLabel { color: #f8f7f3; background: transparent; }
    QLabel#Section { color: #739b7b; font-weight: 600; margin-top: 8px; }
    QLabel#Muted { color: palette(mid); }
    QLabel#Connection { color: #8aa37e; font-weight: 600; }
    QPushButton { padding: 8px 12px; border: 1px solid palette(mid); border-radius: 6px; background: palette(button); color: palette(button-text); }
    QPushButton:hover { border-color: #8aa37e; }
    QPushButton:focus { border: 2px solid #8aa37e; }
    QPushButton:disabled { color: palette(mid); border-color: palette(midlight); }
    QPushButton[primary="true"] { background: #8aa37e; color: #122c24; border-color: #8aa37e; font-weight: 600; }
    QPushButton[primary="true"]:hover { background: #a3b898; }
    QPushButton[primary="true"]:disabled { background: palette(midlight); color: palette(mid); }
    QComboBox, QListWidget { padding: 6px; border: 1px solid palette(mid); border-radius: 6px; background: palette(base); color: palette(text); }
    QListWidget::item { padding: 6px 2px; }
    QProgressBar { max-height: 5px; border: 0; background: palette(midlight); }
    QProgressBar::chunk { background: #8aa37e; }
    """


def brand_header(parent=None):
    header = QWidget(parent)
    header.setObjectName('CollarHeader')
    layout = QVBoxLayout(header)
    layout.setContentsMargins(18, 16, 18, 16)
    logo = QLabel()
    logo.setPixmap(QIcon(str(Path(__file__).parent / 'assets/wordmark.svg')).pixmap(150, 30))
    logo.setAccessibleName('Collar')
    layout.addWidget(logo)
    layout.addWidget(QLabel('Connected planning · QGIS'))
    return header


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('CollarSettings')
        self.setWindowTitle('Collar · Plugin settings')
        self.setStyleSheet(style())
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(brand_header())
        title = QLabel('Synchronisation settings')
        title.setStyleSheet('font-size:18px; font-weight:600; margin-top:8px')
        layout.addWidget(title)
        self.enabled = QCheckBox('Automatically refresh from Collar')
        layout.addWidget(self.enabled)
        row = QHBoxLayout()
        row.addWidget(QLabel('Refresh frequency'))
        self.interval = QComboBox()
        for seconds, label in INTERVALS:
            self.interval.addItem('Every ' + label, seconds)
        row.addWidget(self.interval, 1)
        layout.addLayout(row)
        self.enabled.toggled.connect(self.interval.setEnabled)
        hint = QLabel(
            'Keep project layers up to date. Layers with local edits are skipped. Changes you make in QGIS are only sent when you choose Sync changes to Collar.'
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.basemap = QCheckBox('Include Esri imagery when loading a project')
        layout.addWidget(self.basemap)
        hint = QLabel(
            'Adds a basemap if no raster is present. Imagery is requested directly from Esri. You can use your own basemap instead.'
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setProperty('primary', True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def reset(self, values):
        self.enabled.setChecked(values['enabled'])
        self.interval.setCurrentIndex(self.interval.findData(values['seconds']))
        self.interval.setEnabled(values['enabled'])
        self.basemap.setChecked(values['basemap'])

    def values(self):
        return {
            'enabled': self.enabled.isChecked(),
            'seconds': self.interval.currentData(),
            'basemap': self.basemap.isChecked(),
        }
