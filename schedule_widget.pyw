# -*- coding: utf-8 -*-
"""
주간 일정 위젯 (Weekly Schedule Widget)
- 바탕화면 우측 하단에 작게 상주하는 주간(월~일) 일정 보기/편집 위젯
- 컴팩트 라이트 테마 · 빈 요일은 한 줄로 접힘
- Sticky Notes 메모 붙여넣기 가져오기(미리보기) + 깃허브 자동 업데이트
"""

import os
import re
import sys
import json
import uuid
import threading
import subprocess
import datetime as dt
import tkinter as tk
from tkinter import font as tkfont

# ------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "schedule.json")

if os.name == "nt":
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
else:
    CREATE_NO_WINDOW = 0
    DETACHED_PROCESS = 0

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
W_WIDTH = 340
W_HEIGHT = 560

C = {
    "frame":    "#cdd5e3",
    "bg":       "#ffffff",
    "sep":      "#eef1f6",
    "title":    "#0f172a",
    "sub":      "#64748b",
    "muted":    "#aab4c2",
    "text":     "#1f2937",
    "accent":   "#6366f1",
    "accent_dk": "#4f46e5",
    "today_bg": "#f6f7ff",
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
# 데이터
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


# ------------------------------------------------------------------
# Sticky Notes 파서 (여러 형식에 관대하게)
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
    """반환: (weekday_entries, dated_entries)
       weekday_entries: [(weekday_idx, text, category)]
       dated_entries:   [(date, text, category)]"""
    weekday_entries, dated_entries = [], []
    section = weekday = cur_date = group_label = None

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            cur_date = None
            continue

        m = _RE_SECTION.match(line)
        if m and ("[" in line or "=" * 3 in line):
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
    """현재 주 기준으로 들어갈 항목 목록과, 주 범위 밖 개수를 돌려줌."""
    wd, dated = parse_sticky_note(text)
    week_dates = [week_start + dt.timedelta(days=i) for i in range(7)]
    week_set = {iso(d) for d in week_dates}
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
        self.root = root
        self.data = load_data()
        self.week_start = monday_of(dt.date.today())
        self._drag = {"x": 0, "y": 0}
        self._updating = False
        self._toast_job = None

        root.overrideredirect(True)
        root.configure(bg=C["frame"])
        self.topmost = bool(self.data["window"].get("topmost", False))
        root.attributes("-topmost", self.topmost)

        self._place_window()
        self._init_fonts()
        self._build()
        self.render()

        root.bind("<MouseWheel>", self._on_wheel)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(1500, lambda: self.check_update(manual=False))

    def _init_fonts(self):
        self.f_title = tkfont.Font(family=FONT, size=12, weight="bold")
        self.f_sub = tkfont.Font(family=FONT, size=9)
        self.f_ctrl = tkfont.Font(family=FONT, size=9)
        self.f_act = tkfont.Font(family=FONT, size=9)
        self.f_nav = tkfont.Font(family=FONT, size=13, weight="bold")
        self.f_chip = tkfont.Font(family=FONT, size=9, weight="bold")
        self.f_date = tkfont.Font(family=FONT, size=9, weight="bold")
        self.f_add = tkfont.Font(family=FONT, size=12)
        self.f_item = tkfont.Font(family=FONT, size=10)
        self.f_item_done = tkfont.Font(family=FONT, size=10, overstrike=1)

    def _place_window(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win = self.data["window"]
        x, y = win.get("x"), win.get("y")
        if x is None or y is None:
            x, y = sw - W_WIDTH - 16, sh - W_HEIGHT - 56
        x = max(0, min(x, sw - 80))
        y = max(0, min(y, sh - 80))
        self.root.geometry(f"{W_WIDTH}x{W_HEIGHT}+{x}+{y}")

    # ---------- 버튼 헬퍼 ----------
    def _txt(self, parent, text, cmd, font=None, fg=None, hi=None, bg=None):
        font = font or self.f_ctrl
        fg = fg or C["btn"]
        hi = hi or C["btn_hi"]
        bg = bg or C["bg"]
        b = tk.Label(parent, text=text, font=font, bg=bg, fg=fg, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=hi))
        b.bind("<Leave>", lambda e: b.configure(fg=fg))
        return b

    def _solid(self, parent, text, cmd):
        b = tk.Label(parent, text=text, font=self.f_act, bg=C["accent"],
                     fg="#ffffff", cursor="hand2", padx=11, pady=3)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=C["accent_dk"]))
        b.bind("<Leave>", lambda e: b.configure(bg=C["accent"]))
        return b

    # ---------- UI ----------
    def _build(self):
        outer = tk.Frame(self.root, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(outer, bg=C["bg"])
        header.pack(fill="x")
        self.header = header

        row1 = tk.Frame(header, bg=C["bg"])
        row1.pack(fill="x", padx=14, pady=(11, 5))
        tk.Label(row1, text="주간 일정", font=self.f_title,
                 bg=C["bg"], fg=C["title"]).pack(side="left")
        self._txt(row1, "✕", self.quit).pack(side="right", padx=(12, 0))
        self._txt(row1, "—", self.toggle_collapse).pack(side="right", padx=(12, 0))
        self.btn_pin = self._txt(row1, "고정", self.toggle_topmost,
                                 fg=C["accent"] if self.topmost else C["btn"],
                                 hi=C["accent_dk"])
        self.btn_pin.pack(side="right")

        row2 = tk.Frame(header, bg=C["bg"])
        row2.pack(fill="x", padx=14, pady=(0, 11))
        self._txt(row2, "‹", lambda: self.shift_week(-1), font=self.f_nav,
                  fg=C["sub"], hi=C["accent"]).pack(side="left")
        self.lbl_week = tk.Label(row2, text="", font=self.f_sub,
                                 bg=C["bg"], fg=C["sub"])
        self.lbl_week.pack(side="left", padx=6)
        self._txt(row2, "›", lambda: self.shift_week(1), font=self.f_nav,
                  fg=C["sub"], hi=C["accent"]).pack(side="left")

        self._solid(row2, "오늘", self.goto_today).pack(side="right")
        self._txt(row2, "새로고침", lambda: self.check_update(manual=True),
                  font=self.f_act, fg=C["sub"], hi=C["accent"]).pack(
                  side="right", padx=(0, 12))
        self._txt(row2, "가져오기", self.open_import, font=self.f_act,
                  fg=C["accent"], hi=C["accent_dk"]).pack(side="right", padx=(0, 12))

        for w in (header, row1, row2):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        tk.Frame(outer, bg=C["sep"], height=1).pack(fill="x")

        self.body_wrap = tk.Frame(outer, bg=C["bg"])
        self.body_wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.body_wrap, bg=C["bg"], highlightthickness=0, bd=0)
        self.scroll = tk.Scrollbar(self.body_wrap, orient="vertical",
                                   command=self.canvas.yview, width=8)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=C["bg"])
        self._body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(
            self._body_id, width=e.width))

        self.collapsed = False
        if self.data["window"].get("collapsed"):
            self.toggle_collapse()

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
        ws = self.week_start
        for i in range(7):
            day = ws + dt.timedelta(days=i)
            self._render_day(day, i, is_today=(day == today))
        tk.Frame(self.body, bg=C["bg"], height=8).pack()
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(0)

    def _render_day(self, day, idx, is_today):
        items = self.data["items"].get(iso(day), [])
        bg = C["today_bg"] if is_today else C["bg"]

        block = tk.Frame(self.body, bg=bg)
        block.pack(fill="x")
        tk.Frame(block, bg=C["accent"] if is_today else bg, width=3).pack(
            side="left", fill="y")
        inner = tk.Frame(block, bg=bg)
        inner.pack(side="left", fill="both", expand=True)

        head = tk.Frame(inner, bg=bg)
        head.pack(fill="x", padx=11, pady=(6, 3) if items else 5)

        if is_today:
            cbg, cfg = C["accent"], "#ffffff"
        elif idx == 5:
            cbg, cfg = C["sat_bg"], C["sat_fg"]
        elif idx == 6:
            cbg, cfg = C["sun_bg"], C["sun_fg"]
        else:
            cbg, cfg = C["chip_bg"], C["chip_fg"]
        tk.Label(head, text=f" {WEEKDAYS_KR[idx]} ", font=self.f_chip,
                 bg=cbg, fg=cfg, padx=3, pady=1).pack(side="left")
        tk.Label(head, text=day.strftime("%m/%d"), font=self.f_date,
                 bg=bg, fg=C["sub"] if items else C["muted"]).pack(
                 side="left", padx=(8, 0))
        self._txt(head, "＋", lambda d=day: self.add_item(d), font=self.f_add,
                  fg=C["muted"], hi=C["accent"], bg=bg).pack(side="right")

        for it in items:
            self._render_item(inner, bg, day, it)
        if items:
            tk.Frame(inner, bg=bg, height=6).pack()

        tk.Frame(self.body, bg=C["sep"], height=1).pack(fill="x", padx=11)

    def _render_item(self, parent, bg, day, it):
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", padx=13, pady=1)

        color = self._cat_color(it.get("category"))
        done = it.get("done", False)

        dot = tk.Canvas(row, width=9, height=18, bg=bg, highlightthickness=0)
        dot.create_oval(1, 7, 8, 14, fill=color, outline=color)
        dot.pack(side="left", padx=(0, 5))

        chk = tk.Label(row, text=("☑" if done else "☐"), font=self.f_item,
                       bg=bg, fg=(C["done"] if done else C["sub"]), cursor="hand2")
        chk.pack(side="left")
        chk.bind("<Button-1>", lambda e, d=day, i=it: self.toggle_done(d, i))

        fnt = self.f_item_done if done else self.f_item
        fg = C["done"] if done else C["text"]
        txt = tk.Label(row, text=it.get("text", ""), font=fnt, bg=bg, fg=fg,
                       cursor="hand2", anchor="w", justify="left",
                       wraplength=W_WIDTH - 85)
        txt.pack(side="left", fill="x", expand=True, padx=(5, 0))
        txt.bind("<Button-1>", lambda e, d=day, i=it: self.edit_item(d, i))

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
        if self.collapsed:
            self.body_wrap.pack_forget()
            self.root.geometry(f"{W_WIDTH}x{self.header.winfo_reqheight()+3}"
                               f"+{self.root.winfo_x()}+{self.root.winfo_y()}")
        else:
            self.body_wrap.pack(fill="both", expand=True)
            self.root.geometry(f"{W_WIDTH}x{W_HEIGHT}"
                               f"+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.data["window"]["collapsed"] = self.collapsed
        self._persist()

    # ---------- 가져오기 ----------
    def open_import(self):
        ImportDialog(self)

    def apply_import(self, text):
        inweek, outside = plan_import(text, self.week_start)
        if not inweek:
            self._toast(f"이번 주 밖 {outside}개뿐 — 주 이동 후 재시도" if outside
                        else "인식된 항목이 없습니다", ms=3500)
            return False
        self._ensure_categories([c for _, _, c in inweek])
        for i in range(7):
            self.data["items"].pop(iso(self.week_start + dt.timedelta(days=i)), None)
        for date, t, c in inweek:
            self.data["items"].setdefault(iso(date), []).append(
                {"id": uuid.uuid4().hex, "text": t, "category": c, "done": False})
        self._persist()
        self.render()
        msg = f"{len(inweek)}개 가져옴"
        if outside:
            msg += f" · 이번 주 밖 {outside}개 제외"
        self._toast(msg, ms=3500)
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

    # ---------- 자동 업데이트 ----------
    def check_update(self, manual=False):
        if self._updating:
            return
        self._updating = True
        if manual:
            self._toast("업데이트 확인 중…")
        threading.Thread(target=self._update_worker, args=(manual,),
                         daemon=True).start()

    def _update_worker(self, manual):
        result = self._do_update()
        self.root.after(0, lambda: self._after_update(result, manual))

    def _do_update(self):
        top = run_git(["rev-parse", "--is-inside-work-tree"])
        if top is None or top.returncode != 0:
            return "no_git"
        up = run_git(["rev-parse", "--abbrev-ref", "@{u}"])
        if up is None or up.returncode != 0:
            return "no_remote"
        if run_git(["fetch", "--quiet"]) is None:
            return "error"
        local = run_git(["rev-parse", "HEAD"])
        remote = run_git(["rev-parse", "@{u}"])
        if (local is None or remote is None
                or local.returncode != 0 or remote.returncode != 0):
            return "error"
        if local.stdout.strip() == remote.stdout.strip():
            return "latest"
        pull = run_git(["pull", "--ff-only", "--quiet"])
        return "updated" if (pull and pull.returncode == 0) else "conflict"

    def _after_update(self, result, manual):
        self._updating = False
        if result == "updated":
            self._toast("업데이트 완료 · 재시작 중…")
            self.root.after(900, self._restart)
            return
        if not manual:
            return
        msgs = {"latest": "최신 상태입니다",
                "no_git": "git 미설치 / 저장소 아님",
                "no_remote": "원격 저장소 미설정",
                "conflict": "충돌로 업데이트 실패",
                "error": "업데이트 확인 실패 (네트워크?)"}
        self._toast(msgs.get(result, "업데이트 확인 실패"))

    def _toast(self, msg, ms=2600):
        self.lbl_week.configure(text=msg)
        if self._toast_job:
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(
            ms, lambda: self.lbl_week.configure(text=self._week_range_text()))

    def _restart(self):
        self._persist()
        try:
            subprocess.Popen([sys.executable, os.path.abspath(__file__)], cwd=APP_DIR,
                             creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW)
        except Exception:
            pass
        self.root.destroy()

    # ---------- 드래그 / 저장 ----------
    def _drag_start(self, e):
        self._drag["x"] = e.x_root - self.root.winfo_x()
        self._drag["y"] = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._drag['x']}+{e.y_root - self._drag['y']}")

    def _drag_end(self, e):
        self.data["window"]["x"] = self.root.winfo_x()
        self.data["window"]["y"] = self.root.winfo_y()
        self._persist()

    def _on_wheel(self, e):
        if not getattr(self, "collapsed", False):
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
# 공통: 프레임리스 모달
# ------------------------------------------------------------------
def _modal(app, width):
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
             fg="#ffffff").pack(side="left", padx=14, pady=8)
    return head


# ------------------------------------------------------------------
# 가져오기 대화상자 (붙여넣기 + 미리보기)
# ------------------------------------------------------------------
class ImportDialog:
    def __init__(self, app):
        self.app = app
        top, wrap = _modal(app, 360)
        self.top = top

        ws = app.week_start
        we = ws + dt.timedelta(days=6)
        _accent_head(wrap, app, f"가져오기 · {ws.strftime('%m/%d')}~{we.strftime('%m/%d')} 주")

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=14, pady=12)

        tk.Label(inner, text="Sticky Notes 내용을 복사해 아래에 붙여넣으세요 (Ctrl+V)",
                 font=app.f_act, bg=C["bg"], fg=C["sub"]).pack(anchor="w")

        self.text = tk.Text(inner, height=7, width=40, font=app.f_item, wrap="word",
                            relief="solid", bd=1, highlightthickness=1,
                            highlightbackground=C["field_bd"],
                            highlightcolor=C["accent"], padx=6, pady=5)
        self.text.pack(fill="x", pady=(5, 8))
        self.text.bind("<KeyRelease>", lambda e: self._refresh())
        self.text.bind("<<Paste>>", lambda e: self.top.after(20, self._refresh))

        tk.Label(inner, text="인식된 항목", font=app.f_act, bg=C["bg"],
                 fg=C["sub"]).pack(anchor="w")
        self.preview = tk.Text(inner, height=8, width=40, font=app.f_act, wrap="word",
                              relief="flat", bd=0, bg=C["today_bg"],
                              state="disabled", padx=8, pady=6)
        self.preview.pack(fill="x", pady=(4, 10))

        btns = tk.Frame(inner, bg=C["bg"])
        btns.pack(fill="x")
        self._b(btns, "취소", self._close, C["chip_bg"], C["text"]).pack(side="right", padx=(6, 0))
        self.apply_btn = self._b(btns, "적용", self._apply, C["accent"], "#ffffff")
        self.apply_btn.pack(side="right")

        top.update_idletasks()
        w, h = 340, top.winfo_reqheight()
        px = app.root.winfo_x() + (W_WIDTH - w) // 2
        py = max(40, app.root.winfo_y() + 60)
        top.geometry(f"{w}x{h}+{px}+{py}")

        # 클립보드 자동 채우기
        try:
            clip = app.root.clipboard_get()
        except Exception:
            clip = ""
        if clip and clip.strip():
            self.text.insert("1.0", clip)
        self.text.focus_set()
        self._refresh()
        top.bind("<Escape>", lambda e: self._close())

    def _b(self, parent, text, cmd, bg, fg):
        b = tk.Label(parent, text=text, font=self.app.f_date, bg=bg, fg=fg,
                     padx=16, pady=6, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def _refresh(self):
        text = self.text.get("1.0", "end")
        inweek, outside = plan_import(text, self.app.week_start)
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        if not inweek and not outside:
            self.preview.insert("end", "아직 인식된 항목이 없습니다.\n"
                                "형식 예:  <수요일> / • 할 일 / [혜윰, 11/29]")
        else:
            for date, t, c in inweek:
                wd = WEEKDAYS_KR[date.weekday()]
                line = t if len(t) <= 26 else t[:25] + "…"
                self.preview.insert("end", f"{wd} {date.strftime('%m/%d')}  {line}\n")
            if outside:
                self.preview.insert("end", f"\n(이번 주 밖 {outside}개는 제외됩니다)")
            if not inweek and outside:
                self.preview.insert("1.0", "이번 주에 들어갈 항목이 없습니다.\n"
                                    "주를 이동한 뒤 다시 적용하세요.\n\n")
        self.preview.configure(state="disabled")
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
# 항목 추가/편집 대화상자
# ------------------------------------------------------------------
class ItemDialog:
    def __init__(self, app, day, item):
        self.app, self.day, self.item = app, day, item
        top, wrap = _modal(app, 320)
        self.top = top

        title = "일정 편집" if item else "일정 추가"
        _accent_head(wrap, app, f"{title} · {day.strftime('%m/%d')} "
                     f"({WEEKDAYS_KR[day.weekday()]})")

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=16, pady=14)

        tk.Label(inner, text="할 일", font=app.f_act, bg=C["bg"],
                 fg=C["sub"]).pack(anchor="w")
        self.entry = tk.Entry(inner, font=app.f_item, relief="solid", bd=1,
                              highlightthickness=1, highlightbackground=C["field_bd"],
                              highlightcolor=C["accent"])
        self.entry.pack(fill="x", pady=(4, 12), ipady=5)
        self.entry.insert(0, item.get("text", "") if item else "")

        tk.Label(inner, text="카테고리", font=app.f_act, bg=C["bg"],
                 fg=C["sub"]).pack(anchor="w")
        cat_frame = tk.Frame(inner, bg=C["bg"])
        cat_frame.pack(fill="x", pady=(6, 14))
        cur = item.get("category") if item else app.data["categories"][0]["name"]
        self.cat_var = tk.StringVar(value=cur)
        self.cat_btns = {}
        row = tk.Frame(cat_frame, bg=C["bg"])
        row.pack(fill="x")
        for i, c in enumerate(app.data["categories"]):
            if i and i % 4 == 0:
                row = tk.Frame(cat_frame, bg=C["bg"])
                row.pack(fill="x", pady=(5, 0))
            b = tk.Label(row, text=c["name"], font=app.f_act, bg=C["chip_bg"],
                         fg=C["text"], padx=9, pady=4, cursor="hand2",
                         highlightthickness=2, highlightbackground=C["chip_bg"])
            b.pack(side="left", padx=(0, 5))
            b.bind("<Button-1>", lambda e, n=c["name"]: self._pick(n))
            self.cat_btns[c["name"]] = (b, c["color"])
        self._pick(cur)

        btns = tk.Frame(inner, bg=C["bg"])
        btns.pack(fill="x")
        if item:
            self._b(btns, "삭제", self._delete, C["danger_bg"],
                    C["danger_fg"]).pack(side="left")
        self._b(btns, "취소", self._cancel, C["chip_bg"], C["text"]).pack(side="right", padx=(6, 0))
        self._b(btns, "저장", self._save, C["accent"], "#ffffff").pack(side="right")

        top.update_idletasks()
        w, h = 320, top.winfo_reqheight()
        px = app.root.winfo_x() + (W_WIDTH - w) // 2
        py = app.root.winfo_y() + 110
        top.geometry(f"{w}x{h}+{px}+{py}")
        self.entry.focus_set()
        top.bind("<Return>", lambda e: self._save())
        top.bind("<Escape>", lambda e: self._cancel())

    def _b(self, parent, text, cmd, bg, fg):
        b = tk.Label(parent, text=text, font=self.app.f_date, bg=bg, fg=fg,
                     padx=16, pady=6, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def _pick(self, name):
        self.cat_var.set(name)
        for n, (b, color) in self.cat_btns.items():
            if n == name:
                b.configure(bg=color, fg="#ffffff", highlightbackground=color)
            else:
                b.configure(bg=C["chip_bg"], fg=C["text"], highlightbackground=C["chip_bg"])

    def _save(self):
        text = self.entry.get().strip()
        if not text:
            self.entry.configure(highlightbackground=C["danger_fg"])
            return
        self.app.save_item(self.day, self.item, text, self.cat_var.get())
        self._close()

    def _delete(self):
        if self.item:
            self.app.delete_item(self.day, self.item)
        self._close()

    def _cancel(self):
        self._close()

    def _close(self):
        try:
            self.top.grab_release()
        except Exception:
            pass
        self.top.destroy()


def main():
    root = tk.Tk()
    root.title("주간 일정")
    ScheduleWidget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
