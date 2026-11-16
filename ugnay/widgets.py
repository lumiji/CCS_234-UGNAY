"""Reusable standard-library Tkinter presentation components."""

from base64 import b64encode
from pathlib import Path
import tkinter as tk
from tkinter import ttk

BG = "#F4F7FA"
WHITE = "#FFFFFF"
NAVY = "#14263D"
TEXT = "#192D47"
MUTED = "#5B708F"
BLUE = "#1757A0"
BLUE_HOVER = "#A7D5FF"
PALE_BLUE = "#EAF4FF"
BORDER = "#D8E2ED"
GREEN = "#1D6A3D"
PALE_GREEN = "#EAF7E7"
AMBER = "#9A5B00"
PALE_AMBER = "#FFF3DA"
RED = "#A92A36"
PALE_RED = "#FDECEE"
FONT = "Open Sans"
MONO = "IBM Plex Mono"
EMPTY_SCAN_MESSAGE = "No devices responded to discovery in this range"


def label(parent, text="", size=10, bold=False, color=TEXT, bg=WHITE, **kwargs):
    anchor = kwargs.pop("anchor", "w")
    return tk.Label(parent, text=text, font=(FONT, size, "bold" if bold else "normal"),
                    fg=color, bg=bg, anchor=anchor, **kwargs)


class IconStore:
    """Load the supplied PNGs using Tk alone; keep references alive.

    Missing assets gracefully fall back to text-only controls, so the application
    can still launch when only the Python source folder is copied.
    """

    def __init__(self, master):
        self.master = master
        self.root = Path(__file__).resolve().parent.parent / "icons"
        self.cache = {}

    def get(self, name, size=20, white=False):
        key = (name, size, white)
        if key not in self.cache:
            folder = "on-dark" if white else "icons"
            filename = f"{name}-white.png" if white else f"{name}.png"
            path = self.root / folder / filename
            try:
                source = tk.PhotoImage(master=self.master, data=b64encode(path.read_bytes()))
                # Assets are 96px. Integer subsampling needs no Pillow dependency.
                self.cache[key] = source.subsample(max(1, round(source.width() / size)))
            except (OSError, tk.TclError):
                self.cache[key] = None
        return self.cache[key]


class RoundedPanel(tk.Frame):
    """Rounded card background with an ordinary, geometry-managed body frame."""

    def __init__(self, parent, fill=WHITE, border=BORDER, padding=18, **kwargs):
        super().__init__(parent, bg=parent.cget("bg"), **kwargs)
        self.fill = fill
        self.border = border
        self.canvas = tk.Canvas(self, bg=self.cget("bg"), highlightthickness=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=fill)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)
        self.bind("<Configure>", self._draw)

    def _draw(self, event):
        w, h, r = self.winfo_width() - 1, self.winfo_height() - 1, 12
        self.canvas.delete("surface")
        self.canvas.create_polygon(
            r, 1, w-r, 1, w, 1, w, r, w, h-r, w, h, w-r, h,
            r, h, 1, h, 1, h-r, 1, r, 1, 1,
            smooth=True, splinesteps=24, fill=self.fill, outline=self.border,
            tags="surface",
        )


class ActionButton(tk.Button):
    def __init__(self, parent, text, command, icon=None, primary=False, **kwargs):
        background = BLUE if primary else WHITE
        super().__init__(
            parent, text=f"  {text}" if icon else text, command=command,
            image=icon or "", compound="left", font=(FONT, 10, "bold"),
            bg=background, fg=WHITE if primary else BLUE,
            activebackground=BLUE_HOVER if primary else PALE_BLUE,
            activeforeground=WHITE if primary else BLUE,
            relief="flat", bd=0, padx=16, pady=10, cursor="hand2",
            highlightthickness=1, highlightbackground=BLUE, highlightcolor=BLUE,
            disabledforeground="#A5B1C1", **kwargs,
        )


class StatusBadge(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=WHITE)
        self.text = label(self, size=9)
        self.text.pack(padx=9, pady=4)

    def set(self, text):
        palette = {
            "Responding": (GREEN, PALE_GREEN),
            "Packet loss": (AMBER, PALE_AMBER),
            "Unreachable": (RED, PALE_RED),
        }
        fg, bg = palette.get(text, (MUTED, "#E8EEF4"))
        self.configure(bg=bg)
        self.text.configure(text=text, fg=fg, bg=bg)


class Notice(RoundedPanel):
    def __init__(self, parent, icons):
        super().__init__(parent, fill=PALE_BLUE, border=PALE_BLUE, padding=14)
        self.symbol = label(self.body, bg=PALE_BLUE)
        self.symbol.pack(side="left", anchor="n", padx=(0, 12))
        self.copy = tk.Frame(self.body, bg=PALE_BLUE)
        self.copy.pack(side="left", fill="both", expand=True)
        self.title_label = label(self.copy, bold=True, bg=PALE_BLUE)
        self.title_label.pack(fill="x")
        self.message_label = label(self.copy, size=9, color=MUTED, bg=PALE_BLUE,
                                   justify="left", wraplength=450)
        self.message_label.pack(fill="x", pady=(4, 0))
        self.copy.bind("<Configure>", lambda e: self.message_label.configure(wraplength=max(120, e.width)))
        self.icons = icons

    def set(self, title, message, severity="info"):
        fg, bg, name = {
            "info": (BLUE, PALE_BLUE, "info"),
            "success": (GREEN, PALE_GREEN, "responded"),
            "warning": (AMBER, PALE_AMBER, "packet-loss"),
            "error": (RED, PALE_RED, "operation-error"),
        }.get(severity, (BLUE, PALE_BLUE, "info"))
        self.fill = self.border = bg
        for widget in (self.body, self.symbol, self.copy, self.title_label, self.message_label):
            widget.configure(bg=bg)
        self.symbol.configure(image=self.icons.get(name, 24) or "")
        self.title_label.configure(text=title, fg=fg)
        self.message_label.configure(text=message, fg=fg)
        self.event_generate("<Configure>")


class ScrollablePage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=BG, padx=26, pady=22)
        self.window_id = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._content_resize)
        self.canvas.bind("<Configure>", self._canvas_resize)

    def _content_resize(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_resize(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def scroll(self, delta):
        if self.content.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(delta, "units")


class DeviceTable(tk.Frame):
    def __init__(self, parent, on_select, expanded=False):
        super().__init__(parent, bg=WHITE)
        columns = ("hostname", "ip", "status", "loss") if expanded else ("hostname", "ip", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=5,
                                 selectmode="browse", style="Devices.Treeview")
        headings = {"hostname": "Hostname", "ip": "IP address", "status": "Latest test", "loss": "Packet loss"}
        widths = {"hostname": 170, "ip": 140, "status": 120, "loss": 90}
        for name in columns:
            self.tree.heading(name, text=headings[name], anchor="w")
            self.tree.column(name, width=widths[name], minwidth=widths[name] - 35,
                             stretch=True, anchor="w")
        self.tree.tag_configure("even", background=WHITE)
        self.tree.tag_configure("odd", background="#F8FAFD")
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        ybar.grid(row=0, column=1, sticky="ns")
        xbar = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        xbar.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.empty = label(self, "No devices detected. Use Scan Network to begin.",
                           color=MUTED, justify="center", wraplength=300)
        self.on_select = on_select
        self.updating = False
        self.expanded = expanded
        self.tree.bind("<<TreeviewSelect>>", self._selected)

    def _selected(self, _event):
        selection = self.tree.selection()
        if selection and not self.updating:
            self.on_select(selection[0])

    def set_devices(self, devices, selected_ip=None, *, scan_completed=False):
        self.updating = True
        try:
            self.tree.delete(*self.tree.get_children())
            for index, device in enumerate(devices):
                values = [device.display_name, device.ip_address, device.status.value]
                if self.expanded:
                    values.append(f"{device.result.packet_loss_percent:g}%" if device.result else "—")
                self.tree.insert("", "end", iid=device.ip_address, values=values,
                                 tags=("even" if index % 2 == 0 else "odd",))
            if selected_ip and self.tree.exists(selected_ip):
                self.tree.selection_set(selected_ip)
                self.tree.focus(selected_ip)
            if devices:
                self.empty.place_forget()
            else:
                self.empty.configure(text=(EMPTY_SCAN_MESSAGE if scan_completed else
                                           "No devices detected. Use Scan Network to begin."))
                self.empty.place(relx=.5, rely=.5, anchor="center")
        finally:
            self.updating = False

    def select(self, ip):
        if ip and self.tree.exists(ip) and self.tree.selection() != (ip,):
            self.tree.selection_set(ip)
            self.tree.focus(ip)
            self.tree.see(ip)


class ReplyChart(tk.Canvas):
    """Small optional Canvas chart; it renders supplied replies only."""

    def __init__(self, parent):
        super().__init__(parent, bg=WHITE, height=140, highlightthickness=0)
        self.replies = ()
        self.bind("<Configure>", lambda _e: self._draw())

    def set_replies(self, replies):
        self.replies = replies
        self._draw()

    def _draw(self):
        self.delete("all")
        width = max(self.winfo_width(), 100)
        height = max(self.winfo_height(), 120)
        if not self.replies:
            self.create_text(width/2, height/2, text="No reply data available", fill=MUTED, font=(FONT, 10))
            return
        left, top, right, bottom = 52, 16, width-18, height-30
        values = [r.latency_ms for r in self.replies if r.latency_ms is not None]
        ceiling = max(10.0, max(values, default=0) * 1.2)
        for fraction in (0, .5, 1):
            y = bottom - (bottom-top)*fraction
            self.create_line(left, y, right, y, fill=BORDER)
            self.create_text(left-9, y, anchor="e", text=f"{ceiling*fraction:.0f} ms", fill=MUTED, font=(FONT, 8))
        previous = None
        for index, reply in enumerate(self.replies):
            x = left + (right-left)*index/max(1, len(self.replies)-1)
            self.create_text(x, bottom+17, text=str(reply.sequence), fill=MUTED, font=(FONT, 9))
            if reply.latency_ms is None:
                self.create_text(x, top+15, text="Timeout", fill=AMBER, font=(FONT, 8))
                previous = None
                continue
            y = bottom-(bottom-top)*reply.latency_ms/ceiling
            if previous:
                self.create_line(*previous, x, y, fill=BLUE, width=2)
            self.create_oval(x-3, y-3, x+3, y+3, fill=WHITE, outline=BLUE, width=2)
            previous = (x, y)
