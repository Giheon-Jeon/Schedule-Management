# -*- coding: utf-8 -*-
"""
주간 일정 위젯 (Weekly Schedule Widget)
- 바탕화면 우측 하단에 작게 상주하는 주간(월~일) 일정 보기/편집 위젯
- 데이터는 로컬 JSON 파일에 자동 저장
- Sticky Notes 메모 텍스트 붙여넣기 가져오기 + 깃허브 자동 업데이트 지원
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
from tkinter import messagebox

# ------------------------------------------------------------------
# 경로 / 데이터
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
W_WIDTH = 360
W_HEIGHT = 560

# ------------------------------------------------------------------
# 테마 (라이트, 이모지 없이 안전한 글리프만 사용)
# ------------------------------------------------------------------
C = {
    "frame":     "#cdd5e3",   # 바깥 테두리
    "bg":        "#ffffff",
    "header":    "#ffffff",
    "sep":       "#eef1f6",
    "title":     "#0f172a",
    "sub":       "#64748b",
    "muted":     "#9aa6b6",
    "text":      "#1f2937",
    "accent":    "#6366f1",
    "accent_dk": "#4f46e5",
    "accent_bg": "#eef2ff",
    "today_bg":  "#f6f7ff",
    "chip_bg":   "#f1f5f9",
    "chip_fg":   "#64748b",
    "done":      "#c3cbd8",
    "btn":       "#64748b",
    "btn_hi":    "#0f172a",
    "pill_bd":   "#e2e8f0",
    "sat_bg":    "#e4edff", "sat_fg": "#2563eb",
    "sun_bg":    "#ffe4e6", "sun_fg": "#dc2626",
    "danger_bg": "#fee2e2", "danger_fg": "#dc2626",
}


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
# Sticky Notes 텍스트 파서
# ------------------------------------------------------------------
_RE_SECTION = re.compile(r"^=+\s*\[(.+?)\]\s*=+$")
_RE_WEEKDAY = re.compile(r"^<\s*([월화수목금토일])\s*요일\s*>$")
_RE_DATED = re.compile(r"^\[(.+?)\]$")
_RE_MMDD = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")
_RE_BULLET = re.compile(r"^[•·‣◦\-\*]\s*(.*)$")


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
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            cur_date = None
            continue
        m = _RE_SECTION.match(line)
        if m:
            section, weekday, cur_date = m.group(1).strip(), None, None
            continue
        m = _RE_WEEKDAY.match(line)
        if m:
            weekday, cur_date = WEEKDAY_IDX[m.group(1)], None
            continue
        m = _RE_DATED.match(line)
        if m:
            inside = m.group(1)
            group_label = inside.split(",")[0].strip()
            dm = _RE_MMDD.search(inside)
            cur_date = _make_date(int(dm.group(1)), int(dm.group(2))) if dm else None
            weekday = None
            continue
        m = _RE_BULLET.match(line)
        if not m:
            continue
        txt = m.group(1).strip()
        if not txt or txt in ("-", "–", "—"):
            continue
        cat = section or "기타"
        if weekday is not None:
            weekday_entries.append((weekday, txt, cat))
        elif cur_date is not None:
            full = f"{group_label}: {txt}" if group_label else txt
            dated_entries.append((cur_date, full, cat))
    return weekday_entries, dated_entries


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

    # ---------- 폰트 ----------
    def _init_fonts(self):
        self.f_title = tkfont.Font(family=FONT, size=12, weight="bold")
        self.f_sub = tkfont.Font(family=FONT, size=9)
        self.f_ctrl = tkfont.Font(family=FONT, size=9)
        self.f_nav = tkfont.Font(family=FONT, size=12, weight="bold")
        self.f_chip = tkfont.Font(family=FONT, size=9, weight="bold")
        self.f_date = tkfont.Font(family=FONT, size=9, weight="bold")
        self.f_add = tkfont.Font(family=FONT, size=8, weight="bold")
        self.f_item = tkfont.Font(family=FONT, size=10)
        self.f_item_done = tkfont.Font(family=FONT, size=10, overstrike=1)
        self.f_empty = tkfont.Font(family=FONT, size=8)

    # ---------- 창 위치 ----------
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
    def _btn(self, parent, text, cmd, font, fg, hover, bg):
        b = tk.Label(parent, text=text, font=font, bg=bg, fg=fg, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=hover))
        b.bind("<Leave>", lambda e: b.configure(fg=fg))
        return b

    def _pill(self, parent, text, cmd):
        b = tk.Label(parent, text=text, font=self.f_add, bg=C["bg"],
                     fg=C["sub"], cursor="hand2", padx=9, pady=3,
                     highlightthickness=1, highlightbackground=C["pill_bd"])
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg=C["accent_dk"],
                                                highlightbackground=C["accent"]))
        b.bind("<Leave>", lambda e: b.configure(fg=C["sub"],
                                                highlightbackground=C["pill_bd"]))
        return b

    # ---------- UI 구성 ----------
    def _build(self):
        outer = tk.Frame(self.root, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(outer, bg=C["header"])
        header.pack(fill="x")
        self.header = header

        # 1행: 제목 + 창 컨트롤
        row1 = tk.Frame(header, bg=C["header"])
        row1.pack(fill="x", padx=14, pady=(11, 4))
        tk.Label(row1, text="주간 일정", font=self.f_title,
                 bg=C["header"], fg=C["title"]).pack(side="left")

        self._btn(row1, "✕", self.quit, self.f_ctrl, C["btn"], C["btn_hi"],
                  C["header"]).pack(side="right", padx=(10, 0))
        self._btn(row1, "—", self.toggle_collapse, self.f_ctrl, C["btn"],
                  C["btn_hi"], C["header"]).pack(side="right", padx=(10, 0))
        self.btn_pin = self._btn(row1, "고정", self.toggle_topmost, self.f_ctrl,
                                 C["accent"] if self.topmost else C["btn"],
                                 C["accent_dk"], C["header"])
        self.btn_pin.pack(side="right")

        # 2행: 주 이동 + 액션
        row2 = tk.Frame(header, bg=C["header"])
        row2.pack(fill="x", padx=14, pady=(0, 11))
        self._btn(row2, "‹", lambda: self.shift_week(-1), self.f_nav, C["sub"],
                  C["accent"], C["header"]).pack(side="left")
        self.lbl_week = tk.Label(row2, text="", font=self.f_sub,
                                 bg=C["header"], fg=C["sub"])
        self.lbl_week.pack(side="left", padx=7)
        self._btn(row2, "›", lambda: self.shift_week(1), self.f_nav, C["sub"],
                  C["accent"], C["header"]).pack(side="left")

        self._pill(row2, "오늘", self.goto_today).pack(side="right")
        self._pill(row2, "새로고침", lambda: self.check_update(manual=True)
                   ).pack(side="right", padx=(0, 6))
        self._pill(row2, "가져오기", self.import_clipboard
                   ).pack(side="right", padx=(0, 6))

        # 드래그로 이동
        for w in (header, row1, row2):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        tk.Frame(outer, bg=C["sep"], height=1).pack(fill="x")

        # 본문 (스크롤)
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
            self._render_day(day, i, is_today=(day == today), first=(i == 0))
        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(0)

    def _render_day(self, day, idx, is_today, first):
        bg = C["today_bg"] if is_today else C["bg"]
        block = tk.Frame(self.body, bg=bg)
        block.pack(fill="x")

        # 오늘 강조용 좌측 액센트 바
        bar = tk.Frame(block, bg=C["accent"] if is_today else bg, width=3)
        bar.pack(side="left", fill="y")

        inner = tk.Frame(block, bg=bg)
        inner.pack(side="left", fill="both", expand=True)

        # 날짜 헤더
        head = tk.Frame(inner, bg=bg)
        head.pack(fill="x", padx=12, pady=(10, 4))

        if is_today:
            chip_bg, chip_fg = C["accent"], "#ffffff"
        elif idx == 5:
            chip_bg, chip_fg = C["sat_bg"], C["sat_fg"]
        elif idx == 6:
            chip_bg, chip_fg = C["sun_bg"], C["sun_fg"]
        else:
            chip_bg, chip_fg = C["chip_bg"], C["chip_fg"]
        tk.Label(head, text=f" {WEEKDAYS_KR[idx]} ", font=self.f_chip,
                 bg=chip_bg, fg=chip_fg, padx=4, pady=1).pack(side="left")
        tk.Label(head, text=day.strftime("%m/%d"), font=self.f_date,
                 bg=bg, fg=C["sub"]).pack(side="left", padx=(8, 0))

        add = self._btn(head, "＋ 추가", lambda d=day: self.add_item(d),
                        self.f_add, C["muted"], C["accent"], bg)
        add.pack(side="right")

        items = self.data["items"].get(iso(day), [])
        if not items:
            tk.Label(inner, text="일정 없음", font=self.f_empty, bg=bg,
                     fg=C["muted"]).pack(anchor="w", padx=16, pady=(0, 9))
        else:
            for it in items:
                self._render_item(inner, bg, day, it)
            tk.Frame(inner, bg=bg, height=7).pack()

        tk.Frame(self.body, bg=C["sep"], height=1).pack(fill="x", padx=12)

    def _render_item(self, parent, bg, day, it):
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", padx=14, pady=2)

        color = self._cat_color(it.get("category"))
        done = it.get("done", False)

        dot = tk.Canvas(row, width=10, height=18, bg=bg, highlightthickness=0)
        dot.create_oval(1, 7, 9, 15, fill=color, outline=color)
        dot.pack(side="left", padx=(0, 6))

        chk = tk.Label(row, text=("☑" if done else "☐"), font=self.f_item,
                       bg=bg, fg=(C["done"] if done else C["sub"]), cursor="hand2")
        chk.pack(side="left")
        chk.bind("<Button-1>", lambda e, d=day, i=it: self.toggle_done(d, i))

        fnt = self.f_item_done if done else self.f_item
        fg = C["done"] if done else C["text"]
        txt = tk.Label(row, text=it.get("text", ""), font=fnt, bg=bg, fg=fg,
                       cursor="hand2", anchor="w", justify="left",
                       wraplength=W_WIDTH - 95)
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

    # ---------- Sticky Notes 가져오기 ----------
    def import_clipboard(self):
        try:
            text = self.root.clipboard_get()
        except Exception:
            text = ""
        if not text or not text.strip():
            self._toast("클립보드가 비어 있습니다")
            return
        self.import_from_text(text)

    def import_from_text(self, text):
        weekday_entries, dated_entries = parse_sticky_note(text)
        ws = self.week_start
        week_dates = [ws + dt.timedelta(days=i) for i in range(7)]
        week_set = {iso(d) for d in week_dates}

        new_by_date, cats, outside = {}, [], 0
        for widx, txt, cat in weekday_entries:
            new_by_date.setdefault(iso(ws + dt.timedelta(days=widx)), []).append((txt, cat))
            cats.append(cat)
        for date, txt, cat in dated_entries:
            if iso(date) in week_set:
                new_by_date.setdefault(iso(date), []).append((txt, cat))
                cats.append(cat)
            else:
                outside += 1

        count = sum(len(v) for v in new_by_date.values())
        if count == 0:
            self._toast("이번 주 밖 항목뿐 — 주 이동 후 재시도" if outside
                        else "가져올 항목이 없습니다", ms=3500)
            return

        existing = sum(len(self.data["items"].get(iso(d), [])) for d in week_dates)
        if existing:
            ok = messagebox.askyesno(
                "일정 가져오기",
                f"이번 주({ws.strftime('%m/%d')}~{week_dates[-1].strftime('%m/%d')}) "
                f"기존 {existing}개를 메모 {count}개로 교체할까요?",
                parent=self.root)
            if not ok:
                return

        self._ensure_categories(cats)
        for d in week_dates:
            self.data["items"].pop(iso(d), None)
        for key, lst in new_by_date.items():
            self.data["items"][key] = [
                {"id": uuid.uuid4().hex, "text": t, "category": c, "done": False}
                for t, c in lst]
        self._persist()
        self.render()
        msg = f"{count}개 가져옴"
        if outside:
            msg += f" · 이번 주 밖 {outside}개 제외"
        self._toast(msg, ms=3500)

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

    # ---------- 드래그 ----------
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
# 항목 추가/편집 대화상자
# ------------------------------------------------------------------
class ItemDialog:
    def __init__(self, app, day, item):
        self.app, self.day, self.item = app, day, item
        top = tk.Toplevel(app.root)
        self.top = top
        top.overrideredirect(True)
        top.configure(bg=C["frame"])
        top.attributes("-topmost", True)
        top.grab_set()

        wrap = tk.Frame(top, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(wrap, bg=C["accent"])
        head.pack(fill="x")
        title = "일정 편집" if item else "일정 추가"
        tk.Label(head, text=f"{title}   {day.strftime('%m/%d')} "
                 f"({WEEKDAYS_KR[day.weekday()]})", font=app.f_date,
                 bg=C["accent"], fg="#ffffff").pack(side="left", padx=14, pady=8)

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=16, pady=14)

        tk.Label(inner, text="할 일", font=app.f_add, bg=C["bg"],
                 fg=C["sub"]).pack(anchor="w")
        self.entry = tk.Entry(inner, font=app.f_item, relief="solid", bd=1,
                              highlightthickness=1, highlightbackground=C["pill_bd"],
                              highlightcolor=C["accent"])
        self.entry.pack(fill="x", pady=(4, 12), ipady=5)
        self.entry.insert(0, item.get("text", "") if item else "")

        tk.Label(inner, text="카테고리", font=app.f_add, bg=C["bg"],
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
            b = tk.Label(row, text=c["name"], font=app.f_add, bg=C["chip_bg"],
                         fg=C["text"], padx=9, pady=4, cursor="hand2",
                         highlightthickness=2, highlightbackground=C["chip_bg"])
            b.pack(side="left", padx=(0, 5))
            b.bind("<Button-1>", lambda e, n=c["name"]: self._pick(n))
            self.cat_btns[c["name"]] = (b, c["color"])
        self._pick(cur)

        btns = tk.Frame(inner, bg=C["bg"])
        btns.pack(fill="x")
        if item:
            self._dbtn(btns, "삭제", self._delete, C["danger_bg"],
                       C["danger_fg"]).pack(side="left")
        self._dbtn(btns, "취소", self._cancel, C["chip_bg"],
                   C["text"]).pack(side="right", padx=(6, 0))
        self._dbtn(btns, "저장", self._save, C["accent"], "#ffffff").pack(side="right")

        top.update_idletasks()
        w, h = 320, top.winfo_reqheight()
        px = app.root.winfo_x() + (W_WIDTH - w) // 2
        py = app.root.winfo_y() + 110
        top.geometry(f"{w}x{h}+{px}+{py}")
        self.entry.focus_set()
        top.bind("<Return>", lambda e: self._save())
        top.bind("<Escape>", lambda e: self._cancel())

    def _dbtn(self, parent, text, cmd, bg, fg):
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
