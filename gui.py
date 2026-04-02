"""
gui.py
======
Tkinter GUI for the hexapod spatial memory system.

Layout:
┌─────────────────────┬─────────────────────┬──────────────────────┐
│  Letzter Schritt    │  Aktuell            │  Objects             │
│  (camera + map)     │  (camera + map)     │  ID | Description    │
│                     │                     │  Color               │
├─────────────────────┴──────────┬──────────┤  (scrollable list)   │
│  Log (scrollable)              │  Hints   │                      │
├────────────────────────────────┴──────────┴──────────────────────┤
│  [ Next Step ]  [↺ +5°]  [↻ −5°]                   Status label │
└──────────────────────────────────────────────────────────────────┘

Requires: tkinter (built-in), Pillow
"""

import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Optional

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class HexapodGui:
    """Main application window."""

    IMG_WIDTH  = 512
    IMG_HEIGHT = 768   # camera (384) + map (384)
    WIN_TITLE  = "Hexapod Spatial Memory"

    def __init__(self, app):
        self._app = app
        self._root = tk.Tk()
        self._root.title(self.WIN_TITLE)
        self._root.resizable(True, True)

        self._photo_refs = {"before": None, "after": None}
        self._step_running = False

        self._build_ui()
        self._register_callbacks()
        # Maximise — Windows uses state("zoomed"), Linux uses the -zoomed attribute
        if self._root.tk.call("tk", "windowingsystem") == "win32":
            self._root.state("zoomed")
        else:
            self._root.attributes("-zoomed", True)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = self._root
        root.columnconfigure(0, weight=2)   # left:  "last step" image
        root.columnconfigure(1, weight=2)   # center: "current" image
        root.columnconfigure(2, weight=1)   # right:  objects list
        root.rowconfigure(0, weight=3)
        root.rowconfigure(1, weight=2)
        root.rowconfigure(2, weight=0)

        # ── Col 0 / Row 0: "last step" image ───────────────────────────
        before_frame = ttk.LabelFrame(root, text="Letzter Schritt")
        before_frame.grid(row=0, column=0, sticky="nsew", padx=(6, 2), pady=(6, 2))
        before_frame.rowconfigure(0, weight=1)
        before_frame.columnconfigure(0, weight=1)

        self._canvas_before = tk.Canvas(
            before_frame,
            width=self.IMG_WIDTH,
            height=self.IMG_HEIGHT,
            bg="#2a2a2a",
        )
        self._canvas_before.pack(fill="both", expand=True)
        self._canvas_before.create_text(
            self.IMG_WIDTH // 2, self.IMG_HEIGHT // 2,
            text="Noch kein Schritt",
            fill="#888888",
            font=("Helvetica", 12),
        )

        # ── Col 1 / Row 0: "current" image ─────────────────────────────
        after_frame = ttk.LabelFrame(root, text="Aktuell")
        after_frame.grid(row=0, column=1, sticky="nsew", padx=(2, 2), pady=(6, 2))
        after_frame.rowconfigure(0, weight=1)
        after_frame.columnconfigure(0, weight=1)

        self._canvas_after = tk.Canvas(
            after_frame,
            width=self.IMG_WIDTH,
            height=self.IMG_HEIGHT,
            bg="#2a2a2a",
        )
        self._canvas_after.pack(fill="both", expand=True)
        self._canvas_after.create_text(
            self.IMG_WIDTH // 2, self.IMG_HEIGHT // 2,
            text="No image yet",
            fill="#888888",
            font=("Helvetica", 12),
        )

        # ── Col 2 / Row 0+1: objects list ──────────────────────────────
        obj_frame = ttk.LabelFrame(root, text="Objects")
        obj_frame.grid(row=0, column=2, rowspan=2, sticky="nsew",
                       padx=(2, 6), pady=(6, 2))
        obj_frame.rowconfigure(0, weight=1)
        obj_frame.columnconfigure(0, weight=1)

        cols = ("id", "description", "color")
        self._obj_tree = ttk.Treeview(
            obj_frame, columns=cols, show="headings",
            selectmode="none",
        )
        self._obj_tree.heading("id",          text="ID")
        self._obj_tree.heading("description", text="Description")
        self._obj_tree.heading("color",       text="Color")
        self._obj_tree.column("id",          width=50,  stretch=False, anchor="w")
        self._obj_tree.column("description", width=180, stretch=True,  anchor="w")
        self._obj_tree.column("color",       width=90,  stretch=False, anchor="w")

        obj_scroll = ttk.Scrollbar(obj_frame, orient="vertical",
                                   command=self._obj_tree.yview)
        self._obj_tree.configure(yscrollcommand=obj_scroll.set)
        self._obj_tree.grid(row=0, column=0, sticky="nsew")
        obj_scroll.grid(row=0, column=1, sticky="ns")

        # ── Col 0+1 / Row 1: log + hints ───────────────────────────────
        mid_frame = ttk.Frame(root)
        mid_frame.grid(row=1, column=0, columnspan=2, sticky="nsew",
                       padx=(6, 2), pady=2)
        mid_frame.columnconfigure(0, weight=2)
        mid_frame.columnconfigure(1, weight=1)
        mid_frame.rowconfigure(0, weight=1)

        # Log panel
        log_frame = ttk.LabelFrame(mid_frame, text="Log")
        log_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        self._log_box = scrolledtext.ScrolledText(
            log_frame, state="disabled", wrap="word",
            font=("Courier", 9), bg="#1e1e1e", fg="#cccccc",
            height=10,
        )
        self._log_box.pack(fill="both", expand=True, padx=2, pady=2)

        # Hints panel
        hint_frame = ttk.LabelFrame(mid_frame, text="Operator Hints")
        hint_frame.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        hint_frame.columnconfigure(0, weight=1)

        # Category selector
        cat_frame = ttk.Frame(hint_frame)
        cat_frame.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(cat_frame, text="Category:").pack(side="left")
        self._hint_cat = tk.StringVar(value="one_time")
        for cat, label in [("permanent", "Permanent"),
                            ("session",   "Session"),
                            ("one_time",  "One-time")]:
            ttk.Radiobutton(
                cat_frame, text=label,
                variable=self._hint_cat, value=cat,
            ).pack(side="left", padx=2)

        # Hint text entry
        entry_frame = ttk.Frame(hint_frame)
        entry_frame.pack(fill="x", padx=4, pady=4)
        self._hint_entry = ttk.Entry(entry_frame)
        self._hint_entry.pack(side="left", fill="x", expand=True)
        self._hint_entry.bind("<Return>", lambda _: self._on_add_hint())
        ttk.Button(entry_frame, text="Add", command=self._on_add_hint).pack(side="left", padx=2)

        # Hint list
        self._hint_list = tk.Listbox(
            hint_frame, height=6, font=("Courier", 8),
            bg="#1e1e1e", fg="#cccccc", selectmode="single",
        )
        self._hint_list.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        btn_frame = ttk.Frame(hint_frame)
        btn_frame.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btn_frame, text="Delete selected",
                   command=self._on_delete_hint).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Clear all",
                   command=self._on_clear_hints).pack(side="left")

        # ── Row 2 / all cols: controls ──────────────────────────────────
        ctrl_frame = ttk.Frame(root)
        ctrl_frame.grid(row=2, column=0, columnspan=3, sticky="ew",
                        padx=6, pady=(2, 6))
        ctrl_frame.columnconfigure(3, weight=1)

        self._step_btn = ttk.Button(
            ctrl_frame, text="▶  Next Step",
            command=self._on_step, width=18,
        )
        self._step_btn.grid(row=0, column=0, padx=(0, 8))

        ttk.Button(
            ctrl_frame, text="↺  +5°",
            command=lambda: self._on_rotate(5), width=8,
        ).grid(row=0, column=1, padx=2)

        ttk.Button(
            ctrl_frame, text="↻  −5°",
            command=lambda: self._on_rotate(-5), width=8,
        ).grid(row=0, column=2, padx=(2, 12))

        self._status_var = tk.StringVar(value="Not started")
        ttk.Label(ctrl_frame, textvariable=self._status_var,
                  foreground="#888888").grid(row=0, column=3, sticky="w")

    # ------------------------------------------------------------------
    # Callbacks registered with HexapodApp
    # ------------------------------------------------------------------

    def _register_callbacks(self) -> None:
        self._app._on_log    = self._log
        self._app._on_update = self._on_update

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_step(self) -> None:
        if self._step_running:
            return
        self._step_running = True
        self._step_btn.config(state="disabled")
        self._set_status("Running …")
        self._app.trigger_step()

    def _on_rotate(self, delta_deg: float) -> None:
        threading.Thread(
            target=self._app.rotate_pose, args=(delta_deg,), daemon=True
        ).start()

    def _on_add_hint(self) -> None:
        text = self._hint_entry.get().strip()
        if not text:
            return
        cat = self._hint_cat.get()
        self._app.add_hint(text, cat)
        self._hint_entry.delete(0, "end")
        self._refresh_hints()

    def _on_delete_hint(self) -> None:
        sel = self._hint_list.curselection()
        if not sel:
            return
        line = self._hint_list.get(sel[0])
        # Format is "[category] text"
        if "] " in line:
            cat, text = line.split("] ", 1)
            cat = cat.lstrip("[")
            self._app.remove_hint(text, cat)
        self._refresh_hints()

    def _on_clear_hints(self) -> None:
        self._app.clear_hints()
        self._refresh_hints()

    # ------------------------------------------------------------------
    # Update callbacks (called from background thread → schedule via after)
    # ------------------------------------------------------------------

    def _on_update(self, before_image, after_image, summary: dict) -> None:
        self._root.after(0, self._apply_update, before_image, after_image, summary)

    def _apply_update(self, before_image, after_image, summary: dict) -> None:
        if before_image is not None and PIL_AVAILABLE:
            self._show_image(self._canvas_before, before_image, "before")
        if after_image is not None and PIL_AVAILABLE:
            self._show_image(self._canvas_after, after_image, "after")
        self._refresh_hints()
        self._refresh_objects()
        self._set_status(
            f"Objects: {len(self._app._map.objects)}  "
            f"Trace: {len(self._app._map.positions)}"
        )
        self._step_running = False
        self._step_btn.config(state="normal")

    def _log(self, message: str) -> None:
        """Thread-safe log append."""
        self._root.after(0, self._append_log, message)

    def _append_log(self, message: str) -> None:
        self._log_box.config(state="normal")
        self._log_box.insert("end", message + "\n")
        self._log_box.see("end")
        self._log_box.config(state="disabled")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _show_image(self, canvas: tk.Canvas, image: "Image.Image", ref_key: str) -> None:
        cw = canvas.winfo_width()  or self.IMG_WIDTH
        ch = canvas.winfo_height() or self.IMG_HEIGHT
        img = image.copy()
        img.thumbnail((cw, ch), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._photo_refs[ref_key] = photo   # keep reference to prevent GC
        canvas.delete("all")
        canvas.create_image(cw // 2, ch // 2, image=photo, anchor="center")

    def _refresh_hints(self) -> None:
        hints = self._app.get_hints()
        self._hint_list.delete(0, "end")
        for cat, items in hints.items():
            for text in items:
                self._hint_list.insert("end", f"[{cat}] {text}")

    def _refresh_objects(self) -> None:
        """Repopulate the objects treeview from current map state."""
        self._obj_tree.delete(*self._obj_tree.get_children())
        from object_manager import OBJECT_COLORS
        for obj in self._app._map.objects.get_all():
            color_name = obj.color or ""
            rgb = OBJECT_COLORS.get(color_name)
            tag = f"col_{color_name}"
            if rgb:
                hex_color = "#{:02x}{:02x}{:02x}".format(*rgb)
                self._obj_tree.tag_configure(tag, foreground=hex_color)
            self._obj_tree.insert(
                "", "end",
                values=(obj.id, obj.description, color_name),
                tags=(tag,),
            )

    def _set_status(self, text: str) -> None:
        self._status_var.set(text)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        if not self._app.start():
            self._log("ERROR: Could not start app. Check camera and API key.")
        self._refresh_hints()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Show map (+ static test image if given) immediately on startup
        self._root.after(100, self._show_initial_image)
        self._root.mainloop()

    def _show_initial_image(self) -> None:
        if not PIL_AVAILABLE:
            return
        img = self._app.get_initial_image()
        if img is not None:
            self._show_image(self._canvas_after, img, "after")
        self._refresh_objects()
        obj_count = len(self._app._map.objects)
        self._set_status(f"Objects: {obj_count}  (map loaded from disk)")

    def _on_close(self) -> None:
        self._app.shutdown()
        self._root.destroy()
