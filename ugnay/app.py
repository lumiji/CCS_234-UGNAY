"""UGNAY's complete Tkinter shell. Backend work belongs in the service stubs.

Navigation, selections, rendering, dialogs, and the worker/UI handoff are real.
Scans, pings, report generation, analysis, and export are NOT implemented.
"""

from dataclasses import replace
from datetime import datetime
from functools import partial
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .connectivity import ConnectivityService
from .demo_data import (
    SAMPLE_DEVICES, SAMPLE_NETWORK, SAMPLE_RECOMMENDATIONS, SAMPLE_REPORTS, SAMPLE_TIME,
)
from .discovery import DiscoveryService
from .models import DeviceStatus
from .reporting import ReportingService
from .widgets import (
    ActionButton, BG, BLUE, BORDER, DeviceTable, FONT, GREEN, IconStore,
    MONO, MUTED, NAVY, Notice, PALE_BLUE, ReplyChart, RoundedPanel,
    ScrollablePage, StatusBadge, TEXT, WHITE, label,
)


def latency(value):
    """Presentation formatting only; statistics must be provided by Member 2."""
    return "—" if value is None else f"{value:.1f} ms"


def loss(value):
    return "—" if value is None else f"{value:g}%"


def timestamp(value):
    return "Never" if value is None else value.strftime("%d %b %Y, %I:%M %p")


class UgnayApp(tk.Tk):
    def __init__(self, discovery=None, connectivity=None, reporting=None, demo=True):
        super().__init__()
        self.title("UGNAY | LAN Health Checker")
        self.geometry("1320x850")
        self.minsize(1000, 720)
        self.configure(bg=BG)
        self.discovery = discovery if discovery is not None else DiscoveryService()
        self.connectivity = connectivity if connectivity is not None else ConnectivityService()
        self.reporting = reporting if reporting is not None else ReportingService()
        self.network = SAMPLE_NETWORK if demo else None
        self.devices = {d.ip_address: d for d in SAMPLE_DEVICES} if demo else {}
        self.last_scan = SAMPLE_TIME if demo else None
        self.reports = list(SAMPLE_REPORTS) if demo else []
        self.selected_ip = "192.168.1.24" if demo else None
        self.selected_report_id = self.reports[0].report_id if self.reports else None
        self.recommendations = SAMPLE_RECOMMENDATIONS if demo else ()
        self.sample_devices = demo
        self.sample_report_ids = {r.report_id for r in self.reports}
        self.current_page = "Overview"
        self.busy = False
        self._closing = False
        self._ui_queue = Queue()
        self.icons = IconStore(self)
        self.tables = []
        self.pages = {}
        self.nav_buttons = {}
        self._action_buttons = []
        self.ping_count = tk.StringVar(self, "4")
        self.device_choice = tk.StringVar(self)
        self.status_text = tk.StringVar(self, "Ready · Sample data loaded · Backend services are not connected")
        self._configure_styles()
        self._build_shell()
        self._build_overview()
        self._build_devices()
        self._build_ping_tests()
        self._build_reports()
        # Let the canvas widths settle before filling wrap-dependent content.
        self.update_idletasks()
        self.refresh_views()
        self.show_page("Overview")
        self.bind_all("<MouseWheel>", self._mousewheel, add="+")
        self.bind_all("<Button-4>", self._mousewheel, add="+")
        self.bind_all("<Button-5>", self._mousewheel, add="+")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._poll_id = self.after(60, self._drain_ui_queue)

    def _configure_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Devices.Treeview", font=(FONT, 10), rowheight=44,
                        background=WHITE, fieldbackground=WHITE, foreground=TEXT,
                        borderwidth=0, relief="flat")
        style.configure("Devices.Treeview.Heading", font=(FONT, 9, "bold"),
                        background=BG, foreground=BLUE, relief="flat", padding=(10, 10))
        style.map("Devices.Treeview", background=[("selected", PALE_BLUE)],
                  foreground=[("selected", BLUE)])
        style.map("Devices.Treeview.Heading", background=[("active", PALE_BLUE)])
        style.configure("TCombobox", padding=8, font=(FONT, 10),
                        fieldbackground=WHITE, background=WHITE, foreground=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", WHITE)],
                  selectbackground=[("readonly", WHITE)],
                  selectforeground=[("readonly", TEXT)])
        style.configure("TScrollbar", background=BORDER, troughcolor=BG,
                        borderwidth=0, arrowsize=12)
        self.option_add("*TCombobox*Listbox.font", (FONT, 10))

    def _build_shell(self):
        sidebar = tk.Frame(self, bg=NAVY, width=196)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=NAVY)
        brand.pack(fill="x", padx=20, pady=(24, 28))
        logo = tk.Label(brand, text=" U ", bg=BLUE, fg=WHITE, font=(FONT, 16, "bold"),
                        padx=4, pady=4)
        logo.pack(side="left", padx=(0, 10))
        label(brand, "UGNAY", size=14, bold=True, bg=NAVY, color=WHITE).pack(side="left")
        for name, icon in (("Overview", "overview"), ("Devices", "devices"),
                           ("Ping tests", "ping-test"), ("Reports", "reports")):
            button = tk.Button(
                sidebar, text=f"  {name}", image=self.icons.get(icon, white=True) or "",
                compound="left", command=partial(self.show_page, name), anchor="w",
                bg=NAVY, fg="#B9D7F3", activebackground=BLUE, activeforeground=WHITE,
                font=(FONT, 11), bd=0, relief="flat", padx=16, pady=13,
                cursor="hand2", highlightthickness=0,
            )
            button.pack(fill="x")
            self.nav_buttons[name] = button
        label(sidebar, "Local network tools", size=9, bg=NAVY, color="#B9D7F3").pack(
            side="bottom", anchor="w", padx=18, pady=22)
        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(main, bg=WHITE, padx=28, pady=15)
        header.pack(fill="x")
        self.scan_button = self._button(header, "Scan Network", self.on_scan_network,
                                        "scan", primary=True)
        self.scan_button.pack(side="right", padx=(20, 0))
        headings = tk.Frame(header, bg=WHITE)
        headings.pack(side="left", fill="x", expand=True)
        self.page_title = label(headings, size=22, bold=True)
        self.page_title.pack(fill="x")
        self.page_subtitle = label(headings, size=10, color=MUTED, wraplength=540, justify="left")
        self.page_subtitle.pack(fill="x", pady=(3, 0))
        headings.bind("<Configure>", lambda e: self.page_subtitle.configure(wraplength=max(200, e.width)))
        tk.Frame(main, bg=BORDER, height=1).pack(fill="x")
        footer = tk.Frame(main, bg=WHITE, padx=18, pady=8)
        footer.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=90)
        self.progress.pack(side="right", padx=(12, 0))
        self.status_label = label(footer, size=9, color=MUTED, textvariable=self.status_text,
                                   wraplength=900, justify="left")
        self.status_label.pack(side="left", fill="x", expand=True)
        footer.bind("<Configure>", lambda e: self.status_label.configure(wraplength=max(200, e.width-150)))
        self.page_host = tk.Frame(main, bg=BG)
        self.page_host.pack(fill="both", expand=True)
        self.page_host.rowconfigure(0, weight=1)
        self.page_host.columnconfigure(0, weight=1)

    def _button(self, parent, text, command, icon=None, primary=False):
        button = ActionButton(parent, text, command,
                              self.icons.get(icon, white=primary) if icon else None, primary)
        self._action_buttons.append(button)
        return button

    def _new_page(self, name):
        page = ScrollablePage(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[name] = page
        return page.content

    def _sample_caption(self, parent):
        caption = label(parent, bg=BG, size=9, color=MUTED)
        caption.pack(fill="x", pady=(0, 12))
        return caption

    def _metric_cards(self, parent, captions):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 20))
        variables = []
        cards = []
        for i, caption in enumerate(captions):
            row.columnconfigure(i, weight=1, uniform="metric")
            card = RoundedPanel(row, padding=16)
            cards.append(card)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0 if i == len(captions)-1 else 7))
            label(card.body, caption, size=9, color=MUTED).pack(fill="x")
            variable = tk.StringVar(self, "—")
            label(card.body, size=15, bold=True, textvariable=variable).pack(fill="x", pady=(7, 0))
            variables.append(variable)
        layout = {"columns": len(captions)}

        def reflow(event):
            count = 2 if event.width < 900 else len(captions)
            if count == layout["columns"]:
                return
            layout["columns"] = count
            for index in range(len(captions)):
                row.columnconfigure(index, weight=1 if index < count else 0,
                                    uniform="metric" if index < count else "")
            for index, card in enumerate(cards):
                card.grid_configure(row=index // count, column=index % count,
                                    padx=(0 if index % count == 0 else 7,
                                          0 if index % count == count-1 else 7),
                                    pady=(0 if index < count else 12, 0))
        row.bind("<Configure>", reflow)
        return variables

    @staticmethod
    def _responsive_columns(frame, left, right, weights=(1, 1)):
        layout = {"stacked": False}

        def reflow(event):
            stacked = event.width < 880
            if stacked == layout["stacked"]:
                return
            layout["stacked"] = stacked
            frame.columnconfigure(0, weight=1 if stacked else weights[0], uniform="")
            frame.columnconfigure(1, weight=0 if stacked else weights[1], uniform="")
            left.grid_configure(row=0, column=0, padx=(0, 0 if stacked else 8))
            right.grid_configure(row=1 if stacked else 0, column=0 if stacked else 1,
                                 padx=(0 if stacked else 8, 0), pady=(16 if stacked else 0, 0))
        frame.bind("<Configure>", reflow)

    def _panel_title(self, panel, title, subtitle=None, icon=None):
        row = tk.Frame(panel.body, bg=panel.fill)
        row.pack(fill="x", pady=(0, 10))
        if icon:
            label(row, image=self.icons.get(icon) or "", bg=panel.fill).pack(side="left", padx=(0, 8))
        label(row, title, size=13, bold=True, bg=panel.fill).pack(side="left")
        if subtitle:
            label(panel.body, subtitle, size=9, color=MUTED, bg=panel.fill).pack(fill="x", pady=(0, 12))
        return row

    def _build_overview(self):
        parent = self._new_page("Overview")
        self.overview_caption = self._sample_caption(parent)
        self.overview_metrics = self._metric_cards(parent, (
            "Local IP address", "Network range", "Devices detected", "Last scan"))
        columns = tk.Frame(parent, bg=BG)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=1, uniform="overview")
        columns.columnconfigure(1, weight=1, uniform="overview")
        devices = RoundedPanel(columns)
        devices.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._panel_title(devices, "Detected devices", "Select a device to see its latest test.")
        self.overview_table = DeviceTable(devices.body, self.select_device)
        self.overview_table.pack(fill="both", expand=True)
        self.tables.append(self.overview_table)
        self.device_count_label = label(devices.body, size=9, color=MUTED)
        self.device_count_label.pack(fill="x", pady=(14, 0))
        detail = RoundedPanel(columns)
        detail.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        header = tk.Frame(detail.body, bg=WHITE)
        header.pack(fill="x")
        self.overview_test_button = self._button(header, "Test Connection", self.on_test_connection, "ping-test")
        self.overview_test_button.pack(side="right", padx=(10, 0))
        title = tk.Frame(header, bg=WHITE)
        title.pack(side="left", fill="x", expand=True)
        self.overview_name = label(title, size=14, bold=True, wraplength=200, justify="left")
        self.overview_name.pack(fill="x")
        self.overview_ip = label(title, size=10, color=MUTED)
        self.overview_ip.pack(fill="x", pady=(4, 0))
        tk.Frame(detail.body, bg=BORDER, height=1).pack(fill="x", pady=16)
        self.overview_stats = self._inline_metrics(detail.body)
        self.overview_replies = label(detail.body, size=10, bold=True)
        self.overview_replies.pack(fill="x", pady=(18, 6))
        self.overview_reply_values = label(detail.body, size=10, color=MUTED,
                                             wraplength=400, justify="left")
        self.overview_reply_values.pack(fill="x", pady=(0, 12))
        self.overview_notice = Notice(detail.body, self.icons)
        self.overview_notice.pack(fill="x")
        self._responsive_columns(columns, devices, detail)
        self.overview_security = Notice(parent, self.icons)
        self.overview_security.pack(fill="x", pady=(20, 0))
        self.overview_security.set("Security reminders", "Keep your firewall enabled and use strong, unique passwords.")

    def _inline_metrics(self, parent):
        row = tk.Frame(parent, bg=WHITE)
        row.pack(fill="x")
        variables = []
        for i, caption in enumerate(("Avg. latency", "Max. latency", "Packet loss")):
            row.columnconfigure(i, weight=1, uniform="inline")
            cell = tk.Frame(row, bg=WHITE)
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 8))
            label(cell, caption, size=9, color=MUTED).pack(fill="x")
            var = tk.StringVar(self, "—")
            label(cell, size=19, bold=True, textvariable=var).pack(fill="x", pady=(8, 0))
            variables.append(var)
        return variables

    def _build_devices(self):
        parent = self._new_page("Devices")
        self.devices_caption = self._sample_caption(parent)
        network = RoundedPanel(parent, fill="#EDF4FF")
        network.pack(fill="x", pady=(0, 18))
        label(network.body, image=self.icons.get("router", 48) or "", bg=network.fill).pack(side="left", padx=(0, 18))
        net_copy = tk.Frame(network.body, bg=network.fill)
        net_copy.pack(side="left", fill="x", expand=True)
        label(net_copy, "Your network", bold=True, size=12, bg=network.fill).pack(fill="x")
        self.network_label = label(net_copy, size=11, bg=network.fill)
        self.network_label.pack(fill="x", pady=(5, 0))
        self.network_scan_label = label(network.body, color=MUTED, bg=network.fill, justify="right")
        self.network_scan_label.pack(side="right", padx=(12, 0))
        columns = tk.Frame(parent, bg=BG)
        columns.pack(fill="x")
        columns.columnconfigure(0, weight=3)
        columns.columnconfigure(1, weight=2)
        table_panel = RoundedPanel(columns)
        table_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.devices_title = self._panel_title(table_panel, "Detected devices", icon="devices")
        self.devices_table = DeviceTable(table_panel.body, self.select_device, expanded=True)
        self.devices_table.pack(fill="both", expand=True)
        self.tables.append(self.devices_table)
        details = RoundedPanel(columns)
        details.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._panel_title(details, "Device details", icon="info")
        identity = tk.Frame(details.body, bg=WHITE)
        identity.pack(fill="x", pady=(4, 16))
        self.device_icon = label(identity)
        self.device_icon.pack(side="left", padx=(0, 12))
        text = tk.Frame(identity, bg=WHITE)
        text.pack(side="left", fill="x", expand=True)
        self.devices_name = label(text, size=13, bold=True, wraplength=230, justify="left")
        self.devices_name.pack(fill="x")
        self.devices_ip = label(text, size=11, color=MUTED)
        self.devices_ip.pack(fill="x", pady=(4, 0))
        tk.Frame(details.body, bg=BORDER, height=1).pack(fill="x", pady=(0, 10))
        status_row = tk.Frame(details.body, bg=WHITE)
        status_row.pack(fill="x", pady=5)
        label(status_row, "Status", color=MUTED).pack(side="left")
        self.devices_badge = StatusBadge(status_row)
        self.devices_badge.pack(side="right")
        self.device_detail_values = {}
        for caption in ("Average latency", "Maximum latency", "Packet loss", "Last seen"):
            row = tk.Frame(details.body, bg=WHITE)
            row.pack(fill="x", pady=6)
            label(row, caption, size=9, color=MUTED).pack(side="left")
            value = label(row, size=9, bold=True)
            value.pack(side="right")
            self.device_detail_values[caption] = value
        bottom = tk.Frame(parent, bg=BG)
        bottom.pack(fill="x", pady=(18, 0))
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)
        chart = RoundedPanel(bottom)
        chart.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._panel_title(chart, "Reply latency", "Latency (ms) by request number; gaps indicate timeouts.", "latency")
        self.reply_chart = ReplyChart(chart.body)
        self.reply_chart.pack(fill="x")
        self.devices_notice = Notice(bottom, self.icons)
        self.devices_notice.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._responsive_columns(columns, table_panel, details, (3, 2))
        self._responsive_columns(bottom, chart, self.devices_notice, (3, 2))

    def _build_ping_tests(self):
        parent = self._new_page("Ping tests")
        self.ping_caption = self._sample_caption(parent)
        controls = RoundedPanel(parent)
        controls.pack(fill="x", pady=(0, 18))
        controls.body.columnconfigure(0, weight=3)
        controls.body.columnconfigure(1, weight=1)
        controls.body.columnconfigure(2, weight=1)
        device_field = tk.Frame(controls.body, bg=WHITE)
        device_field.grid(row=0, column=0, sticky="ew", padx=(0, 24))
        label(device_field, "Select device", color=MUTED, size=9).pack(fill="x", pady=(0, 6))
        self.device_combo = ttk.Combobox(device_field, textvariable=self.device_choice,
                                          state="readonly", width=32)
        self.device_combo.pack(fill="x")
        self.device_combo.bind("<<ComboboxSelected>>", self._combo_selected)
        count_field = tk.Frame(controls.body, bg=WHITE)
        count_field.grid(row=0, column=1, sticky="ew", padx=(0, 24))
        label(count_field, "Ping count", color=MUTED, size=9).pack(fill="x", pady=(0, 6))
        self.count_combo = ttk.Combobox(count_field, textvariable=self.ping_count,
                                       state="readonly", values=("4", "10", "20"), width=7)
        self.count_combo.pack(fill="x")
        self.ping_button = self._button(controls.body, "Run ping test", self.on_test_connection,
                                        "ping-test", primary=True)
        self.ping_button.grid(row=0, column=2, sticky="sew")
        columns = tk.Frame(parent, bg=BG)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=3)
        columns.columnconfigure(1, weight=2)
        result = RoundedPanel(columns)
        result.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.ping_result_title = label(result.body, size=15, bold=True)
        self.ping_result_title.pack(fill="x")
        self.ping_result_subtitle = label(result.body, size=9, color=MUTED)
        self.ping_result_subtitle.pack(fill="x", pady=(5, 14))
        tk.Frame(result.body, bg=BORDER, height=1).pack(fill="x", pady=(0, 16))
        self.ping_stats = self._inline_metrics(result.body)
        label(result.body, "Ping results", bold=True).pack(fill="x", pady=(20, 8))
        self.ping_output = self._readonly_text(result.body, height=10, font=(MONO, 10))
        info = RoundedPanel(columns)
        info.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._panel_title(info, "Device info", icon="info")
        self.ping_device_icon = label(info.body)
        self.ping_device_icon.pack(pady=(10, 12))
        self.ping_device_name = label(info.body, size=15, bold=True, anchor="center",
                                       wraplength=280, justify="center")
        self.ping_device_name.pack(fill="x")
        self.ping_device_ip = label(info.body, size=11, color=MUTED, anchor="center")
        self.ping_device_ip.pack(fill="x", pady=(5, 18))
        status = tk.Frame(info.body, bg=WHITE)
        status.pack(fill="x", pady=(0, 18))
        label(status, "Status", bold=True).pack(side="left")
        self.ping_badge = StatusBadge(status)
        self.ping_badge.pack(side="right")
        self.ping_notice = Notice(info.body, self.icons)
        self.ping_notice.pack(fill="both", expand=True)
        self._responsive_columns(columns, result, info, (3, 2))
        reminder = Notice(parent, self.icons)
        reminder.pack(fill="x", pady=(18, 0))
        reminder.set("Recommendation", "Keep your network secure by using a firewall and strong passwords.")

    def _readonly_text(self, parent, height=10, font=(FONT, 10)):
        frame = tk.Frame(parent, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, height=height, bg="#F8FAFD", fg=TEXT, relief="flat",
                       font=font, padx=12, pady=12, wrap="word", cursor="arrow",
                       selectbackground=PALE_BLUE, selectforeground=TEXT, state="disabled")
        bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        return text

    @staticmethod
    def _set_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _build_reports(self):
        parent = self._new_page("Reports")
        self.reports_caption = self._sample_caption(parent)
        self.report_metrics = self._metric_cards(parent, (
            "Devices detected", "Network health", "Avg. latency", "Packet loss"))
        columns = tk.Frame(parent, bg=BG)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=2)
        columns.columnconfigure(1, weight=3)
        history = RoundedPanel(columns)
        history.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._panel_title(history, "Report history", "Select a saved summary to preview it.", "last-scan")
        self.report_tree = ttk.Treeview(history.body, columns=("date", "summary"),
                                       show="headings", selectmode="browse", height=6,
                                       style="Devices.Treeview")
        self.report_tree.heading("date", text="Date / time", anchor="w")
        self.report_tree.heading("summary", text="Devices / loss", anchor="w")
        self.report_tree.column("date", width=180, minwidth=130)
        self.report_tree.column("summary", width=115, minwidth=90)
        self.report_tree.pack(fill="both", expand=True)
        self.report_tree.bind("<<TreeviewSelect>>", self._report_selected)
        self.generate_button = self._button(history.body, "Generate Report", self.on_generate_report, "reports")
        self.generate_button.pack(fill="x", pady=(16, 0))
        preview = RoundedPanel(columns)
        preview.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._panel_title(preview, "Report preview", icon="reports")
        self.report_output = self._readonly_text(preview.body, height=17, font=(MONO, 10))
        self.export_button = self._button(preview.body, "Export Report (.txt)", self.on_export_report,
                                           "export", primary=True)
        self.export_button.pack(fill="x", pady=(14, 0))
        recommendations = RoundedPanel(parent, fill="#EDF4FF")
        recommendations.pack(fill="x", pady=(18, 0))
        self._panel_title(recommendations, "Security recommendations", icon="info")
        self.recommendation_container = tk.Frame(recommendations.body, bg=recommendations.fill)
        self.recommendation_container.pack(fill="x")
        self._responsive_columns(columns, history, preview, (2, 3))

    # UI state and rendering. These methods accept completed member results.

    def show_page(self, name):
        self.current_page = name
        self.pages[name].tkraise()
        titles = {
            "Overview": ("Network overview", "Find devices on your network and check how they respond."),
            "Devices": ("Devices", "Find devices on your local network and check their connection."),
            "Ping tests": ("Ping tests", "Check the responsiveness of a device on your local network."),
            "Reports": ("Reports", "View network summaries, recommendations, and report previews."),
        }
        title, subtitle = titles[name]
        self.page_title.configure(text=title)
        self.page_subtitle.configure(text=subtitle)
        for nav_name, button in self.nav_buttons.items():
            button.configure(bg=BLUE if nav_name == name else NAVY,
                             fg=WHITE if nav_name == name else "#B9D7F3")

    @property
    def selected_device(self):
        return self.devices.get(self.selected_ip)

    @property
    def selected_report(self):
        return next((r for r in self.reports if r.report_id == self.selected_report_id), None)

    def select_device(self, ip_address):
        if ip_address not in self.devices or self.selected_ip == ip_address:
            return
        self.selected_ip = ip_address
        for table in self.tables:
            table.select(ip_address)
        self._refresh_selection()

    def _combo_selected(self, _event):
        selected = self.device_combo.current()
        ips = list(self.devices)
        if 0 <= selected < len(ips):
            self.select_device(ips[selected])

    def refresh_views(self):
        sample = "SAMPLE DATA · Example network and device entries are loaded."
        caption = sample if self.sample_devices else "Scan and connectivity results"
        for widget in (self.overview_caption, self.devices_caption, self.ping_caption):
            widget.configure(text=caption)
        values = (
            self.network.local_ip if self.network else "Not detected",
            self.network.subnet if self.network else "Not detected",
            str(len(self.devices)),
            self.last_scan.strftime("%I:%M %p") if self.last_scan else "Never",
        )
        for var, value in zip(self.overview_metrics, values):
            var.set(value)
        self.network_label.configure(text=(f"{self.network.local_ip}  ·  {self.network.subnet}"
                                           if self.network else "Local IP and subnet not detected"))
        self.network_scan_label.configure(text=f"Last scan\n{timestamp(self.last_scan)}")
        self.device_count_label.configure(text=f"{len(self.devices)} devices {'in sample data' if self.sample_devices else 'detected in the latest scan'}")
        for table in self.tables:
            table.set_devices(tuple(self.devices.values()), self.selected_ip)
        self.device_combo.configure(values=tuple(f"{d.display_name} — {d.ip_address}" for d in self.devices.values()))
        self._refresh_selection()
        self._refresh_report_history()
        self._refresh_report_preview()
        self._update_action_states()

    def _refresh_selection(self):
        device = self.selected_device
        name = device.display_name if device else "No device selected"
        ip = device.ip_address if device else "Select a device from the table."
        result = device.result if device else None
        status = device.status.value if device else "Not tested"
        for widget in (self.overview_name, self.devices_name, self.ping_device_name):
            widget.configure(text=name)
        for widget in (self.overview_ip, self.devices_ip, self.ping_device_ip):
            widget.configure(text=ip)
        self.devices_badge.set(status)
        self.ping_badge.set(status)
        icon_name = "router" if device and device.kind == "router" else "devices"
        self.device_icon.configure(image=self.icons.get(icon_name, 48) or "")
        self.ping_device_icon.configure(image=self.icons.get(icon_name, 96) or "")
        metrics = (latency(result.average_latency_ms), latency(result.maximum_latency_ms),
                   loss(result.packet_loss_percent)) if result else ("—", "—", "—")
        for group in (self.overview_stats, self.ping_stats):
            for variable, value in zip(group, metrics):
                variable.set(value)
        for caption, value in zip(("Average latency", "Maximum latency", "Packet loss"), metrics):
            self.device_detail_values[caption].configure(text=value)
        self.device_detail_values["Last seen"].configure(text=timestamp(device.last_seen if device else None))
        if device:
            self.device_combo.current(list(self.devices).index(device.ip_address))
        else:
            self.device_choice.set("")
        if result:
            # Counts here label existing reply records; latency/loss calculations
            # remain entirely in Member 2's future service implementation.
            successful = sum(reply.latency_ms is not None for reply in result.replies)
            self.overview_replies.configure(text=f"{successful} of {len(result.replies)} replies")
            self.overview_reply_values.configure(text="   ".join(
                latency(r.latency_ms) if r.latency_ms is not None else "Timed out" for r in result.replies))
            self.ping_result_title.configure(text="Sample test results" if self.sample_devices else "Latest ping test")
            self.ping_result_subtitle.configure(text=f"{len(result.replies)} requests · {timestamp(result.tested_at)}")
            lines = [f"{r.sequence}.  Request timed out." if r.latency_ms is None
                     else f"{r.sequence}.  Reply from {device.ip_address}: time={r.latency_ms:.1f} ms"
                     for r in result.replies]
            self._set_text(self.ping_output, "\n".join(lines))
        else:
            self.overview_replies.configure(text="No test results yet")
            self.overview_reply_values.configure(text="Choose a device, then use Test Connection.")
            self.ping_result_title.configure(text="Ready to test" if device else "Select a device")
            self.ping_result_subtitle.configure(text="No connectivity results are available for this device.")
            self._set_text(self.ping_output, "No ping results yet.\n\nThe connectivity service integration belongs in ugnay/connectivity.py.")
        title, message, severity = self._device_notice(device)
        for notice in (self.overview_notice, self.devices_notice, self.ping_notice):
            notice.set(title, message, severity)
        self.reply_chart.set_replies(result.replies if result else ())
        self._update_action_states()

    @staticmethod
    def _device_notice(device):
        # Presentation of an explicit service status, not an analyzer.
        if not device:
            return "No device selected", "Scan the network, then select a device.", "info"
        if device.status == DeviceStatus.PACKET_LOSS:
            return "Packet loss", "Some requests timed out. Run another test to check whether the loss repeats.", "warning"
        if device.status == DeviceStatus.UNREACHABLE:
            return "Unreachable host", "No replies were received. Check the device connection and ICMP/firewall settings.", "error"
        if device.status == DeviceStatus.RESPONDING:
            return "Device responding", "Replies are available. Keep your firewall enabled and software updated.", "success"
        return "Not tested", "Run a ping test to measure latency and packet loss.", "info"

    def _refresh_report_history(self):
        self.report_tree.delete(*self.report_tree.get_children())
        for report in self.reports:
            self.report_tree.insert("", "end", iid=report.report_id, values=(
                report.generated_at.strftime("%d %b %Y, %I:%M %p"),
                f"{report.device_count} devices · {loss(report.packet_loss_percent)}"))
        if self.selected_report_id and self.report_tree.exists(self.selected_report_id):
            self.report_tree.selection_set(self.selected_report_id)

    def _report_selected(self, _event):
        selection = self.report_tree.selection()
        if selection and selection[0] != self.selected_report_id:
            self.selected_report_id = selection[0]
            self._refresh_report_preview()

    def _refresh_report_preview(self):
        report = self.selected_report
        self.reports_caption.configure(text=(
            "SAMPLE REPORT · Static preview; generation and export are not connected."
            if report and report.report_id in self.sample_report_ids else
            "Selected report snapshot" if report else "No reports yet. Use Generate Report after scanning and testing."))
        metrics = (str(report.device_count), report.health, latency(report.average_latency_ms),
                   loss(report.packet_loss_percent)) if report else ("—", "—", "—", "—")
        for variable, value in zip(self.report_metrics, metrics):
            variable.set(value)
        self._set_text(self.report_output, report.text if report else
                       "No report selected.\n\nReport generation and export belong in ugnay/reporting.py.")
        for child in self.recommendation_container.winfo_children():
            child.destroy()
        recommendations = report.recommendations if report else self.recommendations
        if not recommendations:
            label(self.recommendation_container, "Recommendations will appear here when reporting is integrated.",
                  color=MUTED, bg="#EDF4FF", wraplength=650).pack(fill="x")
        for recommendation in recommendations:
            row = tk.Frame(self.recommendation_container, bg="#EDF4FF")
            row.pack(fill="x", pady=(0, 10))
            label(row, recommendation.title, bold=True, bg="#EDF4FF").pack(fill="x")
            message = label(row, recommendation.message, size=9, bg="#EDF4FF", color=MUTED,
                            wraplength=800, justify="left")
            message.pack(fill="x", pady=(3, 0))
            row.bind("<Configure>", lambda e, widget=message: widget.configure(wraplength=max(180, e.width)))
        self._update_action_states()

    # MEMBER 1 integration: service output -> apply_discovery_result(result).
    def on_scan_network(self):
        def work():
            network = self.discovery.detect_network()
            return self.discovery.scan_network(network.subnet)
        self._start_task("Scanning network", work, self.apply_discovery_result)

    def apply_discovery_result(self, result):
        """UI-thread entry point; accepts DiscoveryResult, including no devices."""
        self.network = result.network
        self.last_scan = result.scanned_at
        self.devices = {d.ip_address: d for d in result.devices}
        self.sample_devices = False
        if self.selected_ip not in self.devices:
            self.selected_ip = next(iter(self.devices), None)
        self.refresh_views()
        self.status_text.set(f"Scan complete · {len(self.devices)} devices detected" if self.devices
                             else "Scan complete · No active devices found in this network range")

    # MEMBER 2 integration: service output -> apply_ping_result(result).
    def on_test_connection(self):
        device = self.selected_device
        if not device:
            self.status_text.set("Select a device before running a connectivity test.")
            return
        count = int(self.ping_count.get())
        self._start_task(f"Testing {device.ip_address}",
                         partial(self.connectivity.test_connection, device, count),
                         self.apply_ping_result)

    def apply_ping_result(self, result):
        """UI-thread entry point; also handles all-timeout/unreachable results."""
        if result.ip_address not in self.devices:
            self.status_text.set("Test result ignored: this device is no longer in the current scan.")
            return
        self.devices[result.ip_address] = replace(self.devices[result.ip_address], result=result)
        self.refresh_views()
        self.status_text.set(f"Test complete · {result.ip_address} · {result.status.value}")

    # MEMBER 3 integration: output -> apply_report(report); export is a stub.
    def on_generate_report(self):
        if not self.devices or not self.network:
            self.status_text.set("Scan for devices before generating a report.")
            return
        self._start_task("Generating report", partial(
            self.reporting.generate_report, self.network, tuple(self.devices.values()),
            datetime.now().astimezone()), self.apply_report)

    def apply_report(self, report):
        """UI-thread entry point; report text and recommendations come from Member 3."""
        self.reports = [report] + [r for r in self.reports if r.report_id != report.report_id]
        self.selected_report_id = report.report_id
        self.recommendations = report.recommendations
        self._refresh_report_history()
        self._refresh_report_preview()
        self.status_text.set("Report generated · Ready to export")

    def on_export_report(self):
        report = self.selected_report
        if not report:
            return
        destination = filedialog.asksaveasfilename(
            parent=self, title="Export text report", defaultextension=".txt",
            filetypes=(("Text reports", "*.txt"),),
            initialfile=f"UGNAY-report-{report.generated_at:%Y%m%d-%H%M}.txt")
        if destination:
            self._start_task("Exporting report", partial(self.reporting.export_report, report, Path(destination)),
                             lambda _result: self.status_text.set(f"Report exported · {destination}"))

    # Async plumbing only; never invoke Tk from worker threads.
    def post_to_ui(self, callback, *args):
        self._ui_queue.put(partial(callback, *args))

    def _start_task(self, title, work, on_success):
        if self.busy:
            return
        self.busy = True
        self.status_text.set(f"{title}…")
        self.progress.start(12)
        self._update_action_states()

        def worker():
            try:
                result = work()
            except Exception as error:
                self.post_to_ui(self._finish_task, title, None, on_success, error)
            else:
                self.post_to_ui(self._finish_task, title, result, on_success, None)
        Thread(target=worker, daemon=True, name="ugnay-service").start()

    def _finish_task(self, title, result, on_success, error):
        self.busy = False
        self.progress.stop()
        self._update_action_states()
        if isinstance(error, NotImplementedError):
            self.status_text.set(f"Integration pending · {error}")
            messagebox.showinfo("Integration point", f"{error}\n\nThis version contains the interface and service stubs only.", parent=self)
        elif error is not None:
            self.show_operation_error(title, error)
        else:
            on_success(result)

    def show_operation_error(self, operation, error):
        self.status_text.set(f"{operation} failed · {error}")
        messagebox.showerror(f"{operation} failed", str(error), parent=self)

    def _drain_ui_queue(self):
        if self._closing:
            return
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                try:
                    callback()
                except Exception as error:
                    self.show_operation_error("Updating interface", error)
        except Empty:
            pass
        self._poll_id = self.after(60, self._drain_ui_queue)

    def _update_action_states(self):
        for button in self._action_buttons:
            button.configure(state="disabled" if self.busy else "normal")
        for name in ("ping_button", "overview_test_button"):
            button = getattr(self, name, None)
            if button:
                button.configure(state="normal" if self.selected_device and not self.busy else "disabled")
        if hasattr(self, "generate_button"):
            self.generate_button.configure(state="normal" if self.devices and not self.busy else "disabled")
        if hasattr(self, "export_button"):
            self.export_button.configure(state="normal" if self.selected_report and not self.busy else "disabled")

    def _mousewheel(self, event):
        # Respect native scrolling in results, tables, and the device picker.
        if isinstance(event.widget, (tk.Text, ttk.Treeview, ttk.Combobox)):
            return
        widget = event.widget
        page = self.pages[self.current_page]
        while widget is not None:
            if widget == page:
                delta = -1 if getattr(event, "num", None) == 4 else 1 if getattr(event, "num", None) == 5 else (-1 if event.delta > 0 else 1)
                page.scroll(delta * 3)
                break
            widget = getattr(widget, "master", None)

    def _close(self):
        self._closing = True
        self.after_cancel(self._poll_id)
        self.destroy()
