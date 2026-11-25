# -*- coding: utf-8 -*-
"""
주간 일정 위젯 (Weekly Schedule Widget)
- 바탕화면 우측 하단에 작게 상주하는 일정 위젯
  · 주간 탭: 월~일 일정
  · 전체 탭: 날짜 없는 할 일 목록 (기말고사 준비, 종강 후 할 일 …)
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
LIST_PALETTE = ["#6366f1", "#0ea5e9", "#14b8a6", "#f59e0b",
                "#ec4899", "#8b5cf6", "#22c55e", "#f97316"]

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
    "imp_bg":   "#fff7e6", "imp_fg": "#b45309",
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
    d.setdefault("items", {})      # 주간: {"YYYY-MM-DD": [item]}
    d.setdefault("lists", [])      # 전체: [{id,name,color,folded,items:[item]}]
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


def new_id():
    return uuid.uuid4().hex


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
#   ====== [ 이름 ] ======  → 주간 섹션 (<요일>, [라벨, MM/DD] 아래 항목을 날짜에 배치)
#   ---- [ 이름 ] ----      → 전체 목록 (날짜 없는 할 일)
# ------------------------------------------------------------------
_BULLETS = "⦁•·‣◦●○▪▫■□▸▹►▻◆◇★☆✓✔➤→\\-\\*\\+"
_RE_WEEK_SECTION = re.compile(r"^={3,}\s*\[?\s*(.+?)\s*\]?\s*={3,}$")
_RE_LIST_SECTION = re.compile(r"^-{3,}\s*\[?\s*(.+?)\s*\]?\s*-{3,}$")
_RE_WEEKDAY = re.compile(r"^<\s*([월화수목금토일])\s*(?:요일)?\s*>\s*$")
_RE_WEEKDAY2 = re.compile(r"^([월화수목금토일])요일\s*[:：]?\s*$")
_RE_BRACKET = re.compile(r"^\[(.+?)\]\s*[:：]?\s*$")
_RE_MMDD = re.compile(r"(\d{1,2})\s*[/\.\-]\s*(\d{1,2})")
_RE_BULLET = re.compile(r"^(?:[" + _BULLETS + r"]|\d+[.)])\s*(.*)$")
_PLACEHOLDERS = {"", "-", "–", "—", ".", "x", "X"}


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


def clean_text(t):
    """글머리 뒤 텍스트 정리. **강조** / *강조* 는 '중요' 표시로 바꾸고 별표 제거."""
    t = t.strip()
    important = "**" in t or bool(re.fullmatch(r"\*[^*].*\*", t))
    t = t.replace("**", "").strip()
    if len(t) >= 2 and t.startswith("*") and t.endswith("*"):
        t = t[1:-1].strip()
    t = re.sub(r"\s+", " ", t).strip()
    return t, important


def _bullet_text(line):
    m = _RE_BULLET.match(line)
    return clean_text(m.group(1) if m else line)


def parse_sticky_note(text):
    """반환: {"weekday": [(요일idx, text, category, important)],
             "dated":   [(date, text, category, important)],
             "lists":   [{"name": str, "items": [(text, important)]}]}"""
    res = {"weekday": [], "dated": [], "lists": []}
    mode = "week"
    section = weekday = cur_date = group_label = cur_list = None

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            cur_date = None
            continue

        m = _RE_WEEK_SECTION.match(line)
        if m and re.search(r"[^=\s\[\]]", m.group(1)):
            mode, section = "week", m.group(1).strip()
            weekday = cur_date = cur_list = None
            continue

        m = _RE_LIST_SECTION.match(line)
        if m and re.search(r"[^\-\s\[\]]", m.group(1)):
            mode = "list"
            cur_list = {"name": m.group(1).strip(), "items": []}
            res["lists"].append(cur_list)
            weekday = cur_date = None
            continue

        if mode == "list":
            txt, imp = _bullet_text(line)
            if txt not in _PLACEHOLDERS:
                cur_list["items"].append((txt, imp))
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

        txt, imp = _bullet_text(line)
        if txt in _PLACEHOLDERS:
            continue
        cat = section or "기타"
        if weekday is not None:
            res["weekday"].append((weekday, txt, cat, imp))
        elif cur_date is not None:
            full = f"{group_label}: {txt}" if group_label else txt
            res["dated"].append((cur_date, full, cat, imp))
    return res


def plan_import(text, week_start):
    """현재 주 기준 배치 계획: {"inweek": [(date,text,cat,imp)], "outside": n, "lists": [...]}"""
    res = parse_sticky_note(text)
    week_set = {iso(week_start + dt.timedelta(days=i)) for i in range(7)}
    inweek, outside = [], 0
    for widx, t, c, imp in res["weekday"]:
        inweek.append((week_start + dt.timedelta(days=widx), t, c, imp))
    for d, t, c, imp in res["dated"]:
        if iso(d) in week_set:
            inweek.append((d, t, c, imp))
        else:
            outside += 1
    inweek.sort(key=lambda x: x[0])
    return {"inweek": inweek, "outside": outside, "lists": res["lists"]}


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
        self.tab = self.data["window"].get("tab", "week")
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
        self.set_tab(self.tab, save=False)

        root.bind("<MouseWheel>", self._on_wheel)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(2000, lambda: self.check_update(manual=False))

    def _init_fonts(self):
        F = lambda size, **kw: tkfont.Font(family=FONT, size=size, **kw)
        self.f_tab = F(12, weight="bold")
        self.f_sub = F(9)
        self.f_ctrl = F(9)
        self.f_act = F(9)
        self.f_act_b = F(9, weight="bold")
        self.f_nav = F(13, weight="bold")
        self.f_chip = F(9, weight="bold")
        self.f_date = F(9, weight="bold")
        self.f_list = F(10, weight="bold")
        self.f_add = F(12)
        self.f_item = F(10)
        self.f_item_b = F(10, weight="bold")
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

    # ---------- UI ----------
    def _build(self):
        outer = tk.Frame(self.root, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        # 헤더
        header = tk.Frame(outer, bg=C["bg"])
        header.pack(fill="x")
        self.header = header

        row1 = tk.Frame(header, bg=C["bg"])
        row1.pack(fill="x", padx=S(14), pady=(S(10), S(4)))
        tabs = tk.Frame(row1, bg=C["bg"])
        tabs.pack(side="left")
        self.tab_widgets = {}
        for key, label in (("week", "주간"), ("all", "전체")):
            f = tk.Frame(tabs, bg=C["bg"])
            f.pack(side="left", padx=(0, S(16)))
            lbl = tk.Label(f, text=label, font=self.f_tab, bg=C["bg"], cursor="hand2")
            lbl.pack()
            bar = tk.Frame(f, bg=C["bg"], height=S(2))
            bar.pack(fill="x", pady=(S(2), 0))
            lbl.bind("<Button-1>", lambda e, k=key: self.set_tab(k))
            self.tab_widgets[key] = (lbl, bar)

        self._txt(row1, "✕", self.quit).pack(side="right", padx=(S(12), 0))
        self._txt(row1, "—", self.toggle_collapse).pack(side="right", padx=(S(12), 0))
        self.btn_pin = self._txt(row1, "고정", self.toggle_topmost,
                                 fg=C["accent"] if self.topmost else C["btn"],
                                 hi=C["accent_dk"])
        self.btn_pin.pack(side="right")

        row2 = tk.Frame(header, bg=C["bg"])
        row2.pack(fill="x", padx=S(14), pady=(0, S(10)))

        self.nav_week = tk.Frame(row2, bg=C["bg"])
        self._txt(self.nav_week, "‹", lambda: self.shift_week(-1), font=self.f_nav,
                  fg=C["sub"], hi=C["accent"]).pack(side="left")
        self.lbl_week = tk.Label(self.nav_week, text="", font=self.f_sub, bg=C["bg"], fg=C["sub"])
        self.lbl_week.pack(side="left", padx=S(6))
        self._txt(self.nav_week, "›", lambda: self.shift_week(1), font=self.f_nav,
                  fg=C["sub"], hi=C["accent"]).pack(side="left")
        self._solid(self.nav_week, "오늘", self.goto_today).pack(side="right")

        self.nav_all = tk.Frame(row2, bg=C["bg"])
        self.lbl_summary = tk.Label(self.nav_all, text="", font=self.f_sub, bg=C["bg"], fg=C["sub"])
        self.lbl_summary.pack(side="left", pady=S(3))
        self._solid(self.nav_all, "＋ 새 목록", self.new_list).pack(side="right")

        for w in (header, row1, row2, self.nav_week, self.nav_all,
                  self.lbl_week, self.lbl_summary):
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

    # ---------- 탭 ----------
    def set_tab(self, key, save=True):
        self.tab = key
        for k, (lbl, bar) in self.tab_widgets.items():
            on = (k == key)
            lbl.configure(fg=C["title"] if on else C["muted"])
            bar.configure(bg=C["accent"] if on else C["bg"])
        if key == "week":
            self.nav_all.pack_forget()
            self.nav_week.pack(fill="x")
        else:
            self.nav_week.pack_forget()
            self.nav_all.pack(fill="x")
        if save:
            self.data["window"]["tab"] = key
            self._persist()
        self.render()

    # ---------- 렌더링 ----------
    def _week_range_text(self):
        ws = self.week_start
        we = ws + dt.timedelta(days=6)
        return f"{ws.strftime('%Y.%m.%d')}  –  {we.strftime('%m.%d')}"

    def render(self, keep_scroll=False):
        pos = self.canvas.yview()[0] if keep_scroll else 0.0
        for ch in self.body.winfo_children():
            ch.destroy()
        if self.tab == "week":
            self.lbl_week.configure(text=self._week_range_text())
            today = dt.date.today()
            for i in range(7):
                day = self.week_start + dt.timedelta(days=i)
                self._render_day(day, i, is_today=(day == today))
        else:
            self._render_lists()
        tk.Frame(self.body, bg=C["bg"], height=S(6)).pack()
        self.body.update_idletasks()
        self._update_scroll()
        self.canvas.yview_moveto(pos)

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
        self._txt(head, "＋", lambda d=day: ItemDialog(self, d, None), font=self.f_add,
                  fg=C["muted"], hi=C["accent"], bg=bg).pack(side="right")

        for it in items:
            self._render_item(inner, bg, self._cat_color(it.get("category")), it,
                              on_edit=lambda d=day, i=it: ItemDialog(self, d, i))
        if items:
            tk.Frame(inner, bg=bg, height=S(6)).pack()

        tk.Frame(self.body, bg=C["sep"], height=max(1, S(1))).pack(fill="x", padx=S(12))

    def _render_lists(self):
        lists = self.data["lists"]
        remain = sum(1 for L in lists for it in L["items"] if not it.get("done"))
        self.lbl_summary.configure(
            text=f"목록 {len(lists)}개  ·  남은 할 일 {remain}개" if lists else "목록 없음")
        if not lists:
            box = tk.Frame(self.body, bg=C["bg"])
            box.pack(fill="x", padx=S(16), pady=S(28))
            tk.Label(box, text="아직 전체 목록이 없습니다", font=self.f_date,
                     bg=C["bg"], fg=C["sub"]).pack()
            tk.Label(box, text="메모에  ---- [ 목록 이름 ] ----  아래로\n할 일을 적고 '메모 가져오기' 하거나\n위의 '＋ 새 목록'을 누르세요",
                     font=self.f_status, bg=C["bg"], fg=C["muted"],
                     justify="center").pack(pady=(S(8), 0))
            return
        for L in lists:
            self._render_list(L)

    def _render_list(self, L):
        bg = C["bg"]
        items = L["items"]
        folded = L.get("folded", False)
        done_n = sum(1 for it in items if it.get("done"))

        block = tk.Frame(self.body, bg=bg)
        block.pack(fill="x")
        head = tk.Frame(block, bg=bg)
        head.pack(fill="x", padx=(S(12), S(10)), pady=(S(9), S(4) if not folded else S(9)))

        toggle = lambda L=L: self.toggle_fold(L)
        arrow = self._txt(head, "▸" if folded else "▾", toggle, font=self.f_date,
                          fg=C["muted"], hi=C["accent"])
        arrow.pack(side="left")
        tk.Frame(head, bg=L.get("color", C["accent"]), width=S(8), height=S(8)).pack(
            side="left", padx=(S(6), 0))
        name = tk.Label(head, text=L["name"], font=self.f_list, bg=bg, fg=C["title"],
                        cursor="hand2")
        name.pack(side="left", padx=(S(7), 0))
        name.bind("<Button-1>", lambda e: toggle())
        tk.Label(head, text=f"{done_n}/{len(items)}", font=self.f_status, bg=bg,
                 fg=C["muted"]).pack(side="left", padx=(S(7), 0))
        self._txt(head, "＋", lambda L=L: self.add_list_item(L), font=self.f_add,
                  fg=C["muted"], hi=C["accent"]).pack(side="right")
        self._txt(head, "편집", lambda L=L: self.edit_list(L), font=self.f_status,
                  fg=C["muted"], hi=C["accent"]).pack(side="right", padx=(0, S(10)))

        if not folded:
            if not items:
                tk.Label(block, text="할 일 없음", font=self.f_status, bg=bg,
                         fg=C["muted"]).pack(anchor="w", padx=S(34), pady=(0, S(4)))
            for it in items:
                self._render_item(block, bg, L.get("color", C["accent"]), it,
                                  on_edit=lambda L=L, i=it: self.edit_list_item(L, i))
            tk.Frame(block, bg=bg, height=S(6)).pack()

        tk.Frame(self.body, bg=C["sep"], height=max(1, S(1))).pack(fill="x", padx=S(12))

    def _render_item(self, parent, bg, color, it, on_edit):
        done = it.get("done", False)
        imp = it.get("important", False)

        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", padx=(S(13), S(10)), pady=S(2))

        tk.Frame(row, bg=C["done"] if done else color, width=S(3)).pack(side="left", fill="y")

        chk = self._checkbox(row, bg, done, lambda i=it: self.toggle_done(i))
        off = max(0, (self.f_item.metrics("linespace") - chk.winfo_reqheight()) // 2) + S(2)
        chk.pack(side="left", anchor="n", padx=(S(8), 0), pady=(off, 0))

        if done:
            font, fg = self.f_item_done, C["done"]
        elif imp:
            font, fg = self.f_item_b, C["title"]
        else:
            font, fg = self.f_item, C["text"]
        txt = tk.Label(row, text=it.get("text", ""), font=font, bg=bg, fg=fg,
                       cursor="hand2", anchor="w", justify="left",
                       wraplength=self.W - S(100 if imp and not done else 85))
        txt.pack(side="left", fill="x", expand=True, padx=(S(7), 0))
        txt.bind("<Button-1>", lambda e: on_edit())
        if imp and not done:
            tk.Label(row, text="중요", font=self.f_status, bg=C["imp_bg"], fg=C["imp_fg"],
                     padx=S(4)).pack(side="right", anchor="n", pady=(off, 0))

    def _cat_color(self, name):
        for c in self.data["categories"]:
            if c["name"] == name:
                return c["color"]
        return "#94a3b8"

    # ---------- 공통 동작 ----------
    def _commit(self):
        self._persist()
        self.render(keep_scroll=True)

    def toggle_done(self, it):
        it["done"] = not it.get("done", False)
        self._commit()

    # ---------- 주간 ----------
    def shift_week(self, delta):
        self.week_start += dt.timedelta(weeks=delta)
        self.render()

    def goto_today(self):
        self.week_start = monday_of(dt.date.today())
        self.render()

    def save_item(self, day, item, text, category):
        lst = self.data["items"].setdefault(iso(day), [])
        if item is None:
            lst.append({"id": new_id(), "text": text, "category": category, "done": False})
        else:
            item["text"], item["category"] = text, category
        self._commit()

    def delete_item(self, day, item):
        key = iso(day)
        self.data["items"][key] = [x for x in self.data["items"].get(key, [])
                                   if x.get("id") != item.get("id")]
        if not self.data["items"][key]:
            self.data["items"].pop(key, None)
        self._commit()

    # ---------- 전체 목록 ----------
    def toggle_fold(self, L):
        L["folded"] = not L.get("folded", False)
        self._commit()

    def new_list(self):
        def save(name, _imp):
            used = {L.get("color") for L in self.data["lists"]}
            color = next((c for c in LIST_PALETTE if c not in used),
                         LIST_PALETTE[len(self.data["lists"]) % len(LIST_PALETTE)])
            self.data["lists"].append({"id": new_id(), "name": name, "color": color,
                                       "folded": False, "items": []})
            if self.tab != "all":
                self.set_tab("all")
            self._commit()
        TextDialog(self, "새 목록", "", save, placeholder_label="목록 이름")

    def edit_list(self, L):
        def save(name, _imp):
            L["name"] = name
            self._commit()

        def delete():
            self.data["lists"].remove(L)
            self._commit()
        TextDialog(self, "목록 편집", L["name"], save, on_delete=delete,
                   delete_label="목록 삭제", confirm_delete=True,
                   placeholder_label="목록 이름")

    def add_list_item(self, L):
        def save(text, imp):
            L["items"].append({"id": new_id(), "text": text, "important": imp, "done": False})
            L["folded"] = False
            self._commit()
        TextDialog(self, f"할 일 추가 · {L['name']}", "", save, important=False)

    def edit_list_item(self, L, it):
        def save(text, imp):
            it["text"], it["important"] = text, imp
            self._commit()

        def delete():
            L["items"].remove(it)
            self._commit()
        TextDialog(self, f"할 일 편집 · {L['name']}", it.get("text", ""), save,
                   on_delete=delete, important=it.get("important", False))

    # ---------- 창 ----------
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
        plan = plan_import(text, self.week_start)
        inweek, outside, lists = plan["inweek"], plan["outside"], plan["lists"]
        if not inweek and not lists:
            self._toast(f"이번 주 밖 {outside}개뿐" if outside else "인식된 항목 없음")
            return False

        # 주간: 이번 주 교체 (같은 날짜·같은 내용이면 완료 체크 유지)
        if inweek:
            self._ensure_categories([c for _, _, c, _ in inweek])
            keys = [iso(self.week_start + dt.timedelta(days=i)) for i in range(7)]
            was_done = {(k, x.get("text")) for k in keys
                        for x in self.data["items"].get(k, []) if x.get("done")}
            for k in keys:
                self.data["items"].pop(k, None)
            for date, t, c, imp in inweek:
                self.data["items"].setdefault(iso(date), []).append(
                    {"id": new_id(), "text": t, "category": c, "important": imp,
                     "done": (iso(date), t) in was_done})

        # 전체: 메모의 목록으로 교체 (같은 목록·같은 내용이면 완료 체크, 색, 접힘 유지)
        if lists:
            prev = {L["name"]: L for L in self.data["lists"]}
            was_done = {(L["name"], it.get("text")) for L in self.data["lists"]
                        for it in L["items"] if it.get("done")}
            new_lists = []
            for i, L in enumerate(lists):
                p = prev.get(L["name"], {})
                new_lists.append({
                    "id": p.get("id", new_id()), "name": L["name"],
                    "color": p.get("color", LIST_PALETTE[i % len(LIST_PALETTE)]),
                    "folded": p.get("folded", False),
                    "items": [{"id": new_id(), "text": t, "important": imp,
                               "done": (L["name"], t) in was_done}
                              for t, imp in L["items"]],
                })
            self.data["lists"] = new_lists

        self._persist()
        self.render()
        parts = []
        if inweek:
            parts.append(f"주간 {len(inweek)}개")
        if lists:
            parts.append(f"목록 {len(lists)}개")
        self._toast(" · ".join(parts) + " 가져옴")
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


def _close_modal(top):
    try:
        top.grab_release()
    except Exception:
        pass
    top.destroy()


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
        _accent_head(wrap, app, f"메모 가져오기 · 주간은 {ws.strftime('%m/%d')}~{we.strftime('%m/%d')}")

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=S(14), pady=S(12))

        tk.Label(inner, text="Sticky Notes 내용을 붙여넣으세요 (Ctrl+V)",
                 font=app.f_act, bg=C["bg"], fg=C["sub"]).pack(anchor="w")
        self.text = tk.Text(inner, height=6, font=app.f_item, wrap="word",
                            relief="solid", bd=1, highlightthickness=1,
                            highlightbackground=C["field_bd"],
                            highlightcolor=C["accent"], padx=S(6), pady=S(5))
        self.text.pack(fill="x", pady=(S(5), S(8)))
        self.text.bind("<KeyRelease>", lambda e: self._refresh())
        self.text.bind("<<Paste>>", lambda e: self.top.after(20, self._refresh))

        tk.Label(inner, text="인식된 내용", font=app.f_act, bg=C["bg"],
                 fg=C["sub"]).pack(anchor="w")
        self.preview = tk.Text(inner, height=10, font=app.f_act, wrap="word",
                               relief="flat", bd=0, bg=C["today_bg"],
                               state="disabled", padx=S(8), pady=S(6))
        self.preview.tag_configure("h", font=app.f_act_b, foreground=C["accent_dk"])
        self.preview.tag_configure("m", foreground=C["muted"])
        self.preview.pack(fill="x", pady=(S(4), S(6)))

        tk.Label(inner, text="※ 이번 주 일정과 전체 목록이 메모 내용으로 바뀝니다 (완료 체크는 유지)",
                 font=app.f_status, bg=C["bg"], fg=C["muted"], justify="left",
                 wraplength=S(300)).pack(anchor="w", pady=(0, S(8)))

        btns = tk.Frame(inner, bg=C["bg"])
        btns.pack(fill="x")
        _dbtn(app, btns, "취소", lambda: _close_modal(top), C["chip_bg"], C["text"]).pack(
            side="right", padx=(S(6), 0))
        self.apply_btn = _dbtn(app, btns, "적용", self._apply, C["accent"], "#ffffff")
        self.apply_btn.pack(side="right")

        try:
            clip = app.root.clipboard_get()
        except Exception:
            clip = ""
        res = parse_sticky_note(clip) if clip else None
        if res and (res["weekday"] or res["dated"] or res["lists"]):   # 메모 형식일 때만 채움
            self.text.insert("1.0", clip)
        self._refresh()
        _place_modal(app, top, 340, 30)
        self.text.focus_set()
        top.bind("<Escape>", lambda e: _close_modal(top))

    def _refresh(self):
        plan = plan_import(self.text.get("1.0", "end"), self.app.week_start)
        inweek, outside, lists = plan["inweek"], plan["outside"], plan["lists"]
        p = self.preview
        p.configure(state="normal")
        p.delete("1.0", "end")
        if not inweek and not outside and not lists:
            p.insert("end", "아직 인식된 항목이 없습니다.\n\n", "m")
            p.insert("end", "====== [ 학교 일정 ] ======   → 주간\n<수요일>\n⦁ 할 일\n\n"
                            "---- [ 종강 후 할 일 ] ----   → 전체 목록\n⦁ 할 일", "m")
        else:
            p.insert("end", f"주간  {len(inweek)}개\n", "h")
            for date, t, c, imp in inweek:
                line = t if len(t) <= 22 else t[:21] + "…"
                p.insert("end", f"  {WEEKDAYS_KR[date.weekday()]} {date.strftime('%m/%d')}   {line}\n")
            if not inweek:
                p.insert("end", "  (이번 주에 해당하는 항목 없음)\n", "m")
            if outside:
                p.insert("end", f"  이번 주 밖 {outside}개는 제외\n", "m")
            if lists:
                p.insert("end", f"\n전체 목록  {len(lists)}개\n", "h")
                for L in lists:
                    p.insert("end", f"  {L['name']}  ·  {len(L['items'])}개\n")
        p.configure(state="disabled")
        n = len(inweek) + sum(len(L["items"]) for L in lists)
        self.apply_btn.configure(text=f"적용 ({n})" if n else "적용")

    def _apply(self):
        if self.app.apply_import(self.text.get("1.0", "end")):
            _close_modal(self.top)


# ------------------------------------------------------------------
# 텍스트 입력 대화상자 (목록 / 목록 항목용)
# ------------------------------------------------------------------
class TextDialog:
    def __init__(self, app, title, initial, on_save, on_delete=None, important=None,
                 delete_label="삭제", confirm_delete=False, placeholder_label="할 일"):
        self.app, self.on_save, self.on_delete = app, on_save, on_delete
        self.confirm_delete, self._armed = confirm_delete, False
        top, wrap = _modal(app)
        self.top = top
        _accent_head(wrap, app, title)

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=S(16), pady=S(14))

        tk.Label(inner, text=placeholder_label, font=app.f_act, bg=C["bg"],
                 fg=C["sub"]).pack(anchor="w")
        self.entry = tk.Entry(inner, font=app.f_item, relief="solid", bd=1,
                              highlightthickness=1, highlightbackground=C["field_bd"],
                              highlightcolor=C["accent"])
        self.entry.pack(fill="x", pady=(S(4), S(12)), ipady=S(4))
        self.entry.insert(0, initial)

        self.imp = important
        if important is not None:
            self.imp_btn = tk.Label(inner, text="중요 표시", font=app.f_act,
                                    padx=S(9), pady=S(3), cursor="hand2")
            self.imp_btn.pack(anchor="w", pady=(0, S(14)))
            self.imp_btn.bind("<Button-1>", lambda e: self._toggle_imp())
            self._style_imp()

        btns = tk.Frame(inner, bg=C["bg"])
        btns.pack(fill="x")
        if on_delete:
            self.del_btn = _dbtn(app, btns, delete_label, self._delete,
                                 C["danger_bg"], C["danger_fg"])
            self.del_btn.pack(side="left")
        _dbtn(app, btns, "취소", lambda: _close_modal(top), C["chip_bg"], C["text"]).pack(
            side="right", padx=(S(6), 0))
        _dbtn(app, btns, "저장", self._save, C["accent"], "#ffffff").pack(side="right")

        _place_modal(app, top, 320, 110)
        self.entry.focus_set()
        self.entry.icursor("end")
        top.bind("<Return>", lambda e: self._save())
        top.bind("<Escape>", lambda e: _close_modal(top))

    def _style_imp(self):
        if self.imp:
            self.imp_btn.configure(bg=C["imp_bg"], fg=C["imp_fg"])
        else:
            self.imp_btn.configure(bg=C["chip_bg"], fg=C["sub"])

    def _toggle_imp(self):
        self.imp = not self.imp
        self._style_imp()

    def _save(self):
        text = self.entry.get().strip()
        if not text:
            self.entry.configure(highlightbackground=C["danger_fg"])
            return
        _close_modal(self.top)
        self.on_save(text, bool(self.imp))

    def _delete(self):
        if self.confirm_delete and not self._armed:
            self._armed = True
            self.del_btn.configure(text="한 번 더 누르면 삭제")
            return
        _close_modal(self.top)
        self.on_delete()


# ------------------------------------------------------------------
# 주간 항목 추가/편집 (카테고리 선택 포함)
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
        _dbtn(app, btns, "취소", lambda: _close_modal(top), C["chip_bg"], C["text"]).pack(
            side="right", padx=(S(6), 0))
        _dbtn(app, btns, "저장", self._save, C["accent"], "#ffffff").pack(side="right")

        _place_modal(app, top, 320, 110)
        self.entry.focus_set()
        top.bind("<Return>", lambda e: self._save())
        top.bind("<Escape>", lambda e: _close_modal(top))

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
        _close_modal(self.top)
        self.app.save_item(self.day, self.item, text, self.cat)

    def _delete(self):
        _close_modal(self.top)
        if self.item:
            self.app.delete_item(self.day, self.item)


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
