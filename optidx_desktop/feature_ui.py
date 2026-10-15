"""Native controls for shaders, addons, versions and Linux launch profiles."""
import json
from pathlib import Path
import shlex

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QPlainTextEdit, QScrollArea, QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from . import assets
from .catalog import catalogs, addon_catalog, EXTRAS, DLSS_FILES, STREAMLINE_FILES, game_data
from .features import dll_locations
from .launch import DRS_CHOICES, hdr_outputs, wrapper_options, vkbasalt_available
from .storage import read_json, atomic_json


def push(label, fn):
    button = QPushButton(label)
    button.clicked.connect(fn)
    return button


def help_label(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName('muted')
    return label


def section(parent, title, expanded=True):
    """Give advanced actions their own explicitly expanded scope."""
    box = QWidget()
    outer = QVBoxLayout(box)
    outer.setContentsMargins(0, 4, 0, 4)
    toggle = QToolButton()
    toggle.setText(title)
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toggle.setCheckable(True)
    toggle.setChecked(expanded)
    body = QWidget()
    inner = QVBoxLayout(body)
    inner.setContentsMargins(12, 6, 0, 6)
    from .motion import SectionMotion
    body.motion = SectionMotion(body, toggle)
    toggle.toggled.connect(body.motion.change)
    body.motion.change(expanded)
    outer.addWidget(toggle)
    outer.addWidget(body)
    parent.addWidget(box)
    return inner


class Features:
    def __init__(self, window):
        self.window = window
        self.repository = window.repository
        self.fields = {}
        self.drs = {}
        self.shader_checks = {}
        self.build_assets()
        self.build_versions()
        self.build_extras()
        self.build_launch()
        self.build_library_settings()

    def page(self, name):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(widget)
        self.window.tabs.addTab(area, name)
        return layout

    def combo(self, form, key, label, values):
        widget = QComboBox()
        for text, value in values:
            widget.addItem(text, value)
        self.fields[key] = widget
        form.addRow(label, widget)
        return widget

    def line(self, form, key, label, placeholder=''):
        widget = QLineEdit()
        widget.setPlaceholderText(placeholder)
        self.fields[key] = widget
        form.addRow(label, widget)
        return widget

    def file_line(self, form, key, label, pattern):
        widget=QWidget();row=QHBoxLayout(widget);row.setContentsMargins(0,0,0,0)
        field=QLineEdit();self.fields[key]=field;row.addWidget(field)
        def choose():
            path,_=QFileDialog.getOpenFileName(self.window,label,field.text() or str(Path.home()),pattern)
            if path:field.setText(path)
        row.addWidget(push('Browse',choose));form.addRow(label,widget)
        return field

    def check(self, form, key, label):
        widget = QCheckBox(label)
        self.fields[key] = widget
        form.addRow(widget)
        return widget

    def build_assets(self):
        layout = self.page('ReShade content')
        layout.addWidget(help_label('Add effects and addons to an existing ReShade installation. Each action below installs only the named content.'))
        tabs = QTabWidget()
        layout.addWidget(tabs)
        def tab(name):
            page = QWidget(); box = QVBoxLayout(page)
            area = QScrollArea(); area.setWidgetResizable(True); area.setWidget(page)
            tabs.addTab(area, name)
            return box
        shaders = tab('Shader packs')
        self.shader_list = QListWidget()
        self.shader_list.setMinimumHeight(220)
        shaders.addWidget(self.shader_list)
        row = QHBoxLayout()
        row.addWidget(push('Install checked shader packs', self.install_shaders))
        row.addWidget(push('Choose effects from a pack', self.choose_effects))
        shaders.addLayout(row)
        advanced = section(shaders, 'Remove packs / export a bundle', expanded=False)
        advanced.addWidget(push('Remove unchecked managed shader packs', self.prune_shaders))
        advanced.addWidget(push('Export shader/preset bundle', self.export_bundle))
        imports = tab('Addons & presets')
        imports.addWidget(QLabel('Download an addon from the catalog'))
        self.addon_catalog = QComboBox(); imports.addWidget(self.addon_catalog)
        imports.addWidget(push('Install this catalog addon', lambda: self.job('deploy_catalog_addon', {'id': self.addon_catalog.currentData()})))
        imports.addWidget(QLabel('Install a file from your import library'))
        self.asset_library = QComboBox(); imports.addWidget(self.asset_library)
        imports.addWidget(push('Install this imported item', lambda: self.job('deploy_asset', {'id': self.asset_library.currentData()})))
        library = section(imports, 'Add files to the import library', expanded=False)
        library.addWidget(help_label('Importing stores a copy in the app library. Use Install this imported item to copy it into this game.'))
        library.addWidget(push('Import addon / preset / shader file', self.import_dialog))
        library.addWidget(push('Import from HTTPS URL', self.import_url_dialog))
        imports.addStretch()
        display = tab('ReShade settings')
        display.addWidget(help_label('These controls edit ReShade.ini or the selected preset. They do not install ReShade or any shader pack.'))
        form = QFormLayout()
        self.line(form, 'screenshot_path', 'Screenshot folder')
        self.line(form, 'reshade_hotkey', 'Overlay hotkey', 'e.g. 36,0,0,0 (Home)')
        self.line(form, 'peak_nits', 'Preset peak brightness (nits)', 'Optional; 80–10000')
        display.addLayout(form)
        display.addWidget(push('Apply ReShade configuration', lambda: self.job('apply_display')))
        display.addStretch()
        managed = self.page('Installed tools')
        managed.addWidget(help_label('Optional tools, shader packs and DLL replacements already managed in this game. Removing a group restores its original files. Core components are removed from Installation.'))
        self.managed = QListWidget(); self.managed.setMinimumHeight(160)
        managed.addWidget(self.managed)
        row = QHBoxLayout()
        row.addWidget(push('Enable selected addon', lambda: self.toggle(True)))
        row.addWidget(push('Disable selected addon', lambda: self.toggle(False)))
        row.addWidget(push('Remove selected group / restore originals', self.remove_group))
        managed.addLayout(row)
        managed.addStretch()

    def build_versions(self):
        layout = self.page('Game DLLs')
        self.versions_layout = layout
        layout.addWidget(help_label('Swap DLSS SR, RR, FG, neural rendering or Streamline. Select the actual DLL folder: Unreal games often keep these under Engine/Plugins. Original files are retained and can be restored.'))
        self.dll_paths = QPlainTextEdit()
        self.dll_paths.setReadOnly(True)
        self.dll_paths.setMaximumHeight(120)
        layout.addWidget(self.dll_paths)
        form = QFormLayout()
        self.dll_kind = QComboBox()
        for label, key in [('DLSS Super Resolution', 'dlss'), ('DLSS Ray Reconstruction', 'dlssd'),
                           ('DLSS Frame Generation', 'dlssg'), ('DLSS Neural Rendering', 'dlssnr'), ('Streamline', 'streamline')]:
            self.dll_kind.addItem(label, key)
        self.dll_version = QComboBox()
        self.dll_version.setEditable(True)
        self.dll_kind.currentIndexChanged.connect(self.version_choices)
        self.dll_folder = QLineEdit()
        self.dll_folder.setPlaceholderText('Relative to the game root; empty = selected executable folder')
        form.addRow('Component', self.dll_kind)
        form.addRow('Version', self.dll_version)
        folder=QWidget();folder_row=QHBoxLayout(folder);folder_row.setContentsMargins(0,0,0,0);folder_row.addWidget(self.dll_folder)
        folder_row.addWidget(push('Browse',self.choose_dll_folder))
        form.addRow('DLL folder', folder)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(push('Replace selected DLL with this version', self.swap))
        row.addWidget(push('Replace selected DLL from a local file', self.custom_dll))
        layout.addLayout(row)
        update_form = QFormLayout()
        self.check(update_form, 'auto_update_dlss', 'Use Latest for managed DLSS/Streamline during updates')
        layout.addLayout(update_form)
        layout.addWidget(help_label('Restore original DLLs from Installed tools. Replacing a DLL does not add DLSS GPU support.'))
        layout = section(layout, 'Neural Rendering Cost Scaler', expanded=False)
        layout.addWidget(help_label('Installs a proxy beside the selected Neural Rendering DLL. This is separate from replacing a DLSS version.'))
        form = QFormLayout()
        self.line(form, 'nr_cost_scale', 'NR Cost Scaler resolution scale', 'Default 0.75; 0.25–2.0')
        layout.addLayout(form)
        layout.addWidget(push('Enable NR Cost Scaler in selected DLL folder', lambda:self.job('nr_cost_scaler',{'target_dir':self.dll_folder.text().strip()})))
        layout.addWidget(push('Remove NR Cost Scaler / keep real NR DLL', lambda:self.job('nr_cost_scaler',{'target_dir':self.dll_folder.text().strip(),'enabled':False})))
        layout = section(self.versions_layout, 'Shared DLL defaults and batch replacement', expanded=False)
        layout.addWidget(push('Replace this DLL in selected games…', self.batch_dll))
        layout.addWidget(push('Save these DLL choices as global defaults', self.save_dll_defaults))
        layout.addWidget(push('Load global DLL defaults', self.load_dll_defaults))
        layout.addStretch()

    def build_extras(self):
        self.remove_helix_button = push('Remove HelixSR / restore direct FSR4', self.remove_helixsr)
        self.window.maintenance_box.insertWidget(0, self.remove_helix_button)
        helix_hint = help_label('This removes only managed HelixSR files, reconnects the existing lossy FSR DLL directly, and unchecks HelixSR for future updates. Simply unchecking a component leaves its files installed.')
        self.window.maintenance_box.insertWidget(1, helix_hint)
        layout = section(self.window.installation_box, 'Component download sources and advanced detection', expanded=False)
        layout.addWidget(help_label('Choose download sources for checked OptiScaler and ReShade components. Installation uses these choices; this section has no separate installer.'))
        form = QFormLayout()
        self.combo(form, 'reshade_channel', 'ReShade channel', [(x.replace('_', ' ').title(), x) for x in ['stable', 'nightly', 'custom', 'legacy', 'no_addons']])
        self.line(form, 'reshade_version', 'Pinned ReShade version', 'Used by Legacy')
        self.file_line(form, 'reshade_custom', 'Custom ReShade DLL / archive', 'Packages (*.dll *.exe *.zip *.7z)')
        self.combo(form, 'optiscaler_channel', 'OptiScaler channel', [('Backend default', ''), ('Stable', 'stable'), ('Nightly', 'nightly'), ('Custom archive', 'custom')])
        self.line(form, 'optiscaler_tag', 'Pinned OptiScaler tag', 'Optional')
        self.line(form, 'optiscaler_repo', 'OptiScaler GitHub repository', 'Optional owner/repository override')
        self.file_line(form, 'optiscaler_custom', 'Custom OptiScaler archive', 'Archives (*.7z *.zip)')
        layout.addLayout(form)
        compatibility = section(self.window.configuration_box, 'Advanced: game compatibility / existing file handling', expanded=False)
        compatibility.addWidget(help_label('Per-game overrides used by component and optional-tool installers. Auto detect is recommended. Allow replacing files affects all installs in this game.'))
        form = QFormLayout()
        self.combo(form, 'api_override', 'Graphics API', [('Auto detect', '')] + [(x,x) for x in ['DX9', 'DX10', 'DX11', 'DX12', 'OpenGL', 'Vulkan']])
        self.combo(form, 'bits_override', 'Architecture', [('Auto detect', ''), ('32-bit', '32'), ('64-bit', '64')])
        self.combo(form, 'proxy_override', 'Injection filename', [('Automatic', '')] + [(x,x) for x in ['dxgi.dll','d3d9.dll','opengl32.dll','winmm.dll','version.dll','winhttp.dll']])
        self.check(form, 'allow_foreign', 'Allow replacing existing foreign files (originals are backed up)')
        self.line(form, 'wiki_name', 'RenoDX wiki matching name')
        self.check(form, 'force_ue_extended', 'Prefer generic UE-Extended over the named RenoDX mod')
        compatibility.addLayout(form)
        config = section(self.window.configuration_box, 'Advanced: edit INI / apply an OptiScaler configuration preset', expanded=False)
        config.addWidget(push('Edit an installed component INI', self.config_editor))
        from .templates import TEMPLATES
        self.gpu_template=QComboBox()
        labels = {'nvidia': 'NVIDIA GPU', 'amd-dlss': 'AMD GPU · RHI DLSS preset', 'amd-nodlss': 'AMD GPU · RHI non-DLSS preset'}
        for key in TEMPLATES:
            gpu, channel = key.rsplit('-', 1)
            self.gpu_template.addItem(labels[gpu] + ' · ' + channel.title() + ' configuration', key)
        config.addWidget(help_label('Optional RHI OptiScaler.ini presets. GPU/DLSS names are RHI’s preset labels. Stable/Nightly identifies the configuration variant. Preview the INI before applying it. This does not download a DLSS DLL or change the selected component release. Applying a preset changes OptiScaler settings while preserving library paths and explicit frame-generation choices.'))
        config.addWidget(self.gpu_template)
        config.addWidget(push('Download / open this editable INI preset', self.open_template))
        config.addWidget(push('Apply this preset to OptiScaler.ini', lambda:self.job('apply_template',{'id':self.gpu_template.currentData()})))
        layout = self.page('Optional tools')
        tools = layout
        layout.addWidget(help_label('Each tool has its own install button. Checking components on Installation does not install these tools.'))
        self.extra_sources = {}
        for key, item in EXTRAS.items():
            row = QHBoxLayout()
            row.addWidget(QLabel(item['label']), 1)
            row.addWidget(push('Install ' + item['label'], lambda checked=False, k=key: self.install_extra(k)))
            row.addWidget(push('Choose custom package', lambda checked=False, k=key: self.custom_extra(k)))
            row.addWidget(push('Remove', lambda checked=False, k=key: self.job('remove_asset', {'group': 'extra:' + k})))
            layout.addLayout(row)
        layout = section(layout, 'Advanced package selection', expanded=False)
        form = QFormLayout()
        self.line(form, 'ue_version', 'UE version override', 'e.g. 5.4; used for DOF eligibility')
        self.line(form, 'reframework_asset', 'RE Framework archive name', 'Choose the build for your game, e.g. DD2.zip')
        self.line(form, 'extra_asset_pattern', 'Extra release asset filter', 'Optional exact filename / regular expression')
        update_form = QFormLayout()
        self.line(update_form, 'exclude_components_text', 'Update exclusions', 'Comma-separated group/component IDs')
        self.window.maintenance_box.addLayout(update_form)
        layout.addLayout(form)
        layout = section(tools, 'Custom DXVK installation', expanded=False)
        layout.addWidget(push('Install DXVK translation DLLs', lambda: self.job('install_dxvk')))
        layout.addWidget(help_label('Proton already provides DXVK; custom local DXVK is optional and requires native DLL overrides in the launch profile. Frame limiters are mutually exclusive.'))
        layout = section(tools, 'Neural rendering pipelines', expanded=False)
        neural_form=QFormLayout()
        self.file_line(neural_form,'neural_consumer','Custom neural consumer addon','Addons (*.addon64)')
        layout.addLayout(neural_form)
        self.neural_method = QComboBox()
        self.neural_method.addItems(['DLSS5 Feeder', 'ShortFuse DLSS tool', 'DX11 neural rendering bridge'])
        layout.addWidget(self.neural_method)
        layout.addWidget(push('Install selected neural rendering pipeline', self.automatic_neural))
        layout.addWidget(push('Install selected pipeline from a local package', self.import_pipeline))
        layout.addWidget(help_label('Automatic setup downloads the selected pipeline and its dependencies. A custom consumer addon is optional. Only one neural pipeline can be active at a time.'))
        packages = section(tools, 'Prepared RTX 40 MFG package', expanded=False)
        packages.addWidget(push('Install RTX 40 MFG unlock from a local package…', self.import_other_pipeline))
        tools.addStretch()

    def build_launch(self):
        layout = self.page('Launch options')
        self.launch_layout = layout
        layout.addWidget(help_label('For Steam, copy the launch command below into the game’s Launch Options. These settings then apply when you press Play. Launch game opens Steam/Heroic with their existing settings; manual Wine/Proton launches use this profile directly.'))
        form = QFormLayout()
        form.addRow('Wine / Proton prefix', self.window.path_field(self.window.prefix))
        self.combo(form, 'runner_kind', 'Manual runner type', [(x,x) for x in ['wine','proton','umu','bottles']])
        self.file_line(form, 'runner_command', 'Runner command', 'All files (*)')
        self.line(form, 'launch_arguments', 'Game launch arguments')
        self.file_line(form, 'launch_executable', 'Launch executable override', 'Windows executables (*.exe)')
        self.check(form, 'PROTON_ENABLE_WAYLAND', 'Request Proton native Wayland')
        self.check(form, 'PROTON_ENABLE_HDR', 'Request Proton HDR')
        self.check(form, 'PROTON_ENABLE_NGX_UPDATER', 'Enable the Proton NGX snippet updater')
        self.check(form, 'DXVK_NVAPI_VKREFLEX', 'Enable installed DXVK-NVAPI Vulkan Reflex layer')
        self.check(form, 'dxvk_native_overrides', 'Prefer custom local DXVK DLLs')
        self.check(form, 'gamescope', 'Launch inside Gamescope')
        self.line(form, 'gamescope_arguments', 'Gamescope options', 'e.g. -f --hdr-enabled -r 120')
        self.check(form, 'vkbasalt', 'Enable installed vkBasalt Vulkan effects')
        self.line(form, 'vkbasalt_config', 'vkBasalt configuration file')
        self.check(form, 'auto_hdr', 'Enable HDR for the game and restore it on exit (KDE Plasma)')
        self.line(form, 'hdr_output', 'KDE display name', 'e.g. DP-1')
        layout.addLayout(form)
        layout.addWidget(push('Detect HDR displays', self.detect_hdr))
        layout.addWidget(push('Create vkBasalt shader configuration', self.vulkan_effects))
        layout = section(layout, 'Advanced: NVIDIA / DXVK driver overrides', expanded=False)
        layout.addWidget(help_label('Windows RTX HDR, Smooth Motion, driver ReBAR/power management and Windows global NVIDIA profiles have no implemented Linux equivalent. DLSS/MFG overrides below use DXVK-NVAPI; support depends on the installed runner and NVIDIA GPU.'))
        form = QFormLayout()
        for key, values in DRS_CHOICES.items():
            widget = QComboBox()
            widget.addItem('Keep current', '')
            for value in values:
                widget.addItem(str(int(value)+1) + 'x' if key.endswith(('MULTI_FRAME_COUNT', 'MULTI_FRAME_COUNT_MAX')) else value, value)
            self.drs[key] = widget
            form.addRow(key.removeprefix('NGX_').replace('_',' ').title(), widget)
        self.line(form, 'dlss_sr_scale', 'DLSS SR render scale (%)', '33–100; empty = unchanged')
        self.line(form, 'dlss_rr_scale', 'DLSS RR render scale (%)', '33–100; empty = unchanged')
        self.line(form, 'mfg_target', 'Dynamic MFG target FPS')
        self.combo(form, 'dxvk_vsync', 'DXVK VSync override', [('Keep current',''), ('Off','0'), ('On','1')])
        self.line(form, 'fps_limit', 'DXVK frame-rate limit', 'Optional positive FPS')
        self.combo(form, 'gl_vsync', 'NVIDIA OpenGL VSync', [('Keep current',''),('Off','0'),('On','1')])
        self.combo(form, 'gl_gsync', 'NVIDIA OpenGL G-Sync allowed', [('Keep current',''),('Off','0'),('On','1')])
        self.line(form, 'gl_shader_cache_mb', 'NVIDIA OpenGL shader cache (MiB)', 'Optional; affects OpenGL, not DXVK/VKD3D')
        layout.addLayout(form)
        self.environment = QPlainTextEdit()
        self.environment.setPlaceholderText('Additional per-game environment as JSON, e.g. {"DXVK_FRAME_RATE": "120"}')
        self.environment.setMaximumHeight(100)
        layout.addWidget(self.environment)
        self.launch_layout.addWidget(push('Copy Steam launch command for this profile', self.copy_wrapper))
        layout.addStretch()

    def build_library_settings(self):
        layout = self.page('Game profile')
        form = QFormLayout()
        self.check(form, 'favourite', 'Favourite this game')
        self.check(form, 'hidden', 'Hide this game from the normal library')
        self.line(form, 'display_name', 'Display name override')
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(push('Export game profile', self.export_profile))
        row.addWidget(push('Import game profile', self.import_profile))
        row.addWidget(push('Reset game overrides', self.reset_profile))
        layout.addLayout(row)
        layout.addWidget(push('Check updates for this game', lambda: self.job('check_updates')))
        layout = section(layout, 'Share this profile / apply settings to other games', expanded=False)
        layout.addWidget(push('Save as shared profile', self.save_named_profile))
        layout.addWidget(push('Apply shared profile to selected games', self.batch_profile))
        layout.addWidget(push('Batch apply HDR/FG/display settings', self.batch_settings))
        self.update_info = QPlainTextEdit()
        self.update_info.setReadOnly(True)
        self.update_info.setMaximumHeight(130)
        layout.addWidget(self.update_info)
        self.app_dialog = QDialog(self.window)
        self.app_dialog.setWindowTitle('OptiDX Desktop — app settings')
        self.app_dialog.resize(640, 440)
        layout = QVBoxLayout(self.app_dialog)
        layout.addWidget(help_label('Library-wide settings. These controls do not install files into any game.'))
        layout.addWidget(push('Refresh shader / addon / DLL catalogs', lambda: self.job('refresh_catalogs')))
        layout.addWidget(push('Check updates for all managed games', self.window.check_all_updates))
        self.app_background = QCheckBox('Check for updates every 4 hours while the app is running')
        self.reduce_motion = QCheckBox('Reduce motion (disable animations and accelerated smooth scrolling)')
        self.app_tray = QCheckBox('Keep the app in the system tray when closing')
        self.watch_downloads = QCheckBox('Watch a folder for newly downloaded addons and presets')
        self.watch_folder = QLineEdit()
        self.watch_folder.setPlaceholderText(str(Path.home() / 'Downloads'))
        settings = read_json(self.repository.directory / 'settings.json', {})
        self.theme_choice = QComboBox()
        self.theme_choice.setToolTip("Dark keeps the original navy/teal look. System uses the actual desktop Qt palette, including accent and selection colors.")
        for label, key in [('Dark', 'dark'), ('Light', 'light'), ('System', 'system')]:
            self.theme_choice.addItem(label, key)
        self.theme_choice.setCurrentIndex(max(0, self.theme_choice.findData(self.window.theme.mode)))
        theme_form = QFormLayout()
        theme_form.addRow('Appearance (applies immediately)', self.theme_choice)
        layout.addLayout(theme_form)
        self.theme_choice.currentIndexChanged.connect(self.change_theme)
        self.reduce_motion.setChecked(settings.get('reduce_motion', False))
        self.app_background.setChecked(settings.get('background_checks', False))
        self.app_tray.setChecked(settings.get('tray', False))
        self.watch_downloads.setChecked(settings.get('watch_downloads', False))
        self.watch_folder.setText(settings.get('watch_folder', str(Path.home() / 'Downloads')))
        for widget in [self.app_background, self.app_tray, self.watch_downloads, self.watch_folder, self.reduce_motion]:
            layout.addWidget(widget)
        layout.addWidget(push('Save app settings', self.save_app_settings))
        layout.addWidget(push('Open app data / backups', lambda: self.window.open_directory(self.repository.directory)))
        layout.addWidget(push('Open custom imports', lambda: self.window.open_directory(self.repository.directory / 'custom')))
        self.window.status_box.addWidget(push('PCGamingWiki search for this game', self.pcgw))
        self.window.status_box.addWidget(push('Show compatibility notes for this game', self.notes))
        layout.addWidget(help_label('Imports and background checks do not automatically modify game folders. Your install/update queue remains under your control.'))
        layout.addWidget(push('Close app settings', self.app_dialog.accept))
        layout.addStretch()

    def preferences(self):
        values = {}
        for key, widget in self.fields.items():
            values[key] = widget.isChecked() if isinstance(widget, QCheckBox) else widget.currentData() if isinstance(widget, QComboBox) else widget.text().strip()
        from .launch import environment_overrides
        values['environment'] = environment_overrides(json.loads(self.environment.toPlainText() or '{}'))
        values['drs'] = {k: w.currentData() for k,w in self.drs.items() if w.currentData()}
        values['shader_packs'] = [self.shader_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.shader_list.count()) if self.shader_list.item(i).checkState() == Qt.CheckState.Checked]
        values['exclude_components'] = [v.strip() for v in values.pop('exclude_components_text', '').split(',') if v.strip()]
        values['extra_sources'] = self.extra_sources
        values['dll_kind'] = self.dll_kind.currentData()
        values['dll_version'] = self.dll_version.currentText()
        values['dll_folder'] = self.dll_folder.text().strip()
        # Unchecked optional launch controls preserve the launcher's defaults.
        for key in ('PROTON_ENABLE_WAYLAND','PROTON_ENABLE_HDR','DXVK_NVAPI_VKREFLEX','PROTON_ENABLE_NGX_UPDATER'):
            if not values[key]:
                values[key] = None
        return values

    def load(self, profile):
        for key, widget in self.fields.items():
            value = profile.get(key, '')
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(widget.findData(value), 0))
            else:
                widget.setText(str(value))
        self.fields['exclude_components_text'].setText(','.join(profile.get('exclude_components', [])))
        self.environment.setPlainText(json.dumps(profile.get('environment', {}), indent=2))
        for key, widget in self.drs.items():
            widget.setCurrentIndex(max(widget.findData(profile.get('drs', {}).get(key,'')),0))
        self.extra_sources = profile.get('extra_sources', {}).copy()
        self.dll_kind.setCurrentIndex(max(self.dll_kind.findData(profile.get('dll_kind')), 0))
        self.version_choices()
        self.dll_version.setCurrentText(profile.get('dll_version', 'Latest'))
        self.dll_folder.setText(profile.get('dll_folder',''))
        self.load_shader_choices(profile.get('shader_packs', []))
        self.refresh()

    def load_shader_choices(self, selected):
        self.shader_list.clear()
        for key, pack in sorted(catalogs(self.repository).items(), key=lambda p:p[1]['label'].casefold()):
            item = QListWidgetItem(pack['label'])
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked)
            self.shader_list.addItem(item)

    def refresh(self):
        self.refresh_helix_action()
        self.addon_catalog.clear()
        for key,item in addon_catalog(self.repository).items():
            self.addon_catalog.addItem(item["label"],key)
        self.asset_library.clear()
        for key,item in read_json(self.repository.directory / 'assets.json',{}).items():
            self.asset_library.addItem(item['label'] + ' · ' + item['kind'], key)
        self.managed.clear()
        game = self.window.selected
        if game:
            scopes = {str(game.target): 'target', str(game.root): 'root'}
            for root, scope in scopes.items():
                for key, record in assets.state(root)['groups'].items():
                    item = QListWidgetItem(key + ' · ' + str(record['metadata'].get('version', 'Custom')))
                    item.setData(Qt.ItemDataRole.UserRole, {'group':key,'scope':scope})
                    self.managed.addItem(item)
            self.dll_paths.setPlainText('\n'.join(dll_locations(game)) or 'No existing DLSS/Streamline DLLs detected.')
            info = read_json(self.repository.directory / 'updates' / (game.id + '.json'),{})
            self.update_info.setPlainText(json.dumps(info,indent=2) if info else 'No update check recorded yet.')
        self.version_choices()

    def refresh_helix_action(self):
        game = self.window.selected
        managed = False
        if game:
            record = read_json(game.target / '.optidx-components.json', {})
            files = record.get('files', {}).get('helixsr', [])
            from .inspection import manifest_paths
            try:
                managed = bool(files) or any(path.casefold().startswith('optiscaler/helixsr/')
                                             for path in manifest_paths(game.target))
            except ValueError:
                managed = False
        self.remove_helix_button.setEnabled(managed and self.window.process is None)

    def remove_helixsr(self):
        game = self.window.selected
        if not game:
            return
        def finished(data):
            if self.window.selected and self.window.selected.id == game.id:
                self.window.components['helixsr'].setChecked(False)
        self.job('remove_helixsr', callback=finished)

    def job(self, action, options=None, callback=None):
        if callback is None and action == 'refresh_catalogs':
            def callback(data):
                selected = [self.shader_list.item(i).data(Qt.ItemDataRole.UserRole)
                            for i in range(self.shader_list.count())
                            if self.shader_list.item(i).checkState() == Qt.CheckState.Checked]
                self.load_shader_choices(selected)
                self.refresh()
        self.window.enqueue_feature(action, options or {}, callback)

    def import_dialog(self, path=''):
        if not path:
            path,_ = QFileDialog.getOpenFileName(self.window,'Import asset',str(Path.home()/'Downloads'), 'Mods/presets (*.addon *.addon32 *.addon64 *.ini *.fx *.zip *.7z *.rar)')
        if not path:
            return
        kind = 'preset' if Path(path).suffix.lower()=='.ini' else 'shader' if Path(path).suffix.lower()=='.fx' else 'addon'
        if Path(path).suffix.lower() in {'.zip','.7z','.rar'}:
            kind, ok = QInputDialog.getItem(self.window,'Package type','Contents',['addon','shader'],0,False)
            if not ok:return
        self.job('import_asset', {'path':path,'kind':kind}, lambda data:self.refresh())

    def import_url_dialog(self):
        url,ok=QInputDialog.getText(self.window,'Import URL','HTTPS URL to an addon, archive or preset')
        if ok and url.strip():
            kind,accepted=QInputDialog.getItem(self.window,'Asset type','Contents',['addon','preset','shader'],0,False)
            if accepted:self.job('import_url',{'url':url.strip(),'kind':kind},lambda data:self.refresh())

    def install_shaders(self):
        if not self.window.selected:return
        selected={self.shader_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.shader_list.count())
                  if self.shader_list.item(i).checkState()==Qt.CheckState.Checked}
        catalog=catalogs(self.repository)
        installed=set(assets.state(self.window.selected.target)['groups']) if self.window.selected else set()
        ordered=[];visiting=set()
        def visit(key):
            if key in ordered:return
            if key in visiting:raise ValueError('Shader dependency cycle: '+key)
            visiting.add(key)
            for dependency in catalog[key].get('requires',[]):
                if dependency in selected:visit(dependency)
                elif 'shader:'+dependency not in installed:raise ValueError('Select or install the required shader pack: '+dependency)
            visiting.remove(key);ordered.append(key)
        try:
            for key in sorted(selected):visit(key)
        except (KeyError,ValueError) as error:
            self.window.report_error(str(error));return
        for key in ordered:self.job('deploy_shader',{'id':key})

    def choose_effects(self):
        item = self.shader_list.currentItem()
        game = self.window.selected
        if not item or not game:return
        key = item.data(Qt.ItemDataRole.UserRole)
        from .models import Game
        game = Game.from_dict(game.to_dict())
        def finished(data):
            if self.window.selected and self.window.selected.id == game.id and self.window.selected.target == game.target:
                self.effect_picker(data, game)
            else:
                self.window.statusBar().showMessage('Effect selection cancelled because the selected game changed', 5000)
        self.job('shader_files', {'id':key}, finished)

    def effect_picker(self, data, game=None):
        game = game or self.window.selected
        dialog = QDialog(self.window)
        dialog.setWindowTitle('Choose effects · ' + data['id'])
        layout = QVBoxLayout(dialog)
        choices = QListWidget()
        for name in data['files']:
            item = QListWidgetItem(name)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            choices.addItem(item)
        layout.addWidget(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            selected=[choices.item(i).text() for i in range(choices.count()) if choices.item(i).checkState()==Qt.CheckState.Checked]
            self.window.enqueue_feature('deploy_shader', {'id':data['id'],'selected':selected}, game=game)

    def prune_shaders(self):
        if not self.window.selected:return
        selected={self.shader_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.shader_list.count())
                  if self.shader_list.item(i).checkState()==Qt.CheckState.Checked}
        for group in assets.state(self.window.selected.target)['groups']:
            if group.startswith('shader:') and group.split(':',1)[1] not in selected:
                self.job('remove_asset',{'group':group})

    def toggle(self, enabled):
        item=self.managed.currentItem()
        if item:self.job('toggle_asset',{**item.data(Qt.ItemDataRole.UserRole),'enabled':enabled})

    def remove_group(self):
        item=self.managed.currentItem()
        if item:self.job('remove_asset',item.data(Qt.ItemDataRole.UserRole))

    def version_choices(self):
        current=self.dll_version.currentText()
        self.dll_version.clear();self.dll_version.addItem('Latest')
        manifest=read_json(self.repository.directory/'dlss-manifest.json',{})
        self.dll_version.addItems([x['version'] for x in manifest.get(self.dll_kind.currentData(),[])])
        if current:self.dll_version.setCurrentText(current)

    def choose_dll_folder(self):
        if not self.window.selected:return
        root=Path(self.window.selected.root).resolve()
        folder=QFileDialog.getExistingDirectory(self.window,'Choose DLL folder',str(root))
        if folder:
            try:self.dll_folder.setText(str(Path(folder).resolve().relative_to(root)))
            except ValueError:self.window.report_error('Select a directory inside this game installation')

    def swap(self):
        self.job('swap_dll',{'kind':self.dll_kind.currentData(),'version':self.dll_version.currentText(),'target_dir':self.dll_folder.text().strip()})

    def custom_dll(self):
        path,_=QFileDialog.getOpenFileName(self.window,'Custom DLL or package',str(Path.home()),'DLLs/archives (*.dll *.zip *.7z)')
        if path:self.job('swap_dll',{'kind':self.dll_kind.currentData(),'path':path,'target_dir':self.dll_folder.text().strip()})

    def install_extra(self,key):
        source=self.extra_sources.get(key,{}).copy()
        if key=='reframework' and not source.get('path'):
            name=self.fields['reframework_asset'].text().strip()
            if not name:
                self.window.report_error('Choose the RE Framework archive name for this game first.');return
            import re
            source['pattern']='^'+re.escape(name)+'$'
        if self.fields['extra_asset_pattern'].text().strip():source['pattern']=self.fields['extra_asset_pattern'].text().strip()
        self.job('deploy_extra',{'id':key,'source':source})

    def custom_extra(self,key):
        path,_=QFileDialog.getOpenFileName(self.window,'Custom '+EXTRAS[key]['label'],str(Path.home()),'Packages (*.zip *.7z *.addon64 *.addon32 *.asi)')
        if path:
            self.extra_sources[key]={'path':path,'version':'Custom'}
            self.window.save_profile();self.install_extra(key)

    def automatic_neural(self):
        method=self.neural_method.currentText()
        if method not in {'ShortFuse DLSS tool','DX11 neural rendering bridge','DLSS5 Feeder'}:
            self.window.report_error('Automatic setup supports Feeder, ShortFuse and the DX11 bridge. Choose those methods or import a prepared package for the others.');return
        sources={'consumer':{'path':self.fields['neural_consumer'].text().strip()}} if self.fields['neural_consumer'].text().strip() else {}
        self.job('deploy_neural_tool',{'sources':sources,'method':{'ShortFuse DLSS tool':'shortfuse','DX11 neural rendering bridge':'bridge','DLSS5 Feeder':'feeder'}[method]})

    def import_other_pipeline(self):
        method = 'RTX 40 MFG unlock'
        path, _ = QFileDialog.getOpenFileName(self.window, 'Install ' + method, str(Path.home()), 'Packages (*.zip *.7z)')
        if path:
            self.job('deploy_pipeline', {'path': path, 'method': method})

    def import_pipeline(self):
        path,_=QFileDialog.getOpenFileName(self.window,'Import '+self.neural_method.currentText(),str(Path.home()),'Packages (*.zip *.7z)')
        if path:self.job('deploy_pipeline',{'path':path,'method':self.neural_method.currentText()})

    def vulkan_effects(self):
        game = self.window.selected
        if not game:return
        choices=['cas','dls','fxaa','smaa']+[str(p.relative_to(game.target)) for p in (game.target/'reshade-shaders/OptiDX').rglob('*.fx')]
        effect,ok=QInputDialog.getItem(self.window,'Vulkan effect','Select a builtin or an installed ReShade effect',choices,0,False)
        if ok:
            def finished(data):
                profile = self.repository.preferences(game)
                self.repository.save_preferences(game, {**profile, 'vkbasalt_config': data['path']})
                if self.window.selected and self.window.selected.id == game.id:
                    self.fields['vkbasalt_config'].setText(data['path'])
            self.job('create_vkbasalt_config',{'effects':[effect]},finished)

    def open_template(self):
        from .runtime import open_url
        from PySide6.QtCore import QUrl
        self.job('prepare_template',{'id':self.gpu_template.currentData()},lambda data:open_url(QUrl.fromLocalFile(data['path']).toString()))

    def config_editor(self):
        if not self.window.selected:return
        names=['ReShade.ini','OptiScaler.ini','relimiter.ini','DisplayCommander.ini','dxvk.conf','ReShadePreset.ini','nvngx_dlssnr.ini']
        name,ok=QInputDialog.getItem(self.window,'Edit configuration','File',names,0,False)
        if not ok:return
        path=self.window.selected.target/name
        current=path.read_bytes() if path.is_file() else b''
        from .backend import load_backend
        from .downloads import sha
        encoding=load_backend().hdr_ini_encoding(current)
        dialog=QDialog(self.window);dialog.setWindowTitle(name);dialog.resize(760,560)
        layout=QVBoxLayout(dialog);text=QPlainTextEdit();text.setPlainText(current.decode(encoding));layout.addWidget(text)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():self.job('edit_config',{'name':name,'text':text.toPlainText(),'before_sha256':sha(current)})

    def detect_hdr(self):
        try:
            outputs=hdr_outputs()
            self.window.report_error('\n'.join(o['name']+(' · HDR enabled' if o['enabled'] else ' · HDR disabled') for o in outputs) or 'Automatic display HDR switching is available through KDE Plasma/kscreen-doctor. No supported display adapter was detected.')
        except Exception as e:self.window.report_error(str(e))

    def copy_wrapper(self):
        if not self.window.selected:return
        if self.window.save_profile() is False:return
        from PySide6.QtWidgets import QApplication
        path=self.repository.directory/'profiles'/(self.window.selected.id+'.json')
        QApplication.clipboard().setText(wrapper_options(path))
        self.window.statusBar().showMessage('Managed launch options copied; paste them into Steam to apply the launch profile',7000)

    def change_theme(self, *args):
        mode = self.theme_choice.currentData()
        settings = read_json(self.repository.directory / 'settings.json', {})
        atomic_json(self.repository.directory / 'settings.json', {**settings, 'theme': mode})
        self.window.theme.set_mode(mode)

    def save_app_settings(self):
        atomic_json(self.repository.directory/'settings.json',{**read_json(self.repository.directory/'settings.json', {}), 'background_checks':self.app_background.isChecked(),'tray':self.app_tray.isChecked(),
                    'watch_downloads':self.watch_downloads.isChecked(),'watch_folder':self.watch_folder.text().strip(),
                    'reduce_motion': self.reduce_motion.isChecked()})
        self.window.configure_services()
        self.window.statusBar().showMessage('App settings saved',4000)

    def export_profile(self):
        if not self.window.selected:return
        try:
            profile = self.window.profile()
            path,_=QFileDialog.getSaveFileName(self.window,'Export profile',self.window.selected.title+'.json','Profiles (*.json)')
            if path:atomic_json(path,{'format':'optidx-profile-v1','preferences':profile})
        except (ValueError, TypeError, OSError) as error:
            self.window.report_error(str(error))

    def import_profile(self):
        path,_=QFileDialog.getOpenFileName(self.window,'Import profile',str(Path.home()),'Profiles (*.json)')
        if not path or not self.window.selected:return
        try:
            data=read_json(path,{})
            if data.get('format')!='optidx-profile-v1' or not isinstance(data.get('preferences'),dict):raise ValueError('Invalid OptiDX profile')
            from .backend import selected_components
            selected_components(data['preferences'])
            self.repository.save_preferences(self.window.selected,data['preferences']);self.window.load_profile()
        except Exception as e:self.window.report_error(str(e))

    def reset_profile(self):
        if self.window.selected:
            self.repository.save_preferences(self.window.selected,{});self.window.load_profile()

    def save_named_profile(self):
        try:
            profile = self.window.profile()
            name,ok=QInputDialog.getText(self.window,'Shared profile','Name')
            if ok and name.strip():
                data=read_json(self.repository.directory/'shared-profiles.json',{})
                data[name.strip()]=profile;atomic_json(self.repository.directory/'shared-profiles.json',data)
        except (ValueError, TypeError, OSError) as error:
            self.window.report_error(str(error))

    def games_picker(self):
        dialog=QDialog(self.window);dialog.setWindowTitle('Select games')
        layout=QVBoxLayout(dialog);choices=QListWidget()
        for game in self.window.games:
            if not game.available or not game.executable:continue
            item=QListWidgetItem(game.title);item.setData(Qt.ItemDataRole.UserRole,game.id)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Unchecked);choices.addItem(item)
        layout.addWidget(choices)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if not dialog.exec():return []
        selected={choices.item(i).data(Qt.ItemDataRole.UserRole) for i in range(choices.count()) if choices.item(i).checkState()==Qt.CheckState.Checked}
        return [g for g in self.window.games if g.id in selected]

    def batch_profile(self):
        profiles=read_json(self.repository.directory/'shared-profiles.json',{})
        name,ok=QInputDialog.getItem(self.window,'Shared profile','Choose profile',list(profiles),0,False)
        if ok and name in profiles:
            # Machine/game-specific paths and names never transfer between games.
            excluded={'prefix','config_dir','executable','launch_executable','display_name','hidden','favourite',
                      'runner_command','runner_kind','hdr_output','dll_folder','vkbasalt_config',
                      'reframework_asset','ue_version','wiki_name','launch_arguments','extra_sources',
                      'api_override','bits_override','proxy_override','environment'}
            common={k:v for k,v in profiles[name].items() if k not in excluded}
            for game in self.games_picker():
                old=self.repository.preferences(game);self.repository.save_preferences(game,{**old,**common})
            self.window.load_profile()

    def batch_settings(self):
        for game in self.games_picker():
            self.window.enqueue_feature('configure',game=game)
            self.window.enqueue_feature('apply_display',game=game)

    def batch_dll(self):
        options={'kind':self.dll_kind.currentData(),'version':self.dll_version.currentText(),'target_dir':self.dll_folder.text().strip()}
        for game in self.games_picker():self.window.enqueue_feature('swap_dll',options,game=game)

    def save_dll_defaults(self):
        atomic_json(self.repository.directory/'dll-defaults.json',{'kind':self.dll_kind.currentData(),'version':self.dll_version.currentText()})

    def load_dll_defaults(self):
        data=read_json(self.repository.directory/'dll-defaults.json',{})
        self.dll_kind.setCurrentIndex(max(self.dll_kind.findData(data.get('kind')),0));self.dll_version.setCurrentText(data.get('version','Latest'))

    def export_bundle(self):
        if not self.window.selected:return
        path,_=QFileDialog.getSaveFileName(self.window,'Export shader/preset bundle','optidx-shaders.zip','ZIP (*.zip)')
        if not path:return
        import zipfile
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            for group in assets.state(self.window.selected.target)['groups'].values():
                if group['metadata'].get('kind') in {'shader','preset'}:
                    for name in group['files']:
                        file=self.window.selected.target/name
                        if file.is_file():z.write(file,name)
            z.writestr('optidx-profile.json',json.dumps({'format':'optidx-profile-v1','preferences':self.window.profile()},indent=2))

    def pcgw(self):
        if self.window.selected:
            from urllib.parse import quote
            from .runtime import open_url
            open_url('https://www.pcgamingwiki.com/w/index.php?search='+quote(self.window.selected.title))

    def notes(self):
        if self.window.selected:
            self.window.report_error(json.dumps(game_data(self.repository,self.window.selected.title),indent=2))
