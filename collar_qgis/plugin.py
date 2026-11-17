import json
import uuid
from datetime import datetime, timezone
from urllib.parse import quote
from qgis.PyQt.QtCore import Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QIcon, QDesktopServices
from qgis.PyQt.QtWidgets import (QAction, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGridLayout, QScrollArea, QPushButton, QComboBox, QListWidget, QListWidgetItem, QCheckBox, QProgressBar,
    QMessageBox, QInputDialog, QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem, QPlainTextEdit)
from .move_review import MoveReview
from .ui import SettingsDialog, preferences, style, brand_header, INTERVALS
from qgis.core import QgsSettings
from .uploads import FilePart
from .sync import batch_length
from .catalogue import OPERATIONAL_LAYERS, OPERATIONAL_IDS, separated_specs, layer_features
from .basemaps import add_esri_basemap, has_raster_basemap, has_esri_basemap, restore_esri_basemaps, stop_imagery
from qgis.core import QgsRasterLayer, Qgis, QgsProject
from pathlib import Path
from .auth import TokenStore, BrowserLogin
from .network import request, ORIGIN
from .layers import connected_layers, create_layer, dirty, pending, replace, apply_results, export_vector, snapshot, add_features, default_style, archive_combined_layer

EDITABLE_KINDS = [
    ('managed_tracks', 'Tracks'),
    ('clearing', 'Clearing areas'),
    ('boundary', 'Boundaries'),
    ('annotation', 'Annotations'),
    ('marker', 'Markers / pegs'),
    ('other', 'Other'),
]
EDITABLE_KIND_IDS = [item[0] for item in EDITABLE_KINDS]


class CollarPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.store = TokenStore()
        self.dock = None
        self.tasks = []
        self.busy = False
        self.closed = False
        self.upload_id = None
        self.generation = 0
        self.style_config = {}
        self.preferences_store = QgsSettings()
        self.settings_dialog = None
        self.move_review = None
        self.identity = None
        self.connection_state = "disconnected"

    def initGui(self):
        self.action = QAction(QIcon(str(Path(__file__).parent / 'icon.svg')), 'Collar for QGIS', self.iface.mainWindow())
        self.action.triggered.connect(self.show)
        self.iface.addPluginToMenu('Collar', self.action)
        self.iface.addToolBarIcon(self.action)
        self.publish_action = QAction('Publish to Collar', self.iface.mainWindow())
        self.publish_action.triggered.connect(self.publish)
        self.iface.addCustomActionForLayerType(self.publish_action, 'Collar', Qgis.LayerType.Vector, True)
        self.show()
        QgsProject.instance().readProject.connect(restore_esri_basemaps)
        QgsProject.instance().layersAdded.connect(restore_esri_basemaps)
        restore_esri_basemaps()

    def show(self):
        if self.dock:
            self.dock.show()
            self.dock.raise_()
            return
        self.dock = QDockWidget('Collar for QGIS', self.iface.mainWindow())
        self.dock.setObjectName('CollarForQgis')
        self.preferences = preferences(self.preferences_store)
        body = QWidget()
        body.setObjectName("CollarPanel")
        body.setStyleSheet(style())
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(brand_header())
        heading = QHBoxLayout()
        self.connection_badge = QLabel('Disconnected')
        self.connection_badge.setObjectName('Connection')
        heading.addWidget(self.connection_badge, 1)
        self.settings_button = QPushButton('Settings')
        self.settings_button.clicked.connect(self.show_settings)
        heading.addWidget(self.settings_button)
        layout.addLayout(heading)
        self.account_name = QLabel('Connect your Collar account')
        self.account_name.setTextFormat(Qt.TextFormat.PlainText)
        self.account_name.setWordWrap(True)
        self.account_name.setStyleSheet('font-weight:600')
        layout.addWidget(self.account_name)
        self.account_email = QLabel()
        self.account_email.setTextFormat(Qt.TextFormat.PlainText)
        self.account_email.setWordWrap(True)
        layout.addWidget(self.account_email)
        self.status = QLabel('Disconnected')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.connect_button = QPushButton('Connect to Collar')
        self.connect_button.setProperty('primary', True)
        self.connect_button.clicked.connect(self.connect)
        self.signout_button = QPushButton('Sign out')
        self.signout_button.clicked.connect(self.signout)
        row.addWidget(self.connect_button)
        row.addWidget(self.signout_button)
        layout.addLayout(row)
        section = QLabel('WORKSPACE')
        section.setObjectName('Section')
        layout.addWidget(section)
        layout.addWidget(QLabel('Organisation'))
        self.organisations = QComboBox()
        self.organisations.currentIndexChanged.connect(self.load_projects)
        layout.addWidget(self.organisations)
        layout.addWidget(QLabel('Project'))
        self.projects = QComboBox()
        self.projects.currentIndexChanged.connect(self.discover)
        layout.addWidget(self.projects)
        section = QLabel('PROJECT LAYERS')
        section.setObjectName('Section')
        layout.addWidget(section)
        self.layer_list = QListWidget()
        self.layer_list.setMinimumHeight(150)
        layout.addWidget(self.layer_list)
        self.basemap_credit = QLabel('<a href="https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9">Imagery © Esri, Maxar, Earthstar Geographics and the GIS User Community</a>')
        self.basemap_credit.setOpenExternalLinks(True)
        self.basemap_credit.setWordWrap(True)
        self.basemap_credit.setStyleSheet('font-size:10px')
        self.basemap_credit.setVisible(has_esri_basemap())
        layout.addWidget(self.basemap_credit)
        self.controls = []
        presentation_row = None
        load_row = QHBoxLayout()
        layout.addLayout(load_row)
        actions_grid = None
        for label, handler in [('Load selected layers', self.load), ('Refresh layers', self.refresh),
                               ('Sync changes to Collar', self.sync), ('Publish selected layer to Collar', self.publish),
                               ('Review conflicts / reload layer', self.reload_selected),
                               ('Open project in Collar', self.open_project), ('View all hole details', self.open_hole), ('Propose selected hole move', self.propose_move), ('Add Esri basemap', self.add_basemap), ('Apply Collar styling', self.apply_collar_style), ('Cancel pending layer upload', self.cancel_upload)]:
            button = QPushButton(label)
            button.clicked.connect(handler)
            if label in ['Load selected layers', 'Sync changes to Collar']:
                button.setProperty('primary', True)
            index = len(self.controls)
            if index in (0, 1):
                button.setText('Load layers' if index == 0 else 'Refresh layers')
                button.setToolTip(label)
                load_row.addWidget(button)
            elif index in range(3, 8):
                if actions_grid is None:
                    section = QLabel('PROJECT ACTIONS')
                    section.setObjectName('Section')
                    layout.addWidget(section)
                    actions_grid = QGridLayout()
                    layout.addLayout(actions_grid)
                button.setText({3:'Publish layer', 4:'Review conflicts', 5:'Open project', 6:'Hole details', 7:'Propose hole move'}[index])
                button.setToolTip(label)
                actions_grid.addWidget(button, (index - 3) // 2, (index - 3) % 2, 1, 2 if index == 7 else 1)
            elif label in ['Add Esri basemap', 'Apply Collar styling']:
                if presentation_row is None:
                    presentation_row = QHBoxLayout()
                    layout.addLayout(presentation_row)
                button.setText('Add basemap' if label == 'Add Esri basemap' else 'Collar styling')
                button.setToolTip(label)
                presentation_row.addWidget(button)
            else:
                layout.addWidget(button)
            self.controls.append(button)
        self.refresh_summary = QLabel()
        self.refresh_summary.setWordWrap(True)
        layout.addWidget(self.refresh_summary)
        self.last_sync = QLabel('Not synchronised')
        self.last_sync.setWordWrap(True)
        layout.addWidget(self.last_sync)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        self.dock.setWidget(scroll)
        self.dock.setMinimumWidth(340)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.login = BrowserLogin(self.dock)
        self.login.ready.connect(self.exchange)
        self.login.failed.connect(self.error)
        self.timer = QTimer(self.dock)
        self.timer.timeout.connect(self.auto_refresh)
        self.configure_refresh()
        self.count_timer = QTimer(self.dock)
        self.count_timer.timeout.connect(self.update_count)
        self.count_timer.start(3000)
        self.set_busy(False)
        self.update_connection("checking" if self.store.auth_id else "disconnected")
        if self.store.auth_id:
            self.fetch_identity()

    def show_settings(self):
        if not self.settings_dialog:
            self.settings_dialog = SettingsDialog(self.dock)
            self.settings_dialog.accepted.connect(self.save_settings)
        if not self.settings_dialog.isVisible():
            self.settings_dialog.reset(self.preferences)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def save_settings(self):
        self.preferences = self.settings_dialog.values()
        for key, value in [('autoRefreshEnabled', self.preferences['enabled']),
                           ('refreshSeconds', self.preferences['seconds']),
                           ('includeBasemap', self.preferences['basemap'])]:
            self.preferences_store.setValue('collar/' + key, value)
        self.configure_refresh()
        self.status.setText('Plugin settings saved.')

    def configure_refresh(self):
        enabled = self.preferences['enabled']
        self.refresh_summary.setText('Automatic refresh · Every ' + dict(INTERVALS)[self.preferences['seconds']] if enabled else 'Automatic refresh off · Refresh layers manually')
        self.timer.stop()
        if enabled and self.connection_state in ('connected', 'issue'):
            self.timer.start(self.preferences['seconds'] * 1000)

    def update_connection(self, state):
        self.connection_state = state
        labels = {'disconnected':'Disconnected', 'checking':'Checking connection…',
                  'connected':'● Connected', 'issue':'Connection unavailable', 'expired':'Session expired'}
        self.connection_badge.setText(labels[state])
        has_session = bool(self.store.auth_id)
        self.connect_button.setVisible(not has_session)
        self.signout_button.setVisible(has_session)
        user = self.identity or {}
        name = user.get('name') or ' '.join(str(user.get(key) or '') for key in ('firstName', 'lastName')).strip()
        self.account_name.setText(name or ('Collar account' if has_session else 'Connect your Collar account'))
        self.account_email.setText(str(user.get('email') or ''))
        self.account_email.setVisible(bool(user.get('email')))
        if state == 'expired':
            self.status.setText('Your session has expired. Sign out, then connect again.')
        self.configure_refresh()

    def fetch_identity(self):
        self.set_busy(True)
        def loaded(result):
            self.identity = result['user']
            self.update_connection('connected')
            self.fetch_organisations()
        self.call('GET', '/api/v1/me', None, loaded)

    def set_busy(self, value):
        self.busy = value
        self.progress.setVisible(value)
        for control in self.controls + [self.organisations, self.projects, self.layer_list]:
            control.setEnabled(not value and self.move_review is None)
        self.connect_button.setEnabled(not value)
        self.signout_button.setEnabled(not value)
        if self.move_review:
            self.move_review.set_busy(value)
        if self.controls:
            self.controls[-1].setVisible(bool(self.upload_id))
            self.controls[-1].setEnabled(bool(self.upload_id))

    def notify(self, text):
        self.status.setText(text)
        self.iface.messageBar().pushSuccess('Collar', text)

    def error(self, text):
        self.set_busy(False)
        self.login.complete(False)
        if self.move_review:
            self.move_review.feedback.setText(text)
        self.status.setText(text)
        self.iface.messageBar().pushWarning('Collar', text)

    def call(self, method, path, body, done, anonymous=False):
        token = None if anonymous else self.store.read()
        if not anonymous and not token:
            if self.store.auth_id:
                self.update_connection('issue')
            self.error('Unlock the QGIS authentication database, or sign out and connect again.' if self.store.auth_id else 'Connect to Collar first.')
            return
        generation = self.generation
        task = None
        def completed(result, error):
            self.tasks[:] = [active for active in self.tasks if active is not task]
            if self.closed or generation != self.generation:
                return
            if error:
                if not anonymous and getattr(task, 'http_status', None) == 401:
                    self.update_connection('expired')
                elif not anonymous and getattr(task, 'connection_error', False):
                    self.update_connection('issue')
                self.progress.setRange(0, 0)
                self.error(error)
            else:
                try:
                    if not anonymous and self.identity:
                        self.update_connection('connected')
                    done(result)
                except Exception as failure:
                    self.error(str(failure))
        task = request(method, path, token, self.organisations.currentData(), body, completed)
        self.tasks.append(task)

    def connect(self):
        if self.busy or self.store.auth_id:
            return
        self.set_busy(True)
        self.status.setText('Finish sign-in in your browser…')
        try:
            self.login.start()
        except Exception as error:
            self.error(str(error))

    def exchange(self, payload):
        def saved(result):
            try:
                self.store.save(result['token'])
            except Exception as error:
                # Revoke the new session if secure storage was declined.
                request('POST', '/api/auth/sign-out', result['token'], None, {}, lambda *_: None)
                self.login.complete(False)
                self.error(str(error))
                return
            self.login.complete(True)
            self.update_connection("checking")
            self.fetch_identity()
        self.call('POST', '/api/integrations/qgis/token', payload, saved, anonymous=True)

    def fetch_organisations(self):
        self.set_busy(True)
        def loaded(rows):
            self.organisations.blockSignals(True)
            self.organisations.clear()
            for row in rows:
                self.organisations.addItem(row['name'], row['id'])
            self.organisations.blockSignals(False)
            self.load_projects()
        self.call('GET', '/api/v1/organisations', None, loaded)

    def load_projects(self):
        if not self.organisations.currentData():
            self.set_busy(False)
            return
        self.set_busy(True)
        def loaded(rows):
            self.projects.blockSignals(True)
            self.projects.clear()
            for row in rows:
                self.projects.addItem(row['name'], row['id'])
            self.projects.blockSignals(False)
            if rows:
                self.discover()
            else:
                self.layer_list.clear()
                self.set_busy(False)
                self.status.setText('No accessible projects')
        self.call('GET', '/api/v1/qgis/projects', None, loaded)

    def prefix(self):
        return '/api/v1/qgis/projects/' + quote(str(self.projects.currentData()), safe='')

    def discover(self):
        if not self.projects.currentData():
            self.set_busy(False)
            return
        self.set_busy(True)
        def loaded(result):
            self.style_config = {
                'mapStyle': result.get('mapStyle', {}),
                'featureStyles': result.get('featureStyles', {}),
                'trackStyles': result.get('trackStyles', {}),
            }
            self.layer_list.clear()
            for layer in [part for spec in result['layers'] for part in separated_specs(spec)]:
                suffix = ''
                if layer['id'] == 'managed_tracks':
                    suffix = ' · editable' if layer['editable'] else ' · published read only'
                elif not layer['editable']:
                    suffix = ' · read only'
                item = QListWidgetItem(layer['name'] + suffix)
                item.setData(Qt.ItemDataRole.UserRole, layer)
                checked = layer['id'] in OPERATIONAL_IDS or layer['id'] == 'managed_tracks'
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self.layer_list.addItem(item)
            self.set_busy(False)
            self.status.setText('Connected · ' + self.projects.currentText())
        self.call('GET', self.prefix() + '/layers?separate=1', None, loaded)

    def scoped_layers(self):
        return connected_layers(self.organisations.currentData(), self.projects.currentData())

    def load(self):
        selected = [self.layer_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.layer_list.count()) if self.layer_list.item(i).checkState() == Qt.CheckState.Checked]
        if not selected:
            self.error('Select at least one layer')
            return
        self.set_busy(True)
        def next_layer():
            if not selected:
                self.set_busy(False)
                if OPERATIONAL_IDS.issubset({layer.customProperty('collar/category') for layer in self.scoped_layers()}):
                    for layer in list(self.scoped_layers()):
                        archive_combined_layer(layer)
                if self.preferences['basemap'] and not has_raster_basemap():
                    self.add_basemap()
                self.notify('Project layers loaded')
                return
            spec = selected.pop(0)
            if any(layer.customProperty('collar/category') == spec['id'] for layer in self.scoped_layers()):
                next_layer()
                return
            def loaded(collection):
                self.install(spec, collection['features'])
                next_layer()
            self.call('GET', spec['source'], None, loaded)
        next_layer()

    def install(self, spec, features, publishing=False):
        if spec['id'] == 'operational':
            return [layer for part in separated_specs(spec) for layer in self.install(part, features)]
        features = layer_features(spec, features)
        groups = {}
        for feature in features:
            groups.setdefault(feature['geometry']['type'], []).append(feature)
        # Empty editable layers still support native QGIS feature creation.
        if not groups and (spec['editable'] or spec.get('geometry')):
            if spec.get('geometry'):
                empty = spec['geometry']
            elif spec['id'] == 'managed_tracks':
                empty = 'LineString'
            elif spec['id'] in ['clearing', 'boundary', 'work_area', 'rehab_area']:
                empty = 'Polygon'
            else:
                empty = 'Point'
            groups[empty] = []
        installed = []
        for geometry, values in groups.items():
            existing = next((layer for layer in self.scoped_layers() if layer.customProperty('collar/category') == spec['id'] and layer.customProperty('collar/geometry') == geometry), None)
            if publishing and existing:
                if existing.isEditable() or existing.readOnly():
                    raise ValueError('Close the connected layer edit session before adding published features')
                add_features(existing, values, spec['id'])
                existing.triggerRepaint()
                installed.append(existing)
                continue
            if existing:
                installed.append(existing)
                continue
            name = spec['name'] if spec.get('geometry') else spec['name'] + ' · ' + geometry
            layer = create_layer(name, geometry, values, self.organisations.currentData(), self.projects.currentData(), spec['id'], spec['editable'], self.projects.currentText(), self.style_config)
            layer.setCustomProperty('collar/source', spec['source'])
            if spec.get('entityType'):
                layer.setCustomProperty('collar/entity_type', spec['entityType'])
            if publishing:
                layer.setCustomProperty('collar/baseline', '{}')
            installed.append(layer)
        return installed

    def refresh(self, automatic=False):
        if self.busy:
            return
        layers = self.scoped_layers()
        eligible = [layer for layer in layers if not dirty(layer)]
        skipped = len(layers) - len(eligible)
        self.set_busy(True)
        def next_layer():
            if not eligible:
                self.set_busy(False)
                self.last_sync.setText('Last refreshed: ' + datetime.now(timezone.utc).strftime('%H:%M UTC'))
                self.status.setText('Refresh complete' + (' · {} layer(s) kept with local edits'.format(skipped) if skipped else ''))
                if not automatic:
                    self.notify(self.status.text())
                return
            layer = eligible.pop(0)
            def loaded(collection):
                if dirty(layer):
                    next_layer()
                    return
                if layer.customProperty('collar/category') == 'operational' and layer.readOnly():
                    self.install({'id':'operational','source':layer.customProperty('collar/source')}, collection['features'])
                    archive_combined_layer(layer)
                    next_layer()
                    return
                spec = {'entityType':layer.customProperty('collar/entity_type', None),'geometry':layer.customProperty('collar/geometry')}
                features = [f for f in layer_features(spec, collection['features']) if f['geometry']['type'] == layer.customProperty('collar/geometry')]
                replace(layer, features)
                next_layer()
            self.call('GET', layer.customProperty('collar/source'), None, loaded)
        next_layer()

    def auto_refresh(self):
        if self.preferences['enabled'] and self.connection_state in ('connected', 'issue') and self.store.auth_id and self.projects.currentData() and not self.busy and self.move_review is None:
            self.refresh(automatic=True)

    def update_count(self):
        if self.busy:
            return
        try:
            count = sum(len(pending(layer)) for layer in self.scoped_layers() if not layer.readOnly() and not layer.isEditable())
            self.controls[2].setText('Sync changes to Collar ({})'.format(count))
        except ValueError:
            self.status.setText('A protected feature was changed. Review this layer before sync.')

    def review(self, queue):
        dialog = QDialog(self.dock)
        dialog.setWindowTitle('Review changes to Collar')
        dialog.resize(680, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Publish these saved spatial edits? Conflicts will keep your local changes.'))
        table = QTableWidget(len(queue), 3)
        table.setHorizontalHeaderLabels(['Action', 'Layer / feature', 'Revision'])
        for index, (layer, key, change) in enumerate(queue):
            for column, text in enumerate([change['action'].title(), layer.name() + ' / ' + (change.get('attributes', {}).get('name') or key), str(change.get('revision', 'New'))]):
                table.setItem(index, column, QTableWidgetItem(text))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Publish changes')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def sync(self):
        if self.busy:
            return
        try:
            if any(layer.isEditable() for layer in self.scoped_layers()):
                raise ValueError('Save or roll back QGIS edit sessions before reviewing changes. Saving stays local until you publish.')
            queue = [(layer, key, change) for layer in self.scoped_layers() if not layer.readOnly() for key, change in pending(layer)]
            if not queue:
                self.refresh()
                return
            for index in range(0, len(queue), 50):
                batch_length(queue[index:index + 50])
            if not QgsProject.instance().fileName():
                raise ValueError('Save this QGIS project before synchronising so connection snapshots and retry IDs survive reopening.')
            if not self.review(queue):
                return
            if not QgsProject.instance().write():
                raise ValueError('Could not save connection snapshots. Save the QGIS project and try again.')
        except Exception as error:
            self.error(str(error))
            return
        self.set_busy(True)
        failures = []
        conflicts = []
        applied = [0]
        def next_batch():
            if not queue:
                self.set_busy(False)
                self.last_sync.setText('Last sync: ' + datetime.now(timezone.utc).strftime('%H:%M UTC'))
                if failures:
                    self.error('{} saved; {} conflict(s) or rejected edit(s). Local edits retained.'.format(applied[0], len(failures)))
                    self.review_conflicts(conflicts, failures)
                else:
                    self.notify('{} changes synchronised'.format(applied[0]))
                    self.refresh(automatic=True)
                return
            length = batch_length(queue)
            batch, queue[:] = queue[:length], queue[length:]
            def saved(result):
                by_layer = {}
                for layer, key, change in batch:
                    by_layer.setdefault(layer.id(), (layer, []))[1].append((key, change))
                for layer, submitted in by_layer.values():
                    if layer.isEditable():
                        raise ValueError('Close the QGIS edit session, then retry sync to recover the server receipts.')
                    apply_results(layer, submitted, result['results'])
                if not QgsProject.instance().write():
                    raise ValueError('Changes saved to Collar; save your QGIS project to retain the updated sync snapshots.')
                for row in result['results']:
                    if row['status'] == 'applied':
                        applied[0] += 1
                    else:
                        failures.append(row.get('message', 'Change could not be saved'))
                        matched = next(((layer, key, change) for layer, key, change in batch if change['changeId'] == row['changeId']), None)
                        if matched:
                            conflicts.append((matched, row))
                next_batch()
            self.call('POST', self.prefix() + '/sync', {'changes':[change for _, _, change in batch]}, saved)
        next_batch()

    def review_conflicts(self, conflicts, failures):
        dialog = QDialog(self.dock)
        dialog.setWindowTitle('Review local and Collar changes')
        dialog.resize(900, 560)
        layout = QVBoxLayout(dialog)
        description = QLabel('Your local edits are retained. Compare the versions below, then keep working locally or explicitly reload the active layer from Collar.')
        description.setWordWrap(True)
        layout.addWidget(description)
        selector = QComboBox()
        layout.addWidget(selector)
        row = QHBoxLayout()
        local, remote = QPlainTextEdit(), QPlainTextEdit()
        for title, editor in [('Your submitted change', local), ('Latest Collar version', remote)]:
            column = QVBoxLayout()
            column.addWidget(QLabel(title))
            editor.setReadOnly(True)
            column.addWidget(editor)
            row.addLayout(column)
        layout.addLayout(row)
        def selected(index):
            if index < 0 or index >= len(conflicts):
                return
            (layer, key, change), result = conflicts[index]
            local.setPlainText(json.dumps(change, indent=2))
            remote.setPlainText(json.dumps(result.get('current', {'message':result.get('message', 'Latest version is unavailable. Refresh after reviewing your local copy.')}), indent=2))
            self.iface.setActiveLayer(layer)
        selector.currentIndexChanged.connect(selected)
        for (layer, key, change), result in conflicts:
            selector.addItem(layer.name() + ' / ' + (change.get('attributes', {}).get('name') or key))
        if not conflicts:
            remote.setPlainText('\n'.join(failures[:30]))
        selected(0)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def reload_selected(self):
        layer = self.iface.activeLayer()
        if layer not in self.scoped_layers():
            self.error('Select a connected layer in the current Collar project')
            return
        if layer.isEditable():
            self.error('Close the QGIS edit session first')
            return
        if QMessageBox.question(self.dock, 'Reload latest Collar data', 'Discard all saved local edits in this layer and load the latest Collar version?') != QMessageBox.StandardButton.Yes:
            return
        self.set_busy(True)
        def loaded(collection):
            # Baseline is moved only after an explicit discard confirmation and successful fetch.
            layer.setCustomProperty('collar/baseline', json.dumps(snapshot(layer)))
            if layer.customProperty('collar/category') == 'operational':
                self.install({'id':'operational','source':layer.customProperty('collar/source')},collection['features'])
                archive_combined_layer(layer)
            else:
                spec={'entityType':layer.customProperty('collar/entity_type',None),'geometry':layer.customProperty('collar/geometry')}
                replace(layer, [f for f in layer_features(spec,collection['features']) if f['geometry']['type'] == layer.customProperty('collar/geometry')])
            layer.setCustomProperty('collar/identities', '{}')
            self.set_busy(False)
            self.notify('Latest Collar layer loaded')
        self.call('GET', layer.customProperty('collar/source'), None, loaded)

    def publish(self):
        self.show()
        if self.busy:
            return
        if not self.projects.currentData():
            self.error('Connect and choose the destination organisation and project first')
            return
        source = self.iface.activeLayer()
        if isinstance(source, QgsRasterLayer):
            self.publish_reference(source, raster=True)
            return
        mode, ok = QInputDialog.getItem(self.dock, 'Publish to Collar', 'Publishing mode', ['Editable mapping features', 'Named cloud reference layer'], 0, False)
        if not ok:
            return
        if mode == 'Named cloud reference layer':
            self.publish_reference(source)
            return
        labels = [label for _, label in EDITABLE_KINDS]
        choice, ok = QInputDialog.getItem(
            self.dock,
            'Publish vector layer',
            'Category · ' + self.projects.currentText(),
            labels,
            0,
            False,
        )
        if not ok:
            return
        category = EDITABLE_KIND_IDS[labels.index(choice)]
        source = self.iface.activeLayer()
        name, ok = QInputDialog.getText(self.dock, 'Publish vector layer', 'Layer name', text=source.name() if source else '')
        if not ok or not name.strip():
            return
        try:
            features = export_vector(source, category)
            source_path = (
                self.prefix() + '/tracks'
                if category == 'managed_tracks'
                else self.prefix() + '/features?kind=' + category
            )
            spec = {
                'id': category,
                'name': name.strip(),
                'editable': True,
                'geometry': 'LineString' if category == 'managed_tracks' else None,
                'source': source_path,
            }
            self.install(spec, features, publishing=True)
            self.sync()
        except Exception as error:
            self.error(str(error))

    def publish_reference(self, source, raster=False):
        try:
            if source is None or not source.crs().isValid():
                raise ValueError('Select a layer with a valid coordinate system')
            if raster:
                path = Path(source.source())
                if not path.is_file() or path.suffix.lower() not in ['.tif', '.tiff']:
                    raise ValueError('Select a local GeoTIFF. Export other raster providers to GeoTIFF first.')
                stat = path.stat()
                if stat.st_size <= 0 or stat.st_size > 5_000_000_000:
                    raise ValueError('GeoTIFF cloud publishing supports files up to 5 GB, within your organisation storage policy')
                size = stat.st_size
                manifest = {'kind':'original', 'format':'geotiff', 'crs':source.crs().authid() or source.crs().toWkt()}
                payload = None
                file_format = 'geotiff'
                filename = path.name
            else:
                features = export_vector(source, 'other')
                # Preserve the original source attributes in the named reference layer.
                for item, original in zip(features, source.getFeatures()):
                    item['properties'] = {field.name(): (None if str(original[field.name()]) == 'NULL' else original[field.name()]) for field in source.fields()}
                payload = json.dumps({'type':'FeatureCollection','features':features}, default=str).encode('utf-8')
                size = len(payload)
                if size > 16 * 1024 * 1024:
                    raise ValueError('Named vector references must be at most 16 MiB')
                manifest = {'kind':'vector','crs':'EPSG:4326','featureCount':len(features)}
                file_format, filename = 'geojson', source.name()[:100] + '.geojson'
        except Exception as error:
            self.error(str(error))
            return
        self.set_busy(True)
        def choose(configs):
            candidates = [row for row in configs if row['format'] == file_format]
            labels = ['Create a new cloud layer'] + ['Update: ' + row['name'] + ' · ' + row['id'] for row in candidates]
            selection, ok = QInputDialog.getItem(self.dock, 'Destination · ' + self.projects.currentText(), 'Create or update a reference layer', labels, 0, False)
            if not ok:
                self.set_busy(False)
                return
            selected = labels.index(selection)
            if selected:
                layer = candidates[selected - 1]
                if QMessageBox.question(self.dock, 'Replace shared layer source', 'Replace ' + layer['name'] + ' in ' + self.projects.currentText() + '? This publishes a new source version for your team.') != QMessageBox.StandardButton.Yes:
                    self.set_busy(False)
                    return
                start(layer)
                return
            name, ok = QInputDialog.getText(self.dock, 'New cloud layer', 'Layer name (up to 120 characters)', text=source.name()[:120])
            if not ok or not name.strip():
                self.set_busy(False)
                return
            if len(name.strip()) > 120:
                self.error('Layer names may contain at most 120 characters')
                return
            self.call('POST', '/api/v1/maps/layer-configs', {'projectId':self.projects.currentData(),'name':name.strip(),'format':file_format,'expectedFilename':filename[:255],'crs':manifest['crs'][:40]}, start)
        def start(layer):
            self.call('POST', '/api/v1/maps/gis/layers/' + quote(layer['id'], safe='') + '/uploads', {'mode':'cloud','bytes':size,'manifest':manifest}, upload)
        def upload(result):
            self.upload_id = result['id']
            self.set_busy(True)
            self.controls[-1].setEnabled(True)
            part_bytes = result['partBytes']
            total = (size + part_bytes - 1) // part_bytes
            self.progress.setRange(0, total)
            self.progress.setValue(0)
            def part(index):
                if index >= total:
                    self.call('POST', '/api/v1/maps/gis/uploads/' + quote(self.upload_id, safe='') + '/complete', {}, finished)
                    return
                offset = index * part_bytes
                length = min(part_bytes, size - offset)
                data = FilePart(str(path), offset, length, stat.st_size, stat.st_mtime_ns) if raster else payload[offset:offset + length]
                def accepted(_result):
                    self.progress.setValue(index + 1)
                    part(index + 1)
                self.call('PUT', '/api/v1/maps/gis/uploads/' + quote(self.upload_id, safe='') + '/parts/' + str(index + 1), data, accepted)
            part(0)
        def finished(result):
            self.upload_id = None
            self.progress.setRange(0, 0)
            self.set_busy(False)
            self.notify('Layer uploaded' + ('; Collar is processing the source.' if result.get('processing') else ' and shared with the project.'))
            self.discover()
        self.call('GET', '/api/v1/maps/projects/' + quote(self.projects.currentData(), safe='') + '/layer-configs', None, choose)

    def cancel_upload(self):
        if not self.upload_id:
            self.error('There is no pending upload in this session. Other uploads can be managed in Collar GIS storage.')
            return
        upload_id = self.upload_id
        self.generation += 1
        self.set_busy(True)
        def cancelled(_result):
            self.upload_id = None
            self.progress.setRange(0, 0)
            self.set_busy(False)
            self.notify('Pending upload cancelled')
        self.call('DELETE', '/api/v1/maps/gis/uploads/' + quote(upload_id, safe=''), None, cancelled)

    def add_basemap(self):
        try:
            add_esri_basemap()
            self.basemap_credit.show()
            self.notify('Esri imagery basemap added. You can change or remove it in QGIS.')
        except Exception as error:
            self.error(str(error))

    def apply_collar_style(self):
        layer = self.iface.activeLayer()
        if layer not in self.scoped_layers():
            self.error('Select a connected layer in the current Collar project')
            return
        if QMessageBox.question(self.dock, 'Apply Collar styling', 'Replace this layer’s current styling with the colours and labels configured in Collar?') != QMessageBox.StandardButton.Yes:
            return
        self.set_busy(True)
        def loaded(result):
            self.style_config = {
                'mapStyle': result.get('mapStyle', {}),
                'featureStyles': result.get('featureStyles', {}),
                'trackStyles': result.get('trackStyles', {}),
            }
            default_style(layer, self.style_config)
            self.set_busy(False)
            self.notify('Collar styling applied')
        self.call('GET', self.prefix() + '/layers?separate=1', None, loaded)

    def open_project(self):
        if self.projects.currentData():
            QDesktopServices.openUrl(QUrl(ORIGIN + '/projects/' + quote(self.projects.currentData(), safe='')))

    def open_hole(self):
        layer = self.iface.activeLayer()
        if not layer or layer not in self.scoped_layers() or layer.customProperty('collar/category') not in ['holes','operational']:
            self.error('Select a hole in a connected operational layer')
            return
        selected = layer.selectedFeatures()
        if len(selected) != 1 or not str(selected[0]['client_key']).startswith('hole:'):
            self.error('Select exactly one drillhole point')
            return
        QDesktopServices.openUrl(QUrl(ORIGIN + '/holes/' + quote(str(selected[0]['id']), safe='')))

    def propose_move(self):
        if self.busy:
            return
        if self.move_review:
            self.move_review.show()
            self.move_review.raise_()
            return
        layer = self.iface.activeLayer()
        if layer not in self.scoped_layers() or layer.customProperty('collar/category') not in ['holes','operational']:
            self.error('Select a drillhole in a connected operational layer')
            return
        selected = layer.selectedFeatures()
        if len(selected) != 1 or not str(selected[0]['client_key']).startswith('hole:'):
            self.error('Select exactly one drillhole point using QGIS Select Features, then choose Propose hole move.')
            return
        feature = selected[0]
        if not feature['qgis_revision']:
            self.error('Refresh the drillhole layer first')
            return
        path = self.prefix() + '/holes/' + quote(str(feature['id']), safe='') + '/move'
        try:
            review = MoveReview(self.iface.mainWindow(), self.iface.mapCanvas(), layer, feature)
        except Exception:
            self.error('The selected hole could not be displayed. Refresh the layer and select a drillhole point.')
            return
        self.move_review = review
        self.set_busy(False)
        def closed(_result):
            if self.move_review is review:
                self.move_review = None
                if not self.closed:
                    self.set_busy(self.busy)
                    if _result != QDialog.DialogCode.Accepted:
                        self.status.setText('Hole move cancelled. The original location is unchanged.')
            review.deleteLater()
        def submit(payload):
            if self.busy or self.move_review is not review:
                return
            self.set_busy(True)
            def submitted(result):
                if self.move_review is review:
                    review.accept()
                self.set_busy(False)
                self.notify('Location request ' + result['status'] + '. Review it in Collar; the approved collar stays unchanged until accepted.')
            self.call('POST', path, payload, submitted)
        review.finished.connect(closed)
        review.submitted.connect(submit)
        review.show()
        review.raise_()
        self.status.setText('Use the Review proposed hole move window to choose, review and submit a new position.')

    def signout(self):
        if self.busy:
            return
        if self.move_review:
            self.move_review.dispose()
        self.set_busy(True)
        had_session = bool(self.store.auth_id)
        token = self.store.read()
        self.store.clear()
        self.identity = None
        self.login.stop()
        self.update_connection("disconnected")
        self.generation += 1
        def finished(_result, error):
            if self.closed:
                return
            self.organisations.blockSignals(True)
            self.projects.blockSignals(True)
            self.organisations.clear()
            self.projects.clear()
            self.organisations.blockSignals(False)
            self.projects.blockSignals(False)
            self.layer_list.clear()
            for layer in connected_layers():
                layer.setReadOnly(True)
            self.set_busy(False)
            if error:
                self.error('Signed out locally. Remote revocation failed; revoke the QGIS session in Collar Account → Sessions.')
            else:
                self.notify('Signed out. Local working copies remain on this computer.')
        if token:
            request('POST', '/api/auth/sign-out', token, None, {}, finished)
        else:
            finished(None, 'Session unavailable' if had_session else None)

    def unload(self):
        self.closed = True
        QgsProject.instance().readProject.disconnect(restore_esri_basemaps)
        QgsProject.instance().layersAdded.disconnect(restore_esri_basemaps)
        stop_imagery()
        if self.move_review:
            self.move_review.dispose()
        self.generation += 1
        for task in self.tasks:
            try:
                task.cancel()
            except RuntimeError:
                pass
        if self.settings_dialog:
            self.settings_dialog.close()
            self.settings_dialog.deleteLater()
        if self.dock:
            self.login.stop()
            self.timer.stop()
            self.count_timer.stop()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
        self.iface.removePluginMenu('Collar', self.action)
        self.iface.removeToolBarIcon(self.action)
        self.iface.removeCustomActionForLayerType(self.publish_action)
