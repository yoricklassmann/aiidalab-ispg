"""Widgets for the QE app.

Authors:

    * Carl Simon Adorf <simon.adorf@epfl.ch>
"""

import base64
import hashlib
from queue import Queue
from tempfile import NamedTemporaryFile
from threading import Event, Lock, Thread

import ipywidgets as ipw
import traitlets
from aiida.orm import load_node, CalcJobNode
from aiidalab_widgets_base import register_viewer_widget
from IPython.display import HTML, Javascript, display

__all__ = [
    "CalcJobOutputFollower",
    "LogOutputWidget",
]


class RollingOutput(ipw.VBox):
    style = (
        "background-color: #253239; color: #cdd3df; line-height: normal; custom=test"
    )

    value = traitlets.Unicode()
    auto_scroll = traitlets.Bool()

    def __init__(self, num_min_lines=10, max_output_height="200px", **kwargs):
        self._num_min_lines = num_min_lines
        self._output = ipw.HTML(layout=ipw.Layout(min_width="50em"))
        self._refresh_output()
        super().__init__(
            [self._output],
            layout=ipw.Layout(max_height=max_output_height, min_width="51em"),
        )

    @traitlets.default("value")
    def _default_value(self):
        if self._num_min_lines > 0:
            return "\n" * self._num_min_lines

    @traitlets.default("auto_scroll")
    def _default_auto_scroll(self):
        return True

    def scroll_to_bottom(self):
        # Slight hack because it will scroll all widgets with the same class
        # name and max height to the bottom. That would primarily be an issue in
        # case that there are two LogOutputWidgets in the DOM. Could probably be
        # alleviated by adding a custom class.
        display(
            Javascript(
                """
            Array.from(document.getElementsByClassName('{class_name}'))
            .filter(el => el.style["max-height"] === "{max_height}")
            .forEach(el => el.scrollTop = el.scrollHeight)""".format(
                    class_name="p-Widget p-Panel jupyter-widgets widget-container widget-box widget-vbox",
                    max_height=self.layout.max_height,
                )
            )
        )

    @traitlets.observe("value")
    def _refresh_output(self, _=None):
        self._output.value = self._format_output(self.value)
        if self.auto_scroll:
            self.scroll_to_bottom()

    def _format_output(self, text):
        lines = text.splitlines()

        # Add empty lines to reach the minimum number of lines.
        lines += [""] * max(0, self._num_min_lines - len(lines))

        # Replace empty lines with single white space to ensure that they are
        # actually shown.
        lines = [line if len(line) > 0 else " " for line in lines]

        text = "\n".join(lines)
        return f"""<pre style="{self.style}">{text}</pre>"""


class DownloadButton(ipw.Button):
    # Adapted from https://stackoverflow.com/a/68683463
    """A Button widget for downloads with dynamic content."""

    filename = traitlets.Unicode()
    payload = traitlets.Bytes()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.on_click(self.__on_click)

    @traitlets.default("icon")
    def _default_icon(self):
        return "download"

    @traitlets.default("tooltip")
    def _default_tooltip(self):
        return "Download"

    def __on_click(self, _):
        # bypass browser cache
        digest = hashlib.md5(self.payload).hexdigest()  # noqa: S324
        payload = base64.b64encode(self.payload).decode()

        link_id = f"dl_{digest}"

        display(
            HTML(
                f"""
            <html>
            <body>
            <a id="{link_id}" download="{self.filename}" href="data:text/plain;base64,{payload}" download>
            </a>

            <script>
            (function download() {{
            document.getElementById('{link_id}').click();
            }})()
            </script>

            </body>
            </html>
            """
            )
        )


class FilenameDisplayWidget(ipw.Box):
    value = traitlets.Unicode()

    def __init__(self, max_width=None, **kwargs):
        self.max_width = max_width
        self._html = ipw.HTML()
        super().__init__([self._html], **kwargs)

    @traitlets.observe("value")
    def _observe_filename(self, change):
        icon = '<i class="fa fa-file-text-o" aria-hidden="true"></i>'
        width_style = f"width:{self.max_width};" if self.max_width else ""
        self._html.value = f"""
        <div style="
            white-space:nowrap;
            overflow:hidden;
            text-overflow:ellipsis;
            {width_style}">
            {icon} {change['new']}
        </div>
        """


class LogOutputWidget(ipw.VBox):
    filename = traitlets.Unicode()
    value = traitlets.Unicode()

    def __init__(self, placeholder=None, **kwargs):
        self.placeholder = placeholder

        self._rolling_output = RollingOutput(layout=ipw.Layout(flex="1 1 auto"))
        ipw.dlink(
            (self, "value"),
            (self._rolling_output, "value"),
            lambda value: value or self.placeholder or "",
        )

        self._filename_display = FilenameDisplayWidget(
            layout=ipw.Layout(width="auto"), max_width="55em"
        )
        ipw.dlink(
            (self, "filename"),
            (self._filename_display, "value"),
            lambda value: value or "[no filename]",
        )

        self._btn_download = DownloadButton(
            layout=ipw.Layout(width="30px", flex="5 1 auto"),
            disabled=True,
        )
        ipw.dlink((self, "filename"), (self._btn_download, "filename"))
        ipw.dlink(
            (self, "value"),
            (self._btn_download, "payload"),
            transform=lambda value: value.encode("utf-8"),
        )

        self._btn_scroll_down = ipw.Button(
            icon="angle-double-down",
            tooltip="Scroll to bottom",
            layout=ipw.Layout(width="30px", flex="1 1 auto"),
            disabled=True,
        )
        self._btn_scroll_down.on_click(
            lambda _: self._rolling_output.scroll_to_bottom()
        )

        self._btn_auto_scroll = ipw.ToggleButton(
            icon="magic",
            tooltip="Auto-scroll with content",
            value=True,
            layout=ipw.Layout(flex="1 1 auto", width="30px"),
        )
        ipw.link(
            (self._btn_auto_scroll, "value"), (self._rolling_output, "auto_scroll")
        )

        self._btns = ipw.VBox(
            [self._btn_download, self._btn_scroll_down, self._btn_auto_scroll],
            layout=ipw.Layout(min_width="36px", flex_flow="column"),
        )

        super().__init__(
            [
                self._filename_display,
                ipw.HBox([self._rolling_output, self._btns]),
            ],
            **kwargs,
        )

    @traitlets.default("placeholder")
    def _default_placeholder(self):
        return "[empty]"

    @traitlets.observe("value")
    def _observe_value(self, change):
        self._btn_download.disabled = not change["new"]
        self._btn_scroll_down.disabled = not change["new"]


class CalcJobOutputFollower(traitlets.HasTraits):
    calcjob_uuid = traitlets.Unicode(allow_none=True)
    filename = traitlets.Unicode(allow_none=True)
    output = traitlets.List(trait=traitlets.Unicode)
    lineno = traitlets.Int()

    def __init__(self, **kwargs):
        self._output_queue = Queue()

        self._lock = Lock()
        self._push_thread = None
        self._pull_thread = None
        self._stop_follow_output = Event()
        self._follow_output_thread = None

        super().__init__(**kwargs)

    @traitlets.observe("calcjob_uuid")
    def _observe_calcjob(self, change):
        calcjob_uuid = change["new"]
        if change["old"] == calcjob_uuid:
            return

        with self._lock:
            # Stop following
            self._stop_follow_output.set()

            if self._follow_output_thread:
                self._follow_output_thread.join()
                self._follow_output_thread = None

            # Reset all traitlets and signals.
            self.output.clear()
            self.lineno = 0
            self._stop_follow_output.clear()

            # (Re/)start following
            if change["new"]:
                self._follow_output_thread = Thread(
                    target=self._follow_output, args=(calcjob_uuid,)
                )
                self._follow_output_thread.start()

    def _follow_output(self, calcjob_uuid):
        """Monitor calcjob and orchestrate pushing and pulling of output."""
        self._pull_thread = Thread(target=self._pull_output)
        self._pull_thread.start()
        self._push_thread = Thread(target=self._push_output, args=(calcjob_uuid,))
        self._push_thread.start()

    def _fetch_output(self, calcjob):
        assert isinstance(calcjob, CalcJobNode)
        if "retrieved" in calcjob.outputs:
            try:
                self.filename = calcjob.base.attributes.get("output_filename")
                with calcjob.outputs.retrieved.base.repository.open(self.filename) as f:
                    return f.read().splitlines()
            except OSError:
                return []

        elif "remote_folder" in calcjob.outputs:
            try:
                fn_out = calcjob.base.attributes.get("output_filename")
                self.filename = fn_out
                with NamedTemporaryFile() as tmpfile:
                    calcjob.outputs.remote_folder.getfile(fn_out, tmpfile.name)
                    return tmpfile.read().decode().splitlines()
            except OSError:
                return []
        else:
            return []

    _EOF = None

    def _push_output(self, calcjob_uuid, delay=0.2):
        """Push new log lines onto the queue."""
        lineno = 0
        calcjob = load_node(calcjob_uuid)
        while True:
            try:
                lines = self._fetch_output(calcjob)
            except Exception as error:
                self._output_queue.put([f"[ERROR: {error}]"])
            else:
                self._output_queue.put(lines[lineno:])
                lineno = len(lines)
            finally:
                if calcjob.is_sealed or self._stop_follow_output.wait(delay):
                    # Pushing EOF signals to the pull thread to stop.
                    self._output_queue.put(self._EOF)
                    break  # noqa: B012

    def _pull_output(self):
        """Pull new log lines from the queue and update traitlets."""
        while True:
            item = self._output_queue.get()
            if item is self._EOF:
                self._output_queue.task_done()
                break
            else:  # item is 'new lines'
                with self.hold_trait_notifications():
                    self.output.extend(item)
                    self.lineno += len(item)
                self._output_queue.task_done()


@register_viewer_widget("process.calculation.calcjob.CalcJobNode.")
class CalcJobNodeViewerWidget(ipw.VBox):
    def __init__(self, calcjob, **kwargs):
        self.calcjob = calcjob
        self.output_follower = CalcJobOutputFollower()
        self.log_output = LogOutputWidget()

        self.output_follower.calcjob_uuid = self.calcjob.uuid
        self.output_follower.observe(self._observe_output_follower_lineno, ["lineno"])

        super().__init__(
            [ipw.HTML(f"CalcJob: {self.calcjob}"), self.log_output], **kwargs
        )

    def _observe_output_follower_lineno(self, _):
        with self.hold_trait_notifications():
            self.log_output.filename = self.output_follower.filename
            self.log_output.value = "\n".join(self.output_follower.output)
