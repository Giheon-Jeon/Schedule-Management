# -*- coding: utf-8 -*-
"""
주간 일정 위젯 (Weekly Schedule Widget)
- 바탕화면 우측 하단에 작게 상주하는 주간(월~일) 일정 보기/편집 위젯
- 데이터는 로컬 JSON 파일에 자동 저장
- 추가 설치 없이 Python 내장 Tkinter 로만 동작 (가벼움)
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

# subprocess 플래그 (pythonw 실행 시 콘솔 창이 깜빡이지 않도록)
if os.name == "nt":
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
else:
    CREATE_NO_WINDOW = 0
    DETACHED_PROCESS = 0


def run_git(args, timeout=30):
    """git 명령 실행. 실패/미설치 시 None 반환."""
    try:
        return subprocess.run(
            ["git"] + args, cwd=APP_DIR, capture_output=True, text=True,
            timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        return None
DATA_DIR = os.path.join(APP_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "schedule.json")

DEFAULT_CATEGORIES = [
    {"name": "공부", "color": "#3b82f6"},
    {"name": "업무", "color": "#22c55e"},
    {"name": "개인", "color": "#f59e0b"},
    {"name": "운동", "color": "#ef4444"},
    {"name": "기타", "color": "#94a3b8"},
]

WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]
WEEKDAY_IDX = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

# 새 카테고리에 자동 배정할 색상 팔레트
IMPORT_PALETTE = [
    "#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
    "#ec4899", "#14b8a6", "#f97316", "#0ea5e9", "#64748b",
]

_RE_SECTION = re.compile(r"^=+\s*\[(.+?)\]\s*=+$")
_RE_WEEKDAY = re.compile(r"^<\s*([월화수목금토일])\s*요일\s*>$")
_RE_DATED = re.compile(r"^\[(.+?)\]$")
_RE_MMDD = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")
_RE_BULLET = re.compile(r"^[•·‣◦\-\*]\s*(.*)$")


def _make_date(mm, dd):
    """MM/DD 를 오늘과 가까운 연도의 날짜로 변환."""
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
    """Sticky Notes 텍스트를 파싱.
    반환: (weekday_entries, dated_entries)
      weekday_entries: [(weekday_idx, text, category)]
      dated_entries:   [(date, text, category)]
    """
    weekday_entries = []
    dated_entries = []
    section = None          # 현재 섹션명(카테고리)
    weekday = None          # 현재 요일 index
    cur_date = None         # 현재 날짜 그룹
    group_label = None      # 날짜 그룹 라벨(예: 혜윰, MJSEC)

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            cur_date = None     # 빈 줄은 날짜 그룹만 종료(요일은 유지)
            continue

        m = _RE_SECTION.match(line)
        if m:
            section = m.group(1).strip()
            weekday = None
            cur_date = None
            continue

        m = _RE_WEEKDAY.match(line)
        if m:
            weekday = WEEKDAY_IDX[m.group(1)]
            cur_date = None
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
            continue            # 글머리표가 아닌 줄은 무시
        txt = m.group(1).strip()
        if not txt or txt in ("-", "–", "—"):
            continue            # "• -" 같은 빈 자리표시 무시

        cat = section or "기타"
        if weekday is not None:
            weekday_entries.append((weekday, txt, cat))
        elif cur_date is not None:
            full = f"{group_label}: {txt}" if group_label else txt
            dated_entries.append((cur_date, full, cat))

    return weekday_entries, dated_entries

# ------------------------------------------------------------------
# 테마
# ------------------------------------------------------------------
C = {
    "app_bg":     "#ffffff",
    "header_bg":  "#1e293b",
    "header_fg":  "#f8fafc",
    "header_sub": "#94a3b8",
    "btn_bg":     "#334155",
    "btn_fg":     "#e2e8f0",
    "day_bg":     "#f8fafc",
    "day_today":  "#eff6ff",
    "border":     "#e2e8f0",
    "text":       "#0f172a",
    "muted":      "#64748b",
    "done":       "#94a3b8",
    "add_fg":     "#3b82f6",
    "sat":        "#2563eb",
    "sun":        "#dc2626",
}

W_WIDTH = 360
W_HEIGHT = 540


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
    d.setdefault("items", {})          # {"YYYY-MM-DD": [ {id,text,category,done} ]}
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


# ------------------------------------------------------------------
# 메인 앱
# ------------------------------------------------------------------
class ScheduleWidget:
    def __init__(self, root):
        self.root = root
        self.data = load_data()
        self.week_start = monday_of(dt.date.today())
        self._drag = {"x": 0, "y": 0}

        root.overrideredirect(True)        # 프레임 없는 위젯 형태
        root.configure(bg=C["border"])
        self.topmost = bool(self.data["window"].get("topmost", False))
        root.attributes("-topmost", self.topmost)
        try:
            root.attributes("-alpha", 0.98)
        except Exception:
            pass

        self._place_window()
        self._init_fonts()
        self._build()
        self.render()

        root.bind("<MouseWheel>", self._on_wheel)
        root.protocol("WM_DELETE_WINDOW", self.quit)

        # 시작 후 조용히 깃허브 업데이트 확인 (창이 먼저 뜨도록 지연)
        root.after(1500, lambda: self.check_update(manual=False))

    # ---------- 폰트 ----------
    def _init_fonts(self):
        fam = "Malgun Gothic"
        self.f_title = tkfont.Font(family=fam, size=11, weight="bold")
        self.f_sub = tkfont.Font(family=fam, size=8)
        self.f_day = tkfont.Font(family=fam, size=9, weight="bold")
        self.f_item = tkfont.Font(family=fam, size=9)
        self.f_item_done = tkfont.Font(family=fam, size=9, overstrike=1)
        self.f_btn = tkfont.Font(family=fam, size=10, weight="bold")
        self.f_add = tkfont.Font(family=fam, size=8)

    # ---------- 창 위치 ----------
    def _place_window(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win = self.data["window"]
        x = win.get("x")
        y = win.get("y")
        if x is None or y is None:
            x = sw - W_WIDTH - 16
            y = sh - W_HEIGHT - 56     # 작업표시줄 여백
        # 화면 밖으로 사라지지 않도록 보정
        x = max(0, min(x, sw - 80))
        y = max(0, min(y, sh - 80))
        self.root.geometry(f"{W_WIDTH}x{W_HEIGHT}+{x}+{y}")

    # ---------- UI 구성 ----------
    def _build(self):
        outer = tk.Frame(self.root, bg=C["border"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        # 헤더 바
        header = tk.Frame(outer, bg=C["header_bg"])
        header.pack(fill="x")
        self.header = header

        bar = tk.Frame(header, bg=C["header_bg"])
        bar.pack(fill="x", padx=10, pady=(8, 2))

        self.lbl_title = tk.Label(bar, text="주간 일정", font=self.f_title,
                                  bg=C["header_bg"], fg=C["header_fg"])
        self.lbl_title.pack(side="left")

        # 오른쪽 상단 버튼들
        self._hbtn(bar, "✕", self.quit).pack(side="right")
        self.btn_pin = self._hbtn(bar, "📌", self.toggle_topmost)
        self.btn_pin.pack(side="right")
        self._hbtn(bar, "–", self.toggle_collapse).pack(side="right")
        self._hbtn(bar, "↻", lambda: self.check_update(manual=True)).pack(side="right")

        # 주 이동 바
        nav = tk.Frame(header, bg=C["header_bg"])
        nav.pack(fill="x", padx=10, pady=(0, 8))
        self._hbtn(nav, "‹", lambda: self.shift_week(-1)).pack(side="left")
        self.lbl_week = tk.Label(nav, text="", font=self.f_sub,
                                 bg=C["header_bg"], fg=C["header_sub"])
        self.lbl_week.pack(side="left", padx=6)
        self._hbtn(nav, "›", lambda: self.shift_week(1)).pack(side="left")
        self._hbtn(nav, "오늘", self.goto_today, wide=True).pack(side="right")
        self._hbtn(nav, "📋", self.import_clipboard).pack(side="right")

        # 헤더 드래그로 창 이동
        for w in (header, bar, nav, self.lbl_title):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        # 본문 (스크롤 가능)
        self.body_wrap = tk.Frame(outer, bg=C["app_bg"])
        self.body_wrap.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(self.body_wrap, bg=C["app_bg"],
                                highlightthickness=0, bd=0)
        self.scroll = tk.Scrollbar(self.body_wrap, orient="vertical",
                                   command=self.canvas.yview, width=8)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.body = tk.Frame(self.canvas, bg=C["app_bg"])
        self._body_id = self.canvas.create_window((0, 0), window=self.body,
                                                   anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(
            self._body_id, width=e.width))

        self.collapsed = False
        if self.data["window"].get("collapsed"):
            self.toggle_collapse()

    def _hbtn(self, parent, text, cmd, wide=False):
        b = tk.Label(parent, text=text, font=self.f_btn,
                     bg=C["header_bg"], fg=C["btn_fg"], cursor="hand2",
                     padx=(8 if wide else 5), pady=1)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(fg="#ffffff"))
        b.bind("<Leave>", lambda e: b.configure(fg=C["btn_fg"]))
        return b

    # ---------- 렌더링 ----------
    def _week_range_text(self):
        ws = self.week_start
        we = ws + dt.timedelta(days=6)
        return f"{ws.strftime('%Y.%m.%d')} ~ {we.strftime('%m.%d')}"

    def render(self):
        ws = self.week_start
        self.lbl_week.configure(text=self._week_range_text())

        for ch in self.body.winfo_children():
            ch.destroy()

        today = dt.date.today()
        for i in range(7):
            day = ws + dt.timedelta(days=i)
            self._render_day(day, i, is_today=(day == today))

        self.body.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _render_day(self, day, idx, is_today):
        bg = C["day_today"] if is_today else C["day_bg"]
        wrap = tk.Frame(self.body, bg=C["app_bg"])
        wrap.pack(fill="x", padx=8, pady=(6 if idx == 0 else 3, 0))

        card = tk.Frame(wrap, bg=bg, highlightbackground=C["border"],
                        highlightthickness=1)
        card.pack(fill="x")

        # 날짜 헤더
        head = tk.Frame(card, bg=bg)
        head.pack(fill="x", padx=8, pady=(5, 2))

        wd = WEEKDAYS_KR[idx]
        wd_color = C["sat"] if idx == 5 else (C["sun"] if idx == 6 else C["text"])
        tk.Label(head, text=wd, font=self.f_day, bg=bg, fg=wd_color).pack(side="left")
        tk.Label(head, text=day.strftime(" %m/%d"), font=self.f_day, bg=bg,
                 fg=C["muted"]).pack(side="left")
        if is_today:
            tk.Label(head, text="오늘", font=self.f_add, bg="#dbeafe",
                     fg="#1d4ed8", padx=4).pack(side="left", padx=6)

        add = tk.Label(head, text="＋ 추가", font=self.f_add, bg=bg,
                       fg=C["add_fg"], cursor="hand2")
        add.pack(side="right")
        add.bind("<Button-1>", lambda e, d=day: self.add_item(d))

        # 항목들
        items = self.data["items"].get(iso(day), [])
        if not items:
            tk.Label(card, text="일정 없음", font=self.f_add, bg=bg,
                     fg=C["muted"]).pack(anchor="w", padx=12, pady=(0, 6))
        else:
            for it in items:
                self._render_item(card, bg, day, it)
            tk.Frame(card, bg=bg, height=4).pack()

    def _render_item(self, parent, bg, day, it):
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", padx=10, pady=1)

        color = self._cat_color(it.get("category"))
        done = it.get("done", False)

        # 색상 점
        dot = tk.Canvas(row, width=10, height=10, bg=bg, highlightthickness=0)
        dot.create_oval(1, 1, 9, 9, fill=color, outline=color)
        dot.pack(side="left", padx=(0, 4))

        # 완료 체크
        chk = tk.Label(row, text=("☑" if done else "☐"), font=self.f_item,
                       bg=bg, fg=(C["done"] if done else C["text"]), cursor="hand2")
        chk.pack(side="left")
        chk.bind("<Button-1>", lambda e, d=day, i=it: self.toggle_done(d, i))

        # 텍스트 (클릭 시 편집)
        fnt = self.f_item_done if done else self.f_item
        fg = C["done"] if done else C["text"]
        txt = tk.Label(row, text=it.get("text", ""), font=fnt, bg=bg, fg=fg,
                       cursor="hand2", anchor="w", justify="left",
                       wraplength=W_WIDTH - 90)
        txt.pack(side="left", fill="x", expand=True, padx=(4, 0))
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
        key = iso(day)
        lst = self.data["items"].setdefault(key, [])
        if item is None:
            lst.append({"id": uuid.uuid4().hex, "text": text,
                        "category": category, "done": False})
        else:
            item["text"] = text
            item["category"] = category
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
        self.btn_pin.configure(fg="#ffffff" if self.topmost else C["btn_fg"])
        self.data["window"]["topmost"] = self.topmost
        self._persist()

    def toggle_collapse(self):
        self.collapsed = not getattr(self, "collapsed", False)
        if self.collapsed:
            self.body_wrap.pack_forget()
            self.root.geometry(f"{W_WIDTH}x{self.header.winfo_reqheight()+2}"
                               f"+{self.root.winfo_x()}+{self.root.winfo_y()}")
        else:
            self.body_wrap.pack(fill="both", expand=True)
            self.root.geometry(f"{W_WIDTH}x{W_HEIGHT}"
                               f"+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.data["window"]["collapsed"] = self.collapsed
        self._persist()

    # ---------- 드래그 ----------
    def _drag_start(self, e):
        self._drag["x"] = e.x_root - self.root.winfo_x()
        self._drag["y"] = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        x = e.x_root - self._drag["x"]
        y = e.y_root - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

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

        # 이번 주에 들어갈 항목 모으기
        new_by_date = {}   # iso -> [(text, cat)]
        cats = []
        outside = 0
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
            msg = "가져올 항목이 없습니다"
            if outside:
                msg = f"이번 주 밖 {outside}개뿐 — 주를 이동해 다시 시도"
            self._toast(msg, ms=3500)
            return

        # 기존 이번 주 항목이 있으면 덮어쓰기 확인
        existing = sum(len(self.data["items"].get(iso(d), [])) for d in week_dates)
        if existing:
            ok = messagebox.askyesno(
                "일정 가져오기",
                f"이번 주({ws.strftime('%m/%d')}~{week_dates[-1].strftime('%m/%d')}) "
                f"기존 항목 {existing}개를 메모 내용 {count}개로 교체할까요?",
                parent=self.root)
            if not ok:
                return

        self._ensure_categories(cats)

        # 이번 주 덮어쓰기
        for d in week_dates:
            self.data["items"].pop(iso(d), None)
        for key, lst in new_by_date.items():
            self.data["items"][key] = [
                {"id": uuid.uuid4().hex, "text": t, "category": c, "done": False}
                for t, c in lst
            ]

        self._persist()
        self.render()
        msg = f"{count}개 항목 가져옴"
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
        """깃허브 원격에 새 커밋이 있으면 pull 후 재시작. 백그라운드 스레드에서 실행."""
        if getattr(self, "_updating", False):
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
        # git 설치/저장소 여부 확인
        top = run_git(["rev-parse", "--is-inside-work-tree"])
        if top is None or top.returncode != 0:
            return "no_git"
        # 원격(upstream) 설정 확인
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
        if pull is not None and pull.returncode == 0:
            return "updated"
        return "conflict"

    def _after_update(self, result, manual):
        self._updating = False
        if result == "updated":
            self._toast("업데이트 완료 · 재시작 중…")
            self.root.after(900, self._restart)
            return
        if not manual:
            return  # 자동 확인은 조용히 (업데이트 없을 땐 아무 표시 안 함)
        msgs = {
            "latest":    "최신 상태입니다",
            "no_git":    "git 미설치 / 저장소 아님",
            "no_remote": "원격 저장소 미설정",
            "conflict":  "충돌로 업데이트 실패 (수동 확인 필요)",
            "error":     "업데이트 확인 실패 (네트워크?)",
        }
        self._toast(msgs.get(result, "업데이트 확인 실패"))

    def _toast(self, msg, ms=2600):
        self.lbl_week.configure(text=msg)
        if getattr(self, "_toast_job", None):
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(
            ms, lambda: self.lbl_week.configure(text=self._week_range_text()))

    def _restart(self):
        self._persist()
        try:
            subprocess.Popen(
                [sys.executable, os.path.abspath(__file__)], cwd=APP_DIR,
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW)
        except Exception:
            pass
        self.root.destroy()

    def quit(self):
        self._persist()
        self.root.destroy()


# ------------------------------------------------------------------
# 항목 추가/편집 대화상자
# ------------------------------------------------------------------
class ItemDialog:
    def __init__(self, app, day, item):
        self.app = app
        self.day = day
        self.item = item

        top = tk.Toplevel(app.root)
        self.top = top
        top.overrideredirect(True)
        top.configure(bg=C["border"])
        top.attributes("-topmost", True)
        top.grab_set()

        wrap = tk.Frame(top, bg=C["app_bg"])
        wrap.pack(fill="both", expand=True, padx=1, pady=1)

        title = "일정 편집" if item else "일정 추가"
        head = tk.Frame(wrap, bg=C["header_bg"])
        head.pack(fill="x")
        tk.Label(head, text=f"{title}  ·  {day.strftime('%m/%d')} "
                 f"({WEEKDAYS_KR[day.weekday()]})", font=app.f_day,
                 bg=C["header_bg"], fg=C["header_fg"]).pack(side="left",
                                                            padx=10, pady=6)

        inner = tk.Frame(wrap, bg=C["app_bg"])
        inner.pack(fill="both", expand=True, padx=12, pady=10)

        tk.Label(inner, text="할 일", font=app.f_add, bg=C["app_bg"],
                 fg=C["muted"]).pack(anchor="w")
        self.entry = tk.Entry(inner, font=app.f_item, relief="solid", bd=1)
        self.entry.pack(fill="x", pady=(2, 10), ipady=4)
        self.entry.insert(0, item.get("text", "") if item else "")

        tk.Label(inner, text="카테고리", font=app.f_add, bg=C["app_bg"],
                 fg=C["muted"]).pack(anchor="w")
        cat_frame = tk.Frame(inner, bg=C["app_bg"])
        cat_frame.pack(fill="x", pady=(4, 12))

        cur = item.get("category") if item else app.data["categories"][0]["name"]
        self.cat_var = tk.StringVar(value=cur)
        self.cat_btns = {}
        for c in app.data["categories"]:
            b = tk.Label(cat_frame, text=c["name"], font=app.f_add,
                         bg=C["day_bg"], fg=C["text"], padx=8, pady=3,
                         cursor="hand2", highlightthickness=2,
                         highlightbackground=C["day_bg"])
            b.pack(side="left", padx=(0, 5))
            b.bind("<Button-1>", lambda e, n=c["name"]: self._pick(n))
            self.cat_btns[c["name"]] = (b, c["color"])
        self._pick(cur)

        btns = tk.Frame(inner, bg=C["app_bg"])
        btns.pack(fill="x")
        if item:
            self._btn(btns, "삭제", self._delete, "#fee2e2", "#b91c1c").pack(side="left")
        self._btn(btns, "취소", self._cancel, C["day_bg"], C["text"]).pack(side="right", padx=(6, 0))
        self._btn(btns, "저장", self._save, "#3b82f6", "#ffffff").pack(side="right")

        # 가운데 배치
        top.update_idletasks()
        w, h = 320, top.winfo_reqheight()
        px = app.root.winfo_x() + (W_WIDTH - w) // 2
        py = app.root.winfo_y() + 120
        top.geometry(f"{w}x{h}+{px}+{py}")

        self.entry.focus_set()
        top.bind("<Return>", lambda e: self._save())
        top.bind("<Escape>", lambda e: self._cancel())

    def _btn(self, parent, text, cmd, bg, fg):
        b = tk.Label(parent, text=text, font=self.app.f_day, bg=bg, fg=fg,
                     padx=14, pady=5, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def _pick(self, name):
        self.cat_var.set(name)
        for n, (b, color) in self.cat_btns.items():
            if n == name:
                b.configure(bg=color, fg="#ffffff", highlightbackground=color)
            else:
                b.configure(bg=C["day_bg"], fg=C["text"],
                            highlightbackground=C["day_bg"])

    def _save(self):
        text = self.entry.get().strip()
        if not text:
            self.entry.configure(bg="#fee2e2")
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
