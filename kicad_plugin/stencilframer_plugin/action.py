import shutil
import threading

import pcbnew
import wx

from . import core


class StencilframerAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'Stencilframer'
        self.category = 'Fabrication'
        self.description = 'Generate a stencil frame from a KiCad PCB and stencil Gerber'
        self.show_toolbar_button = True

    def Run(self):
        board = pcbnew.GetBoard()
        board_path = board.GetFileName() if board is not None else ''
        dialog = StencilframerDialog(None, board_path)
        dialog.ShowModal()
        dialog.Destroy()


class StencilframerDialog(wx.Dialog):
    def __init__(self, parent, board_path):
        wx.Dialog.__init__(self, parent, title='Create Stencil Frame', size=(760, 520))
        self.board_path = board_path
        self.temp_dir = None
        self.output_path = core.default_output_path(board_path)
        self.pcb_thickness = core.detect_pcb_thickness(board_path)
        self.preferences = core.load_preferences()
        self.discovered_openscad_path = core.find_openscad() or ''
        self.openscad_custom = bool(self.preferences.get('openscad_custom'))
        saved_openscad_path = self.preferences.get('openscad_path') or ''
        self.openscad_path = saved_openscad_path if saved_openscad_path and (self.openscad_custom or not self.discovered_openscad_path) else self.discovered_openscad_path
        self.process_running = False

        self._build_ui()
        self._set_idle_state()

    def _build_ui(self):
        panel = wx.Panel(self)
        self.panel = panel
        root = wx.BoxSizer(wx.VERTICAL)

        if not self.board_path:
            board_text = wx.StaticText(panel, label='Save the PCB before creating a stencil frame.')
            root.Add(board_text, 0, wx.ALL | wx.EXPAND, 10)

        stencil_label = wx.StaticText(panel, label='Stencil Gerber (gbr, zip)')
        root.Add(stencil_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.stencil_picker = wx.FilePickerCtrl(
                panel,
                message='Select stencil Gerber or zip',
                wildcard='Gerber or zip (*.gbr;*.ger;*.gtp;*.gbp;*.gts;*.gbs;*.zip)|*.gbr;*.ger;*.gtp;*.gbp;*.gts;*.gbs;*.zip|All files (*.*)|*.*',
                style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        root.Add(self.stencil_picker, 0, wx.ALL | wx.EXPAND, 10)

        output_label = wx.StaticText(panel, label='Output STL')
        root.Add(output_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.output_picker = wx.FilePickerCtrl(
                panel,
                path=self.output_path,
                message='Choose output STL',
                wildcard='STL files (*.stl)|*.stl|All files (*.*)|*.*',
                style=wx.FLP_SAVE | wx.FLP_OVERWRITE_PROMPT | wx.FLP_USE_TEXTCTRL)
        root.Add(self.output_picker, 0, wx.ALL | wx.EXPAND, 10)

        options = wx.FlexGridSizer(3, 4, 8, 8)
        options.AddGrowableCol(1)
        options.AddGrowableCol(3)

        options.Add(wx.StaticText(panel, label='PCB offset (mm)'), 0, wx.ALIGN_CENTER_VERTICAL)
        self.offset_input = wx.TextCtrl(panel, value=str(self.preferences.get('offset') or core.PREFERENCE_DEFAULTS['offset']))
        options.Add(self.offset_input, 1, wx.EXPAND)

        options.Add(wx.StaticText(panel, label='Stencil offset (mm)'), 0, wx.ALIGN_CENTER_VERTICAL)
        self.stencil_offset_input = wx.TextCtrl(panel, value=str(self.preferences.get('stencil_offset') or core.PREFERENCE_DEFAULTS['stencil_offset']))
        options.Add(self.stencil_offset_input, 1, wx.EXPAND)

        options.Add(wx.StaticText(panel, label='Side'), 0, wx.ALIGN_CENTER_VERTICAL)
        self.side_choice = wx.Choice(panel, choices=['Front', 'Back'])
        self.side_choice.SetStringSelection(self.preference_choice(self.preferences.get('side'), ('front', 'back'), 'Front'))
        options.Add(self.side_choice, 1, wx.EXPAND)

        options.Add(wx.StaticText(panel, label='Lift hole'), 0, wx.ALIGN_CENTER_VERTICAL)
        self.lift_hole_choice = wx.Choice(panel, choices=['Auto', 'Left', 'Right', 'Top', 'Bottom', 'Top Left', 'Top Right', 'Bottom Left', 'Bottom Right'])
        self.lift_hole_choice.SetStringSelection(self.preference_choice(
            self.preferences.get('lift_hole_position'),
            ('auto', 'l', 'r', 't', 'b', 'tl', 'tr', 'bl', 'br'),
            'Auto'))
        options.Add(self.lift_hole_choice, 1, wx.EXPAND)

        options.Add(wx.StaticText(panel, label='PCB thickness (mm)'), 0, wx.ALIGN_CENTER_VERTICAL)
        self.pcb_thickness_input = wx.TextCtrl(panel, value=self.format_float(self.pcb_thickness), style=wx.TE_READONLY)
        options.Add(self.pcb_thickness_input, 1, wx.EXPAND)

        self.fill_voids_checkbox = wx.CheckBox(panel, label='Fill voids')
        self.fill_voids_checkbox.SetValue(bool(self.preferences.get('fill_voids')))
        options.Add(self.fill_voids_checkbox, 0, wx.ALIGN_CENTER_VERTICAL)

        min_void_box = wx.BoxSizer(wx.HORIZONTAL)
        min_void_box.Add(wx.StaticText(panel, label='Min area (mm^2)'), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8)
        self.min_void_area_input = wx.TextCtrl(panel, value=str(self.preferences.get('min_void_area') or core.PREFERENCE_DEFAULTS['min_void_area']))
        min_void_box.Add(self.min_void_area_input, 1, wx.EXPAND)
        options.Add(min_void_box, 1, wx.EXPAND)

        root.Add(options, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.min_void_area_input.Enable(self.fill_voids_checkbox.GetValue())

        openscad_label = wx.StaticText(panel, label='OpenSCAD executable')
        root.Add(openscad_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.openscad_picker = wx.FilePickerCtrl(
                panel,
                path=self.openscad_path,
                message='Select OpenSCAD executable',
                wildcard='All files (*.*)|*.*',
                style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        root.Add(self.openscad_picker, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.openscad_label = openscad_label
        if self.openscad_picker_hidden():
            openscad_label.Hide()
            self.openscad_picker.Hide()

        self.log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        root.Add(self.log, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.create_button = wx.Button(panel, label='Create')
        self.reveal_button = wx.Button(panel, label=core.reveal_label())
        buttons.AddStretchSpacer(1)
        buttons.Add(self.reveal_button, 0, wx.RIGHT, 8)
        buttons.Add(self.create_button, 0)
        root.Add(buttons, 0, wx.ALL | wx.EXPAND, 10)

        panel.SetSizer(root)

        self.create_button.Bind(wx.EVT_BUTTON, self.on_create)
        self.fill_voids_checkbox.Bind(wx.EVT_CHECKBOX, self.on_fill_voids_changed)
        self.reveal_button.Bind(wx.EVT_BUTTON, self.on_reveal)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def _set_idle_state(self):
        self.create_button.Enable(bool(self.board_path))
        self.create_button.SetLabel('Create')
        self.reveal_button.Hide()
        self._set_busy(False)
        self._refresh_layout()

    def append_log(self, text):
        self.log.AppendText(text)
        if not text.endswith('\n'):
            self.log.AppendText('\n')

    def append_script_output(self, output):
        if not output:
            return
        for line in output.splitlines():
            self.append_log(line)

    def format_float(self, value):
        return '{:g}'.format(value)

    def preference_choice(self, value, valid_values, fallback_label):
        if value in valid_values:
            return self.choice_label(value)
        return fallback_label

    def choice_label(self, value):
        labels = {
            'front': 'Front',
            'back': 'Back',
            'auto': 'Auto',
            'l': 'Left',
            'r': 'Right',
            't': 'Top',
            'b': 'Bottom',
            'tl': 'Top Left',
            'tr': 'Top Right',
            'bl': 'Bottom Left',
            'br': 'Bottom Right',
        }
        return labels[value]

    def side_value(self):
        return self.side_choice.GetStringSelection().lower()

    def lift_hole_value(self):
        values = {
            'Auto': 'auto',
            'Left': 'l',
            'Right': 'r',
            'Top': 't',
            'Bottom': 'b',
            'Top Left': 'tl',
            'Top Right': 'tr',
            'Bottom Left': 'bl',
            'Bottom Right': 'br',
        }
        return values[self.lift_hole_choice.GetStringSelection()]

    def openscad_picker_hidden(self):
        return bool(self.discovered_openscad_path) and not self.openscad_custom

    def current_openscad_path(self):
        if not self.openscad_picker.IsShown():
            return self.discovered_openscad_path

        selected = self.openscad_picker.GetPath().strip()
        if selected:
            return selected
        return self.discovered_openscad_path

    def current_openscad_custom(self):
        return self.openscad_picker.IsShown() and bool(self.openscad_picker.GetPath().strip())

    def _set_busy(self, is_busy):
        if is_busy:
            if not wx.IsBusy():
                wx.BeginBusyCursor()
        elif wx.IsBusy():
            wx.EndBusyCursor()

    def _set_running_state(self):
        self.process_running = True
        self.create_button.Disable()
        self.create_button.SetLabel('Creating...')
        self.reveal_button.Hide()
        self._set_busy(True)
        self._refresh_layout()

    def _set_finished_state(self, show_reveal):
        self.process_running = False
        self.create_button.Enable(bool(self.board_path))
        self.create_button.SetLabel('Create')
        if show_reveal:
            self.reveal_button.SetLabel(core.reveal_label())
            self.reveal_button.Show()
        else:
            self.reveal_button.Hide()
        self._set_busy(False)
        self._refresh_layout()

    def _refresh_layout(self):
        self.panel.Layout()
        self.Layout()

    def on_fill_voids_changed(self, _event):
        self.min_void_area_input.Enable(self.fill_voids_checkbox.GetValue())

    def parse_float_input(self, ctrl, label):
        value = ctrl.GetValue().strip()
        try:
            return float(value)
        except ValueError:
            raise ValueError('{} must be a number'.format(label))

    def on_create(self, _event):
        if self.process_running:
            return

        stencil_input = self.stencil_picker.GetPath()
        output_path = self.output_picker.GetPath()
        if not output_path:
            output_path = self.output_path
        openscad_path = self.current_openscad_path()
        if not openscad_path:
            self.log.Clear()
            self.append_log('[ERROR] Select the OpenSCAD executable')
            return
        try:
            offset = self.parse_float_input(self.offset_input, 'PCB offset')
            stencil_offset = self.parse_float_input(self.stencil_offset_input, 'Stencil offset')
            fill_voids = self.fill_voids_checkbox.GetValue()
            min_void_area = self.parse_float_input(self.min_void_area_input, 'Minimum void area') if fill_voids else None
            side = self.side_value()
            lift_hole_position = self.lift_hole_value()
        except ValueError as exc:
            self.log.Clear()
            self.append_log('[ERROR] {}'.format(exc))
            return

        self.log.Clear()
        self.save_current_preferences(openscad_path, fill_voids, side, lift_hole_position)
        self._set_running_state()

        thread = threading.Thread(
                target=self._run_generator,
                args=(stencil_input, output_path, openscad_path, offset, stencil_offset, fill_voids, min_void_area, side, lift_hole_position))
        thread.daemon = True
        thread.start()

    def save_current_preferences(self, openscad_path, fill_voids, side, lift_hole_position):
        prefs = {
            'offset': self.offset_input.GetValue().strip(),
            'stencil_offset': self.stencil_offset_input.GetValue().strip(),
            'fill_voids': fill_voids,
            'min_void_area': self.min_void_area_input.GetValue().strip(),
            'side': side,
            'lift_hole_position': lift_hole_position,
            'openscad_path': openscad_path,
            'openscad_custom': self.current_openscad_custom(),
        }
        try:
            core.save_preferences(prefs)
        except Exception as exc:
            self.append_log('[WARN] Could not save preferences: {}'.format(exc))

    def _run_generator(self, stencil_input, output_path, openscad_path, offset, stencil_offset, fill_voids, min_void_area, side, lift_hole_position):
        try:
            if self.temp_dir:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                self.temp_dir = None
            stencil_path, temp_dir = core.resolve_stencil_input(stencil_input)
            self.temp_dir = temp_dir

            wx.CallAfter(self.append_log, 'Creating stencil frame...')
            wx.CallAfter(self.append_log, 'Stencil: {}'.format(stencil_path))
            wx.CallAfter(self.append_log, 'Output: {}'.format(output_path))
            wx.CallAfter(self.append_log, 'OpenSCAD: {}'.format(openscad_path))
            wx.CallAfter(self.append_log, 'Side: {}'.format(self.choice_label(side)))
            wx.CallAfter(self.append_log, 'Lift hole: {}'.format(self.choice_label(lift_hole_position)))
            wx.CallAfter(self.append_log, 'PCB thickness: {} mm'.format(self.format_float(self.pcb_thickness)))
            wx.CallAfter(self.append_log, 'PCB offset: {} mm'.format(offset))
            wx.CallAfter(self.append_log, 'Stencil offset: {} mm'.format(stencil_offset))
            if fill_voids:
                wx.CallAfter(self.append_log, 'Fill voids: >= {} mm^2'.format(min_void_area))

            returncode, output = core.run_stencilframer(
                    self.board_path,
                    stencil_path,
                    output_path,
                    openscad_path=openscad_path,
                    offset=offset,
                    stencil_offset=stencil_offset,
                    mirror=(side == 'back'),
                    lift_hole_position=lift_hole_position,
                    pcb_thickness=self.pcb_thickness,
                    fill_voids=fill_voids,
                    min_void_area=min_void_area)
            if returncode!=0:
                wx.CallAfter(self._show_script_failure, returncode, output)
                return

            wx.CallAfter(self.append_script_output, output)
            wx.CallAfter(self._show_success, output_path)
        except Exception as exc:
            wx.CallAfter(self._show_error, str(exc))

    def _show_success(self, output_path):
        self.output_path = output_path
        self.append_log('Wrote {}'.format(output_path))
        self._set_finished_state(show_reveal=True)

    def _show_error(self, message):
        self.append_log('[ERROR] {}'.format(message))
        self._set_finished_state(show_reveal=False)

    def _show_script_failure(self, returncode, output):
        self.append_script_output(output)
        self.append_log('[ERROR] stencilframer.py exited with status {}'.format(returncode))
        self._set_finished_state(show_reveal=False)

    def on_reveal(self, _event):
        if not self.output_path:
            return
        core.reveal_output(self.output_path)

    def on_close(self, event):
        if self.process_running:
            event.Veto()
            return
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None
        self.EndModal(wx.ID_CLOSE)
