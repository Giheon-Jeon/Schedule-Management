# -*- coding: utf-8 -*-
"""
주간 일정 위젯 (Weekly Schedule Widget)
- 바탕화면 우측 하단에 작게 상주하는 주간(월~일) 일정 보기/편집 위젯
- 고해상도(DPI) 대응으로 선명한 글자
- Sticky Notes 메모 붙여넣기 가져오기(미리보기) + 깃허브/로컬 변경 자동 반영
"""

import os
import re
import sys
import json
import time
import uuid
import ctypes
import hashlib
import threading
import subprocess
import datetime as dt
import tkinter as tk
from tkinter import font as tkfont

# ------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(__file__)
DATA_DIR = os.path.join(APP_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "schedule.json")

if os.name == "nt":
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
else:
    CREATE_NO_WINDOW = DETACHED_PROCESS = CREATE_NEW_PROCESS_GROUP = 0

DEFAULT_CATEGORIES = [
    {"name": "공부", "color": "#6366f1"},
    {"name": "업무", "color": "#22c55e"},
    {"name": "개인", "color": "#f59e0b"},
    {"name": "운동", "color": "#ef4444"},
    {"name": "기타", "color": "#94a3b8"},
]

WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]
WEEKDAY_IDX = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

IMPORT_PALETTE = [
    "#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
    "#ec4899", "#14b8a6", "#f97316", "#0ea5e9", "#64748b",
]

FONT = "Malgun Gothic"
W_WIDTH = 340      # 논리 픽셀 (DPI 배율이 곱해짐)
W_HEIGHT = 580

C = {
    "frame":    "#cdd5e3",
    "bg":       "#ffffff",
    "sep":      "#edf0f5",
    "title":    "#0f172a",
    "sub":      "#64748b",
    "muted":    "#a3adbb",
    "text":     "#1f2937",
    "accent":   "#6366f1",
    "accent_dk": "#4f46e5",
    "today_bg": "#f5f6ff",
    "chip_bg":  "#eef1f6",
    "chip_fg":  "#64748b",
    "done":     "#c3cbd8",
    "btn":      "#64748b",
    "btn_hi":   "#0f172a",
    "field_bd": "#dbe1ea",
    "sat_bg":   "#e4edff", "sat_fg": "#2563eb",
    "sun_bg":   "#ffe4e6", "sun_fg": "#dc2626",
    "danger_bg": "#fee2e2", "danger_fg": "#dc2626",
}

# ------------------------------------------------------------------
# 고해상도(DPI) 대응
# ------------------------------------------------------------------
SCALE = 1.0


def S(v):
    """논리 픽셀 -> 실제 픽셀"""
    return int(round(v * SCALE))


def enable_dpi_awareness():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # system DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def work_area(root):
    """작업표시줄을 제외한 화면 영역 (left, top, right, bottom)"""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]
        r = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):
            return r.l, r.t, r.r, r.b
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


# ------------------------------------------------------------------
# 단일 실행 보장 (중복 실행 방지)
# ------------------------------------------------------------------
_MUTEX = None


def acquire_single_instance(wait_sec=0):
    global _MUTEX
    if os.name != "nt":
        return True
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    deadline = time.time() + wait_sec
    while True:
        h = k.CreateMutexW(None, False, "Local\\WeeklyScheduleWidget")
        err = ctypes.get_last_error()
        if h and err != 183:          # 183 = ERROR_ALREADY_EXISTS
            _MUTEX = (k, h)
            return True
        if h:
            k.CloseHandle(h)
        if time.time() >= deadline:
            return False
        time.sleep(0.25)


def release_single_instance():
    global _MUTEX
    if _MUTEX:
        k, h = _MUTEX
        k.CloseHandle(h)
        _MUTEX = None


# ------------------------------------------------------------------
# 데이터 / 유틸
# ------------------------------------------------------------------
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
    else:
        d = {}
    d.setdefault("categories", [dict(c) for c in DEFAULT_CATEGORIES])
    d.setdefault("items", {})
    d.setdefault("window", {})
    return d


def save_data(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def monday_of(date):
    return date - dt.timedelta(days=date.weekday())


def iso(date):
    return date.strftime("%Y-%m-%d")


def run_git(args, timeout=30):
    try:
        return subprocess.run(["git"] + args, cwd=APP_DIR, capture_output=True,
                              text=True, timeout=timeout,
                              creationflags=CREATE_NO_WINDOW)
    except Exception:
        return None


def code_signature():
    """앱 코드(.pyw/.py) 내용의 해시 — 디스크의 코드가 바뀌었는지 판별용"""
    h = hashlib.sha1()
    for name in sorted(os.listdir(APP_DIR)):
        if name.endswith((".pyw", ".py")):
            try:
                with open(os.path.join(APP_DIR, name), "rb") as f:
                    h.update(name.encode())
                    h.update(f.read())
            except Exception:
                pass
    return h.hexdigest()


def script_compiles():
    try:
        with open(SCRIPT, "rb") as f:
            compile(f.read(), SCRIPT, "exec")
        return True
    except Exception:
        return False


def pythonw_exe():
    exe = sys.executable
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


# ------------------------------------------------------------------
# Sticky Notes 파서
# ------------------------------------------------------------------
_RE_SECTION = re.compile(r"^=+\s*\[?\s*(.+?)\s*\]?\s*=+$")
_RE_WEEKDAY = re.compile(r"^<\s*([월화수목금토일])\s*(?:요일)?\s*>\s*$")
_RE_WEEKDAY2 = re.compile(r"^([월화수목금토일])요일\s*[:：]?\s*$")
_RE_BRACKET = re.compile(r"^\[(.+?)\]\s*[:：]?\s*$")
_RE_MMDD = re.compile(r"(\d{1,2})\s*[/\.\-]\s*(\d{1,2})")
_RE_BULLET = re.compile(r"^(?:[•·‣◦●○▪▸▹◆■\-\*]|\d+[.)])\s*(.*)$")


def _make_date(mm, dd):
    today = dt.date.today()
    for y in (today.year, today.year + 1, today.year - 1):
        try:
            d = dt.date(y, mm, dd)
        except ValueError:
            return None
        if -180 <= (d - today).days <= 185:
            return d
    try:
        return dt.date(today.year, mm, dd)
    except ValueError:
        return None


def parse_sticky_note(text):
    weekday_entries, dated_entries = [], []
    section = weekday = cur_date = group_label = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            cur_date = None
            continue
        m = _RE_SECTION.match(line)
        if m and ("[" in line or "===" in line):
            section, weekday, cur_date = m.group(1).strip(), None, None
            continue
        m = _RE_WEEKDAY.match(line) or _RE_WEEKDAY2.match(line)
        if m:
            weekday, cur_date = WEEKDAY_IDX[m.group(1)], None
            continue
        m = _RE_BRACKET.match(line)
        if m:
            inside = m.group(1).strip()
            dm = _RE_MMDD.search(inside)
            if dm:
                group_label = inside.split(",")[0].strip()
                cur_date = _make_date(int(dm.group(1)), int(dm.group(2)))
                weekday = None
            else:
                section, weekday, cur_date = inside, None, None
            continue
        m = _RE_BULLET.match(line)
        txt = m.group(1).strip() if m else line
        if not txt or txt in ("-", "–", "—", "."):
            continue
        cat = section or "기타"
        if weekday is not None:
            weekday_entries.append((weekday, txt, cat))
        elif cur_date is not None:
            full = f"{group_label}: {txt}" if group_label else txt
            dated_entries.append((cur_date, full, cat))
    return weekday_entries, dated_entries


def plan_import(text, week_start):
    wd, dated = parse_sticky_note(text)
    week_set = {iso(week_start + dt.timedelta(days=i)) for i in range(7)}
    inweek, outside = [], 0
    for widx, t, c in wd:
        inweek.append((week_start + dt.timedelta(days=widx), t, c))
    for d, t, c in dated:
        if iso(d) in week_set:
            inweek.append((d, t, c))
        else:
            outside += 1
    inweek.sort(key=lambda x: x[0])
    return inweek, outside


# ------------------------------------------------------------------
# 메인 앱
# ------------------------------------------------------------------
class ScheduleWidget:
    def __init__(self, root):
        global SCALE
        self.root = root
        SCALE = root.winfo_fpixels("1i") / 96.0
        self.W, self.H = S(W_WIDTH), S(W_HEIGHT)

        self.data = load_data()
        self.week_start = monday_of(dt.date.today())
        self._drag = {"x": 0, "y": 0}
        self._updating = False
        self._toast_job = None
        self._sb_shown = False
        self._sig = code_signature()

        root.overrideredirect(True)
        root.configure(bg=C["frame"])
        self.topmost = bool(self.data["window"].get("topmost", False))
        root.attributes("-topmost", self.topmost)

        self._init_fonts()
        self._place_window()
        self._build()
        self.render()

        root.bind("<MouseWheel>", self._on_wheel)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(2000, lambda: self.check_update(manual=False))

    def _init_fonts(self):
        F = lambda size, **kw: tkfont.Font(family=FONT, size=size, **kw)
        self.f_title = F(12, weight="bold")
        self.f_sub = F(9)
        self.f_ctrl = F(9)
        self.f_act = F(9)
        self.f_act_b = F(9, weight="bold")
        self.f_nav = F(13, weight="bold")
        self.f_chip = F(9, weight="bold")
        self.f_date = F(9, weight="bold")
        self.f_add = F(12)
        self.f_item = F(10)
        self.f_item_done = F(10, overstrike=1)
        self.f_status = F(8)

    def _place_window(self):
        l, t, r, b = work_area(self.root)
        win = self.data["window"]
        x, y = win.get("px"), win.get("py")
        if x is None or y is None:
            x, y = r - self.W - S(12), b - self.H - S(12)
        x = max(l, min(x, r - S(80)))
        y = max(t, min(y, b - S(60)))
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    # ---------- 버튼 헬퍼 ----------
    def _txt(self, parent, text, cmd, font=None, fg=None, hi=None, bg=None):
        font, fg = font or self.f_ctrl, fg or C["btn"]
        hi, bg = hi or C["btn_hi"], bg or C["bg"]
        b = tk.Label(parent, text=text, font=font, bg=bg, fg=fg, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=hi))
        b.bind("<Leave>", lambda e: b.configure(fg=fg))
        return b

    def _solid(self, parent, text, cmd):
        b = tk.Label(parent, text=text, font=self.f_act, bg=C["accent"],
                     fg="#ffffff", cursor="hand2", padx=S(10), pady=S(2))
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=C["accent_dk"]))
        b.bind("<Leave>", lambda e: b.configure(bg=C["accent"]))
        return b

    # ---------- UI ----------
    def _build(self):
        outer = tk.Frame(self.root, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        # 헤더
        header = tk.Frame(outer, bg=C["bg"])
        header.pack(fill="x")
        self.header = header

        row1 = tk.Frame(header, bg=C["bg"])
        row1.pack(fill="x", padx=S(14), pady=(S(11), S(4)))
        title = tk.Label(row1, text="주간 일정", font=self.f_title,
                         bg=C["bg"], fg=C["title"])
        title.pack(side="left")
        self._txt(row1, "✕", self.quit).pack(side="right", padx=(S(12), 0))
        self._txt(row1, "—", self.toggle_collapse).pack(side="right", padx=(S(12), 0))
        self.btn_pin = self._txt(row1, "고정", self.toggle_topmost,
                                 fg=C["accent"] if self.topmost else C["btn"],
                                 hi=C["accent_dk"])
        self.btn_pin.pack(side="right")

        row2 = tk.Frame(header, bg=C["bg"])
        row2.pack(fill="x", padx=S(14), pady=(0, S(10)))
        self._txt(row2, "‹", lambda: self.shift_week(-1), font=self.f_nav,
                  fg=C["sub"], hi=C["accent"]).pack(side="left")
        self.lbl_week = tk.Label(row2, text="", font=self.f_sub, bg=C["bg"], fg=C["sub"])
        self.lbl_week.pack(side="left", padx=S(6))
        self._txt(row2, "›", lambda: self.shift_week(1), font=self.f_nav,
                  fg=C["sub"], hi=C["accent"]).pack(side="left")
        self._solid(row2, "오늘", self.goto_today).pack(side="right")

        for w in (header, row1, row2, title, self.lbl_week):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        tk.Frame(outer, bg=C["sep"], height=max(1, S(1))).pack(fill="x")

        # 본문 + 푸터 (접기 시 함께 숨김)
        self.main = tk.Frame(outer, bg=C["bg"])
        self.main.pack(fill="both", expand=True)

        footer = tk.Frame(self.main, bg=C["bg"])
        footer.pack(side="bottom", fill="x")
        tk.Frame(self.main, bg=C["sep"], height=max(1, S(1))).pack(side="bottom", fill="x")
        fin = tk.Frame(footer, bg=C["bg"])
        fin.pack(fill="x", padx=S(14), pady=S(8))
        self._txt(fin, "메모 가져오기", self.open_import, font=self.f_act_b,
                  fg=C["accent"], hi=C["accent_dk"]).pack(side="left")
        self._txt(fin, "새로고침", lambda: self.check_update(manual=True),
                  font=self.f_act, fg=C["sub"], hi=C["title"]).pack(side="right")
        self.lbl_status = tk.Label(fin, text="", font=self.f_status, bg=C["bg"],
                                   fg=C["muted"], anchor="center")
        self.lbl_status.pack(side="left", fill="x", expand=True, padx=S(6))

        body_wrap = tk.Frame(self.main, bg=C["bg"])
        body_wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body_wrap, bg=C["bg"], highlightthickness=0, bd=0)
        self.scroll = ThinScroll(body_wrap, self.canvas)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=C["bg"])
        self._body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self._update_scroll())
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        self.collapsed = False
        if self.data["window"].get("collapsed"):
            self.toggle_collapse()

    def _on_canvas_resize(self, e):
        self.canvas.itemconfig(self._body_id, width=e.width)
        self._update_scroll()

    def _update_scroll(self):
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        self.canvas.configure(scrollregion=bbox)
        need = (bbox[3] - bbox[1]) > self.canvas.winfo_height() + 2
        if need and not self._sb_shown:
            self.scroll.pack(side="right", fill="y", padx=(0, S(3)), pady=S(4),
                             before=self.canvas)
            self._sb_shown = True
        elif not need and self._sb_shown:
            self.scroll.pack_forget()
            self._sb_shown = False
            self.canvas.yview_moveto(0)

    # ---------- 렌더링 ----------
    def _week_range_text(self):
        ws = self.week_start
        we = ws + dt.timedelta(days=6)
        return f"{ws.strftime('%Y.%m.%d')}  –  {we.strftime('%m.%d')}"

    def render(self):
        self.lbl_week.configure(text=self._week_range_text())
        for ch in self.body.winfo_children():
            ch.destroy()
        today = dt.date.today()
        for i in range(7):
            day = self.week_start + dt.timedelta(days=i)
            self._render_day(day, i, is_today=(day == today))
        tk.Frame(self.body, bg=C["bg"], height=S(6)).pack()
        self.body.update_idletasks()
        self.canvas.yview_moveto(0)
        self._update_scroll()

    def _render_day(self, day, idx, is_today):
        items = self.data["items"].get(iso(day), [])
        bg = C["today_bg"] if is_today else C["bg"]

        block = tk.Frame(self.body, bg=bg)
        block.pack(fill="x")
        tk.Frame(block, bg=C["accent"] if is_today else bg, width=S(3)).pack(
            side="left", fill="y")
        inner = tk.Frame(block, bg=bg)
        inner.pack(side="left", fill="both", expand=True)

        head = tk.Frame(inner, bg=bg)
        head.pack(fill="x", padx=(S(10), S(10)),
                  pady=(S(7), S(3)) if items else S(5))

        if is_today:
            cbg, cfg = C["accent"], "#ffffff"
        elif idx == 5:
            cbg, cfg = C["sat_bg"], C["sat_fg"]
        elif idx == 6:
            cbg, cfg = C["sun_bg"], C["sun_fg"]
        else:
            cbg, cfg = C["chip_bg"], C["chip_fg"]
        tk.Label(head, text=WEEKDAYS_KR[idx], font=self.f_chip, bg=cbg, fg=cfg,
                 padx=S(6), pady=0).pack(side="left")
        tk.Label(head, text=day.strftime("%m/%d"), font=self.f_date, bg=bg,
                 fg=C["sub"] if items else C["muted"]).pack(side="left", padx=(S(8), 0))
        if is_today:
            tk.Label(head, text="오늘", font=self.f_status, bg=bg,
                     fg=C["accent"]).pack(side="left", padx=(S(6), 0))
        self._txt(head, "＋", lambda d=day: self.add_item(d), font=self.f_add,
                  fg=C["muted"], hi=C["accent"], bg=bg).pack(side="right")

        for it in items:
            self._render_item(inner, bg, day, it)
        if items:
            tk.Frame(inner, bg=bg, height=S(6)).pack()

        tk.Frame(self.body, bg=C["sep"], height=max(1, S(1))).pack(fill="x", padx=S(12))

    def _render_item(self, parent, bg, day, it):
        color = self._cat_color(it.get("category"))
        done = it.get("done", False)

        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", padx=(S(13), S(10)), pady=S(2))

        # 카테고리 색상 바 (선명한 사각형)
        tk.Frame(row, bg=C["done"] if done else color, width=S(3)).pack(
            side="left", fill="y")

        chk = self._checkbox(row, bg, done, lambda d=day, i=it: self.toggle_done(d, i))
        off = max(0, (self.f_item.metrics("linespace") - chk.winfo_reqheight()) // 2) + S(2)
        chk.pack(side="left", anchor="n", padx=(S(8), 0), pady=(off, 0))

        txt = tk.Label(row, text=it.get("text", ""),
                       font=self.f_item_done if done else self.f_item,
                       bg=bg, fg=C["done"] if done else C["text"], cursor="hand2",
                       anchor="w", justify="left", wraplength=self.W - S(85))
        txt.pack(side="left", fill="x", expand=True, padx=(S(7), 0))
        txt.bind("<Button-1>", lambda e, d=day, i=it: self.edit_item(d, i))

    def _checkbox(self, parent, bg, done, cmd):
        sz = S(14)
        cv = tk.Canvas(parent, width=sz, height=sz, bg=bg, highlightthickness=0,
                       bd=0, cursor="hand2")
        if done:
            cv.create_rectangle(0, 0, sz, sz, fill=C["done"], outline="")
            cv.create_line(sz * 0.24, sz * 0.52, sz * 0.43, sz * 0.71, sz * 0.78, sz * 0.31,
                           fill="#ffffff", width=max(2, S(1.6)),
                           capstyle="round", joinstyle="round")
        else:
            w = max(1, S(1.2))
            cv.create_rectangle(w // 2 + 1, w // 2 + 1, sz - w // 2 - 1, sz - w // 2 - 1,
                                outline="#b3bdca", width=w)
            cv.bind("<Enter>", lambda e: cv.itemconfig("all", outline=C["accent"]))
            cv.bind("<Leave>", lambda e: cv.itemconfig("all", outline="#b3bdca"))
        cv.bind("<Button-1>", lambda e: cmd())
        return cv

    def _cat_color(self, name):
        for c in self.data["categories"]:
            if c["name"] == name:
                return c["color"]
        return "#94a3b8"

    # ---------- 동작 ----------
    def shift_week(self, delta):
        self.week_start += dt.timedelta(weeks=delta)
        self.render()

    def goto_today(self):
        self.week_start = monday_of(dt.date.today())
        self.render()

    def toggle_done(self, day, it):
        it["done"] = not it.get("done", False)
        self._persist()
        self.render()

    def add_item(self, day):
        ItemDialog(self, day, None)

    def edit_item(self, day, it):
        ItemDialog(self, day, it)

    def save_item(self, day, item, text, category):
        lst = self.data["items"].setdefault(iso(day), [])
        if item is None:
            lst.append({"id": uuid.uuid4().hex, "text": text,
                        "category": category, "done": False})
        else:
            item["text"], item["category"] = text, category
        self._persist()
        self.render()

    def delete_item(self, day, item):
        key = iso(day)
        lst = self.data["items"].get(key, [])
        self.data["items"][key] = [x for x in lst if x.get("id") != item.get("id")]
        if not self.data["items"][key]:
            self.data["items"].pop(key, None)
        self._persist()
        self.render()

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.btn_pin.configure(fg=C["accent"] if self.topmost else C["btn"])
        self.data["window"]["topmost"] = self.topmost
        self._persist()

    def toggle_collapse(self):
        self.collapsed = not getattr(self, "collapsed", False)
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if self.collapsed:
            self.main.pack_forget()
            self.root.update_idletasks()
            h = self.header.winfo_reqheight() + S(1) + 3
            self.root.geometry(f"{self.W}x{h}+{x}+{y}")
        else:
            self.main.pack(fill="both", expand=True)
            self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.data["window"]["collapsed"] = self.collapsed
        self._persist()

    # ---------- 가져오기 ----------
    def open_import(self):
        ImportDialog(self)

    def apply_import(self, text):
        inweek, outside = plan_import(text, self.week_start)
        if not inweek:
            self._toast(f"이번 주 밖 {outside}개뿐" if outside else "인식된 항목 없음")
            return False
        self._ensure_categories([c for _, _, c in inweek])
        for i in range(7):
            self.data["items"].pop(iso(self.week_start + dt.timedelta(days=i)), None)
        for date, t, c in inweek:
            self.data["items"].setdefault(iso(date), []).append(
                {"id": uuid.uuid4().hex, "text": t, "category": c, "done": False})
        self._persist()
        self.render()
        self._toast(f"{len(inweek)}개 가져옴" + (f" · {outside}개 제외" if outside else ""))
        return True

    def _ensure_categories(self, names):
        existing = {c["name"] for c in self.data["categories"]}
        idx = len(self.data["categories"])
        for n in names:
            if n and n not in existing:
                self.data["categories"].append(
                    {"name": n, "color": IMPORT_PALETTE[idx % len(IMPORT_PALETTE)]})
                existing.add(n)
                idx += 1

    # ---------- 업데이트 / 새로고침 ----------
    def check_update(self, manual=False):
        """깃허브에서 받아오고(pull), 디스크의 코드가 실행 중인 코드와 다르면 재시작."""
        if self._updating:
            return
        self._updating = True
        if manual:
            self._toast("확인 중…", ms=60000)
        threading.Thread(target=self._update_worker, args=(manual,), daemon=True).start()

    def _update_worker(self, manual):
        pull = self._git_pull()
        changed = code_signature() != self._sig
        ok = script_compiles() if changed else True
        self.root.after(0, lambda: self._after_update(pull, changed, ok, manual))

    def _git_pull(self):
        top = run_git(["rev-parse", "--is-inside-work-tree"])
        if top is None or top.returncode != 0:
            return "no_git"
        up = run_git(["rev-parse", "--abbrev-ref", "@{u}"])
        if up is None or up.returncode != 0:
            return "no_remote"
        f = run_git(["fetch", "--quiet"])
        if f is None or f.returncode != 0:
            return "error"
        behind = run_git(["rev-list", "--count", "HEAD..@{u}"])
        try:
            n = int(behind.stdout.strip())
        except Exception:
            return "error"
        if n == 0:
            return "none"
        p = run_git(["pull", "--ff-only", "--quiet"])
        return "pulled" if (p and p.returncode == 0) else "conflict"

    def _after_update(self, pull, changed, ok, manual):
        self._updating = False
        if changed and ok:
            self._toast("새 버전 적용 · 재시작", ms=60000)
            self.root.after(600, self._restart)
            return
        if not manual:
            return
        if changed and not ok:
            self._toast("새 코드에 오류 — 재시작 안 함", ms=4000)
        elif pull == "conflict":
            self._toast("충돌로 받기 실패", ms=4000)
        elif pull in ("error", "no_remote", "no_git"):
            self._toast("깃허브 확인 실패 · 현재 최신", ms=4000)
        else:
            self._toast("이미 최신 버전입니다")

    def _toast(self, msg, ms=2600):
        self.lbl_status.configure(text=msg)
        if self._toast_job:
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(ms, lambda: self.lbl_status.configure(text=""))

    def _restart(self):
        self._persist()
        release_single_instance()
        try:
            subprocess.Popen([pythonw_exe(), SCRIPT, "--restarted"], cwd=APP_DIR,
                             creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
        except Exception:
            acquire_single_instance(0)
            self._toast("재시작 실패 — 직접 다시 실행해 주세요", ms=5000)
            return
        self.root.destroy()

    # ---------- 드래그 / 스크롤 / 저장 ----------
    def _drag_start(self, e):
        self._drag["x"] = e.x_root - self.root.winfo_x()
        self._drag["y"] = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._drag['x']}+{e.y_root - self._drag['y']}")

    def _drag_end(self, e):
        self.data["window"]["px"] = self.root.winfo_x()
        self.data["window"]["py"] = self.root.winfo_y()
        self._persist()

    def _on_wheel(self, e):
        if not self.collapsed and self._sb_shown:
            self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _persist(self):
        try:
            save_data(self.data)
        except Exception:
            pass

    def quit(self):
        self._persist()
        self.root.destroy()


# ------------------------------------------------------------------
# 얇은 스크롤바 (기본 스크롤바는 두껍고 투박해서 직접 그림)
# ------------------------------------------------------------------
class ThinScroll(tk.Canvas):
    def __init__(self, parent, target):
        super().__init__(parent, width=S(5), bg=C["bg"], highlightthickness=0, bd=0)
        self.target = target
        self.first, self.last = 0.0, 1.0
        self._color = "#d3d9e2"
        self._grab = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._hover("#aeb8c6"))
        self.bind("<Leave>", lambda e: self._hover("#d3d9e2"))
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._draw()

    def _hover(self, color):
        self._color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        h, w = self.winfo_height(), self.winfo_width()
        if self.last - self.first >= 1.0 or h <= 1:
            return
        y1 = self.first * h
        y2 = max(y1 + S(24), self.last * h)
        self.create_rectangle(0, y1, w, y2, fill=self._color, outline="")

    def _press(self, e):
        h = max(1, self.winfo_height())
        span = self.last - self.first
        if not (self.first * h <= e.y <= self.last * h):     # 트랙 클릭 → 그 위치로 이동
            self.target.yview_moveto(e.y / h - span / 2)
        self._grab = (e.y, self.first)

    def _move(self, e):
        if self._grab:
            y0, f0 = self._grab
            self.target.yview_moveto(f0 + (e.y - y0) / max(1, self.winfo_height()))


# ------------------------------------------------------------------
# 공통 모달
# ------------------------------------------------------------------
def _modal(app):
    top = tk.Toplevel(app.root)
    top.overrideredirect(True)
    top.configure(bg=C["frame"])
    top.attributes("-topmost", True)
    top.grab_set()
    wrap = tk.Frame(top, bg=C["bg"])
    wrap.pack(fill="both", expand=True, padx=1, pady=1)
    return top, wrap


def _accent_head(wrap, app, text):
    head = tk.Frame(wrap, bg=C["accent"])
    head.pack(fill="x")
    tk.Label(head, text=text, font=app.f_date, bg=C["accent"],
             fg="#ffffff").pack(side="left", padx=S(14), pady=S(8))


def _place_modal(app, top, w_logical, y_offset):
    top.update_idletasks()
    w, h = S(w_logical), top.winfo_reqheight()
    px = app.root.winfo_x() + (app.W - w) // 2
    py = max(S(20), app.root.winfo_y() + S(y_offset))
    top.geometry(f"{w}x{h}+{px}+{py}")


def _dbtn(app, parent, text, cmd, bg, fg):
    b = tk.Label(parent, text=text, font=app.f_date, bg=bg, fg=fg,
                 padx=S(16), pady=S(5), cursor="hand2")
    b.bind("<Button-1>", lambda e: cmd())
    return b


# ------------------------------------------------------------------
# 메모 가져오기 (붙여넣기 + 미리보기)
# ------------------------------------------------------------------
class ImportDialog:
    def __init__(self, app):
        self.app = app
        top, wrap = _modal(app)
        self.top = top
        ws = app.week_start
        we = ws + dt.timedelta(days=6)
        _accent_head(wrap, app, f"메모 가져오기 · {ws.strftime('%m/%d')}~{we.strftime('%m/%d')}")

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=S(14), pady=S(12))

        tk.Label(inner, text="Sticky Notes 내용을 붙여넣으세요 (Ctrl+V)",
                 font=app.f_act, bg=C["bg"], fg=C["sub"]).pack(anchor="w")
        self.text = tk.Text(inner, height=7, font=app.f_item, wrap="word",
                            relief="solid", bd=1, highlightthickness=1,
                            highlightbackground=C["field_bd"],
                            highlightcolor=C["accent"], padx=S(6), pady=S(5))
        self.text.pack(fill="x", pady=(S(5), S(8)))
        self.text.bind("<KeyRelease>", lambda e: self._refresh())
        self.text.bind("<<Paste>>", lambda e: self.top.after(20, self._refresh))

        tk.Label(inner, text="이번 주에 들어갈 항목", font=app.f_act, bg=C["bg"],
                 fg=C["sub"]).pack(anchor="w")
        self.preview = tk.Text(inner, height=8, font=app.f_act, wrap="word",
                               relief="flat", bd=0, bg=C["today_bg"],
                               state="disabled", padx=S(8), pady=S(6))
        self.preview.pack(fill="x", pady=(S(4), S(10)))

        btns = tk.Frame(inner, bg=C["bg"])
        btns.pack(fill="x")
        tk.Label(btns, text="※ 이번 주 기존 항목은 교체됩니다", font=app.f_status,
                 bg=C["bg"], fg=C["muted"]).pack(side="left")
        _dbtn(app, btns, "취소", self._close, C["chip_bg"], C["text"]).pack(
            side="right", padx=(S(6), 0))
        self.apply_btn = _dbtn(app, btns, "적용", self._apply, C["accent"], "#ffffff")
        self.apply_btn.pack(side="right")

        try:
            clip = app.root.clipboard_get()
        except Exception:
            clip = ""
        # 클립보드가 메모 형식일 때만 자동으로 채움
        if clip and any(parse_sticky_note(clip)):
            self.text.insert("1.0", clip)
        self._refresh()
        _place_modal(app, top, 340, 50)
        self.text.focus_set()
        top.bind("<Escape>", lambda e: self._close())

    def _refresh(self):
        inweek, outside = plan_import(self.text.get("1.0", "end"), self.app.week_start)
        p = self.preview
        p.configure(state="normal")
        p.delete("1.0", "end")
        if not inweek and not outside:
            p.insert("end", "아직 인식된 항목이 없습니다.\n"
                            "예)  <수요일>  /  • 할 일  /  [혜윰, 11/29]")
        else:
            if not inweek:
                p.insert("end", "이번 주에 해당하는 항목이 없습니다.\n주를 이동한 뒤 다시 시도하세요.\n")
            for date, t, c in inweek:
                line = t if len(t) <= 24 else t[:23] + "…"
                p.insert("end", f"{WEEKDAYS_KR[date.weekday()]} {date.strftime('%m/%d')}   {line}\n")
            if outside:
                p.insert("end", f"\n(이번 주 밖 {outside}개는 제외)")
        p.configure(state="disabled")
        n = len(inweek)
        self.apply_btn.configure(text=f"적용 ({n})" if n else "적용")

    def _apply(self):
        if self.app.apply_import(self.text.get("1.0", "end")):
            self._close()

    def _close(self):
        try:
            self.top.grab_release()
        except Exception:
            pass
        self.top.destroy()


# ------------------------------------------------------------------
# 항목 추가/편집
# ------------------------------------------------------------------
class ItemDialog:
    def __init__(self, app, day, item):
        self.app, self.day, self.item = app, day, item
        top, wrap = _modal(app)
        self.top = top
        title = "일정 편집" if item else "일정 추가"
        _accent_head(wrap, app, f"{title} · {day.strftime('%m/%d')} ({WEEKDAYS_KR[day.weekday()]})")

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=S(16), pady=S(14))

        tk.Label(inner, text="할 일", font=app.f_act, bg=C["bg"], fg=C["sub"]).pack(anchor="w")
        self.entry = tk.Entry(inner, font=app.f_item, relief="solid", bd=1,
                              highlightthickness=1, highlightbackground=C["field_bd"],
                              highlightcolor=C["accent"])
        self.entry.pack(fill="x", pady=(S(4), S(12)), ipady=S(4))
        self.entry.insert(0, item.get("text", "") if item else "")

        tk.Label(inner, text="카테고리", font=app.f_act, bg=C["bg"], fg=C["sub"]).pack(anchor="w")
        cat_frame = tk.Frame(inner, bg=C["bg"])
        cat_frame.pack(fill="x", pady=(S(6), S(14)))
        cur = item.get("category") if item else app.data["categories"][0]["name"]
        self.cat_btns = {}
        self.cat = cur
        row = tk.Frame(cat_frame, bg=C["bg"])
        row.pack(fill="x")
        for i, c in enumerate(app.data["categories"]):
            if i and i % 4 == 0:
                row = tk.Frame(cat_frame, bg=C["bg"])
                row.pack(fill="x", pady=(S(5), 0))
            b = tk.Label(row, text=c["name"], font=app.f_act, bg=C["chip_bg"],
                         fg=C["text"], padx=S(9), pady=S(3), cursor="hand2")
            b.pack(side="left", padx=(0, S(5)))
            b.bind("<Button-1>", lambda e, n=c["name"]: self._pick(n))
            self.cat_btns[c["name"]] = (b, c["color"])
        self._pick(cur)

        btns = tk.Frame(inner, bg=C["bg"])
        btns.pack(fill="x")
        if item:
            _dbtn(app, btns, "삭제", self._delete, C["danger_bg"], C["danger_fg"]).pack(side="left")
        _dbtn(app, btns, "취소", self._close, C["chip_bg"], C["text"]).pack(
            side="right", padx=(S(6), 0))
        _dbtn(app, btns, "저장", self._save, C["accent"], "#ffffff").pack(side="right")

        _place_modal(app, top, 320, 110)
        self.entry.focus_set()
        top.bind("<Return>", lambda e: self._save())
        top.bind("<Escape>", lambda e: self._close())

    def _pick(self, name):
        self.cat = name
        for n, (b, color) in self.cat_btns.items():
            if n == name:
                b.configure(bg=color, fg="#ffffff")
            else:
                b.configure(bg=C["chip_bg"], fg=C["text"])

    def _save(self):
        text = self.entry.get().strip()
        if not text:
            self.entry.configure(highlightbackground=C["danger_fg"])
            return
        self.app.save_item(self.day, self.item, text, self.cat)
        self._close()

    def _delete(self):
        if self.item:
            self.app.delete_item(self.day, self.item)
        self._close()

    def _close(self):
        try:
            self.top.grab_release()
        except Exception:
            pass
        self.top.destroy()


def main():
    enable_dpi_awareness()
    wait = 8 if "--restarted" in sys.argv else 0
    if not acquire_single_instance(wait):
        return      # 이미 실행 중
    root = tk.Tk()
    root.title("주간 일정")
    ScheduleWidget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
