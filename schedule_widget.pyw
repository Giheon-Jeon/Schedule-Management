# -*- coding: utf-8 -*-
"""
주간 일정 위젯 (Weekly Schedule Widget)
- 바탕화면 우측 하단에 작게 상주하는 일정 위젯
  · 주간 탭: 월~일 일정 + 다가오는 일정(D-day)
  · 전체 탭: 날짜 없는 할 일 목록 (기말고사 준비, 종강 후 할 일 …)
- Sticky Notes 메모 가져오기 / 메모로 보내기 (같은 형식으로 왕복)
- 과목 태그([알고리즘] → 색 태그), 고해상도(DPI) 대응, 깃허브/로컬 변경 자동 반영
"""

import os
import re
import sys
import json
import time
import uuid
import zlib
import shutil
import ctypes
import ctypes.wintypes
import hashlib
import traceback
import threading
import subprocess
import datetime as dt
import tkinter as tk
from tkinter import font as tkfont

# ------------------------------------------------------------------
def _arg_value(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


# --app-dir: 비상용 이전 버전이 원래 폴더의 데이터를 쓰도록 할 때 사용
APP_DIR = os.path.abspath(_arg_value("--app-dir") or os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(APP_DIR, "schedule_widget.pyw")      # 재시작 시 실행할 원래 스크립트
FALLBACK_MODE = "--fallback" in sys.argv
DATA_DIR = os.path.join(APP_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "schedule.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
FALLBACK_DIR = os.path.join(DATA_DIR, "fallback")
LOG_FILE = os.path.join(DATA_DIR, "error.log")
BACKUP_KEEP = 14
MUTEX_NAME = "Local\\WeeklyScheduleWidget-%08x" % zlib.crc32(APP_DIR.lower().encode("utf-8"))

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
# 과목 태그 색 (배경, 글자) — 이름 해시로 항상 같은 색
TAG_COLORS = [("#eef2ff", "#4338ca"), ("#e0f2fe", "#0369a1"), ("#dcfce7", "#15803d"),
              ("#fce7f3", "#be185d"), ("#ede9fe", "#6d28d9"), ("#ccfbf1", "#0f766e"),
              ("#f1f5f9", "#334155")]

FONT = "Malgun Gothic"
W_WIDTH = 340      # 논리 픽셀 (DPI 배율이 곱해짐)
W_HEIGHT = 600
BULLET_OUT = "⦁    "   # 메모로 보낼 때 쓰는 글머리표

HOTKEY_LABEL = "Ctrl+Alt+W"
HOTKEY_MODS = 0x0001 | 0x0002 | 0x4000      # MOD_ALT | MOD_CONTROL | MOD_NOREPEAT
HOTKEY_VK = ord("W")

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
    "up_bg":    "#fbfcfe",
    "chip_bg":  "#eef1f6",
    "chip_fg":  "#64748b",
    "done":     "#c3cbd8",
    "btn":      "#64748b",
    "btn_hi":   "#0f172a",
    "field_bd": "#dbe1ea",
    "sat_bg":   "#e4edff", "sat_fg": "#2563eb",
    "sun_bg":   "#ffe4e6", "sun_fg": "#dc2626",
    "danger_bg": "#fee2e2", "danger_fg": "#dc2626",
    "warn_bg":  "#ffedd5", "warn_fg": "#c2410c",
    "imp_bg":   "#fff7e6", "imp_fg": "#b45309",
    "carry_bg": "#fffbeb", "carry_fg": "#92400e",
    "good":     "#22c55e",
    "snack":    "#1f2937", "snack_fg": "#a5b4fc",
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
        h = k.CreateMutexW(None, False, MUTEX_NAME)
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
def log_error(context, exc=None):
    """콘솔이 없어서(pythonw) 보이지 않는 오류를 data/error.log 에 기록"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 256 * 1024:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {context}\n")
            if exc is not None:
                f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            f.write("\n")
    except Exception:
        pass


def install_error_hooks():
    sys.excepthook = lambda t, v, tb: log_error("처리되지 않은 오류", v)
    threading.excepthook = lambda a: log_error("백그라운드 작업 오류", a.exc_value)


def _with_defaults(d):
    d.setdefault("categories", [dict(c) for c in DEFAULT_CATEGORIES])
    d.setdefault("items", {})          # 주간: {"YYYY-MM-DD": [item]}
    d.setdefault("lists", [])          # 전체: [{id,name,color,folded,items:[item]}]
    d.setdefault("section_order", [])  # 메모의 주간 섹션 순서 (내보내기용)
    d.setdefault("day_sections", [])   # <요일> 블록을 쓰는 섹션
    d.setdefault("recurring", [])      # 반복 일정 규칙
    d.setdefault("window", {})
    return d


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError("일정 데이터 형식이 아님")
    return d


def _backups():
    try:
        return sorted(os.path.join(BACKUP_DIR, n) for n in os.listdir(BACKUP_DIR)
                      if n.startswith("schedule-") and n.endswith(".json"))
    except FileNotFoundError:
        return []


def backup_daily():
    """하루 한 번, 그날 처음 저장하기 전 데이터를 data/backups 에 보관 (최근 BACKUP_KEEP개)"""
    if not os.path.exists(DATA_FILE):
        return
    target = os.path.join(BACKUP_DIR, f"schedule-{dt.date.today():%Y-%m-%d}.json")
    if os.path.exists(target):
        return
    try:
        _read_json(DATA_FILE)            # 깨진 파일은 백업하지 않음
    except Exception:
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    shutil.copy2(DATA_FILE, target)
    for old in _backups()[:-BACKUP_KEEP]:
        try:
            os.remove(old)
        except OSError:
            pass


def load_data():
    """반환: (data, 알림 문구 또는 None).
    파일이 깨졌으면 schedule.corrupt-*.json 으로 복사해 두고 가장 최근 백업에서 복구."""
    if not os.path.exists(DATA_FILE):
        return _with_defaults({}), None
    try:
        return _with_defaults(_read_json(DATA_FILE)), None
    except Exception as e:
        log_error("일정 파일을 읽지 못함", e)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        shutil.copy2(DATA_FILE, os.path.join(DATA_DIR, f"schedule.corrupt-{stamp}.json"))
    except OSError as e:
        log_error("손상된 파일 보관 실패", e)
    for b in reversed(_backups()):
        try:
            d = _read_json(b)
        except Exception:
            continue
        day = os.path.basename(b)[len("schedule-"):-len(".json")]
        return (_with_defaults(d),
                f"일정 파일이 손상되어 {day} 백업으로 복구했습니다. (손상된 파일은 data 폴더에 보관)")
    return (_with_defaults({}),
            "일정 파일이 손상되었고 백업이 없습니다. 손상된 파일은 data 폴더에 보관했습니다.")


def save_data(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        backup_daily()
    except Exception as e:
        log_error("백업 실패", e)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def monday_of(date):
    return date - dt.timedelta(days=date.weekday())


def iso(date):
    return date.strftime("%Y-%m-%d")


def from_iso(s):
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def new_id():
    return uuid.uuid4().hex


def md(d):
    """11/29 (일) 형태"""
    return f"{d.month}/{d.day} ({WEEKDAYS_KR[d.weekday()]})"


def dday_info(d):
    """(표시 텍스트, 남은 일수, (배경, 글자))"""
    n = (d - dt.date.today()).days
    txt = "D-day" if n == 0 else (f"D-{n}" if n > 0 else f"D+{-n}")
    if n <= 1:
        col = (C["danger_bg"], C["danger_fg"])
    elif n <= 3:
        col = (C["warn_bg"], C["warn_fg"])
    else:
        col = (C["chip_bg"], C["chip_fg"])
    return txt, n, col


def tag_colors(name):
    return TAG_COLORS[zlib.crc32(name.encode("utf-8")) % len(TAG_COLORS)]


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


def tests_pass():
    """tests/ 폴더가 있으면 새 코드로 테스트를 돌려 통과해야만 재시작 (실패 내용은 error.log)"""
    tdir = os.path.join(APP_DIR, "tests")
    if not os.path.isdir(tdir):
        return True
    py = os.path.join(os.path.dirname(sys.executable), "python.exe")
    if not os.path.exists(py):
        py = sys.executable
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([py, "-m", "unittest", "discover", "-s", tdir, "-q"],
                           cwd=APP_DIR, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, env=env,
                           creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        log_error("테스트를 실행하지 못함 (업데이트는 계속)", e)
        return True
    if r.returncode != 0:
        log_error("새 버전이 테스트를 통과하지 못해 재시작하지 않음\n" + (r.stderr or "")[-4000:])
        return False
    return True


def save_fallback():
    """정상 실행이 확인된 코드를 data/fallback 에 보관 (새 버전이 시작하다 죽으면 대신 실행)"""
    if FALLBACK_MODE:
        return
    with open(SCRIPT, "rb") as f:
        cur = f.read()
    dst = os.path.join(FALLBACK_DIR, "schedule_widget.pyw")
    if os.path.exists(dst):
        with open(dst, "rb") as f:
            if f.read() == cur:
                return
    os.makedirs(FALLBACK_DIR, exist_ok=True)
    tmp = dst + ".tmp"
    with open(tmp, "wb") as f:
        f.write(cur)
    os.replace(tmp, dst)


def launch_fallback():
    """보관해 둔 이전 버전을 원래 폴더의 데이터로 실행. 실행했으면 True."""
    fb = os.path.join(FALLBACK_DIR, "schedule_widget.pyw")
    if FALLBACK_MODE or not os.path.exists(fb):
        return False
    try:
        with open(fb, "rb") as f, open(SCRIPT, "rb") as g:
            if f.read() == g.read():
                return False            # 지금 코드와 같으면 다시 실행해도 소용없음
        subprocess.Popen([pythonw_exe(), fb, "--app-dir", APP_DIR, "--fallback", "--restarted"],
                         cwd=APP_DIR, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except Exception as e:
        log_error("비상용 이전 버전 실행 실패", e)
        return False


# Win32 API (창 순서 / 전역 단축키) — 전역 user32 설정을 건드리지 않도록 별도 인스턴스
if os.name == "nt":
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _u32.GetAncestor.restype = ctypes.c_void_p
    _u32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    _u32.GetForegroundWindow.restype = ctypes.c_void_p
    _u32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    _u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    _u32.IsIconic.argtypes = [ctypes.c_void_p]
    _u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    _u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _u32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    _u32.GetMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG), ctypes.c_void_p,
                                 ctypes.c_uint, ctypes.c_uint]
else:
    _u32 = None


# ------------------------------------------------------------------
# Sticky Notes 파서
#   ====== [ 이름 ] ======  → 주간 섹션 (<요일>, [라벨, MM/DD] 아래 항목을 날짜에 배치)
#   [라벨, ~MM/DD]          → '~' 가 있으면 마감, 없으면 일정 (둘 다 D-day 표시)
#   ---- [ 이름 ] ----      → 전체 목록 (날짜 없는 할 일, ~MM/DD 로 마감일 지정 가능)
#   ✓ 할 일                 → 완료된 항목
# ------------------------------------------------------------------
_BULLETS = "⦁•·‣◦●○▪▫■□▸▹►▻◆◇★☆➤→\\-\\*\\+"
_RE_WEEK_SECTION = re.compile(r"^={3,}\s*\[?\s*(.+?)\s*\]?\s*={3,}$")
_RE_LIST_SECTION = re.compile(r"^-{3,}\s*\[?\s*(.+?)\s*\]?\s*-{3,}$")
_RE_WEEKDAY = re.compile(r"^<\s*([월화수목금토일])\s*(?:요일)?\s*>\s*$")
_RE_WEEKDAY2 = re.compile(r"^([월화수목금토일])요일\s*[:：]?\s*$")
_RE_BRACKET = re.compile(r"^\[(.+?)\]\s*[:：]?\s*$")
_RE_BRACKET_DATE = re.compile(r"(~\s*)?(\d{1,2})\s*[/\.]\s*(\d{1,2})")
_RE_DUE_INLINE = re.compile(r"\(?\s*~\s*(\d{1,2})\s*/\s*(\d{1,2})\s*\)?")
_RE_BULLET = re.compile(r"^(?:[" + _BULLETS + r"]|\d+[.)])\s*(.*)$")
_RE_DONE = re.compile(r"^(?:[✓✔☑]|\[[xX]\])\s*")
_RE_TAG = re.compile(r"^\[([^\[\]]{1,20})\]\s*(.*)$")
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
    """(텍스트, 중요, 완료). ✓ 로 시작하면 완료, **강조**/*강조* 는 중요."""
    t = t.strip()
    done = False
    m = _RE_DONE.match(t)
    if m:
        done, t = True, t[m.end():]
    important = "**" in t or bool(re.fullmatch(r"\*[^*].*\*", t.strip()))
    t = t.replace("**", "").strip()
    if len(t) >= 2 and t.startswith("*") and t.endswith("*"):
        t = t[1:-1].strip()
    t = re.sub(r"\s+", " ", t).strip()
    return t, important, done


def _bullet_text(line):
    m = _RE_BULLET.match(line)
    return clean_text(m.group(1) if m else line)


def parse_sticky_note(text):
    res = {"weekday": [], "dated": [], "lists": [], "sections": [], "day_sections": []}
    mode = "week"
    section = weekday = cur_date = label = cur_list = None
    deadline = False

    def add_section(name):
        if name not in res["sections"]:
            res["sections"].append(name)

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            cur_date = None
            continue

        m = _RE_WEEK_SECTION.match(line)
        if m and re.search(r"[^=\s\[\]]", m.group(1)):
            mode, section = "week", m.group(1).strip()
            add_section(section)
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
            txt, imp, done = _bullet_text(line)
            if txt in _PLACEHOLDERS:
                continue
            due = None
            dm = _RE_DUE_INLINE.search(txt)
            if dm:
                due = _make_date(int(dm.group(1)), int(dm.group(2)))
                if due:
                    txt = re.sub(r"\s+", " ", txt[:dm.start()] + " " + txt[dm.end():]).strip()
            if txt:
                cur_list["items"].append({"text": txt, "important": imp, "done": done,
                                          "due_date": iso(due) if due else None})
            continue

        m = _RE_WEEKDAY.match(line) or _RE_WEEKDAY2.match(line)
        if m:
            weekday, cur_date = WEEKDAY_IDX[m.group(1)], None
            sec = section or "기타"
            add_section(sec)
            if sec not in res["day_sections"]:
                res["day_sections"].append(sec)
            continue

        m = _RE_BRACKET.match(line)
        if m:
            inside = m.group(1).strip()
            dm = _RE_BRACKET_DATE.search(inside)
            if dm:
                first = inside.split(",")[0].strip()
                label = None if _RE_BRACKET_DATE.search(first) else first
                deadline = bool(dm.group(1))
                cur_date = _make_date(int(dm.group(2)), int(dm.group(3)))
                weekday = None
            else:
                section, weekday, cur_date = inside, None, None
                add_section(section)
            continue

        txt, imp, done = _bullet_text(line)
        if txt in _PLACEHOLDERS:
            continue
        txt, rep = strip_repeat(txt)
        cat = section or "기타"
        if weekday is not None:
            res["weekday"].append({"widx": weekday, "text": txt, "category": cat,
                                   "important": imp, "done": done, "repeat": rep})
        elif cur_date is not None:
            res["dated"].append({"date": cur_date, "text": txt, "category": cat,
                                 "important": imp, "done": done,
                                 "label": label, "deadline": deadline, "repeat": False})
            add_section(cat)
    return res


def plan_import(text, week_start):
    """{"inweek": [...], "other": [...], "lists": [...], "sections": [...], "day_sections": [...]}
       inweek/other 항목: dict(date, text, category, important, done, label, deadline, due)"""
    res = parse_sticky_note(text)
    week_end = week_start + dt.timedelta(days=6)
    inweek, other = [], []
    for e in res["weekday"]:
        inweek.append(dict(e, date=week_start + dt.timedelta(days=e["widx"]),
                           label=None, deadline=False, due=False))
    for e in res["dated"]:
        e = dict(e, due=True)
        (inweek if week_start <= e["date"] <= week_end else other).append(e)
    inweek.sort(key=lambda e: e["date"])
    other.sort(key=lambda e: e["date"])
    return {"inweek": inweek, "other": other, "lists": res["lists"],
            "sections": res["sections"], "day_sections": res["day_sections"]}


# ------------------------------------------------------------------
# 메모로 보내기 (위젯 → Sticky Notes 형식)
# ------------------------------------------------------------------
def _item_line(it, with_due=False):
    t = it.get("text", "")
    if it.get("rid"):
        t += " " + REPEAT_MARK
    if with_due and it.get("due_date"):
        d = from_iso(it["due_date"])
        if d:
            t += f" ~{d.month}/{d.day}"
    if it.get("important"):
        t += " **"
    if it.get("done"):
        t = "✓ " + t
    return t


def export_note(data, week_start):
    """보고 있는 주의 일정 + (지난 30일~미래의) 날짜 항목 + 전체 목록을 메모 형식으로."""
    week_end = week_start + dt.timedelta(days=6)
    secs = {}

    def sec(name):
        return secs.setdefault(name, {"groups": {}, "days": {}})

    for k, lst in data["items"].items():
        d = from_iso(k)
        if not d:
            continue
        inweek = week_start <= d <= week_end
        for it in lst:
            name = it.get("category") or "기타"
            if it.get("due") or it.get("label"):
                keep = (inweek or d > week_end or
                        (not it.get("done") and (week_start - d).days <= 30))
                if keep:
                    key = (it.get("label") or "", k, bool(it.get("deadline")))
                    sec(name)["groups"].setdefault(key, []).append(it)
            elif inweek:
                sec(name)["days"].setdefault(d.weekday(), []).append(it)

    order = list(data.get("section_order", []))
    day_secs = set(data.get("day_sections", []))
    for n in order:
        sec(n)
    rank = {n: i for i, n in enumerate(order)}
    names = sorted(secs, key=lambda n: (rank.get(n, len(rank)), n))

    blocks = []
    for n in names:
        s = secs[n]
        parts = []
        for (label, k, dl), its in sorted(s["groups"].items(), key=lambda kv: (kv[0][1], kv[0][0])):
            d = from_iso(k)
            ds = f"{'~' if dl else ''}{d.month}/{d.day} {WEEKDAYS_KR[d.weekday()]}"
            head = f"[{label}, {ds}]" if label else f"[{ds}]"
            parts.append("\n".join([head] + [BULLET_OUT + _item_line(it) for it in its]))
        if s["days"] or n in day_secs:
            lines = []
            for i in range(7):
                lines.append(f"<{WEEKDAYS_KR[i]}요일>")
                its = s["days"].get(i, [])
                lines += [BULLET_OUT + _item_line(it) for it in its] or [BULLET_OUT + "-"]
            parts.append("\n".join(lines))
        if not parts and n not in order:
            continue
        blocks.append(f"====== [ {n} ] ======" + ("\n" + "\n\n".join(parts) if parts else ""))

    for L in data.get("lists", []):
        blocks.append("\n".join([f"---- [{L['name']}] ----"] +
                                [BULLET_OUT + _item_line(it, True) for it in L["items"]]))
    return "\n\n".join(blocks) + "\n"


# ------------------------------------------------------------------
# 데이터 조작 (화면과 분리 — tests/ 에서 직접 검증)
# ------------------------------------------------------------------
def ensure_categories(data, names, color=None):
    existing = {c["name"] for c in data["categories"]}
    idx = len(data["categories"])
    for n in names:
        if n and n not in existing:
            data["categories"].append(
                {"name": n, "color": color or IMPORT_PALETTE[idx % len(IMPORT_PALETTE)]})
            existing.add(n)
            idx += 1


def merge_import(data, plan, week_start):
    """가져오기 계획을 데이터에 반영. 반환: (주간 항목 수, 목록 수)"""
    inweek, other, lists = plan["inweek"], plan["other"], plan["lists"]

    def make(e, was_done):
        return {"id": new_id(), "text": e["text"], "category": e["category"],
                "important": e["important"], "done": e["done"] or was_done,
                "label": e["label"], "due": e["due"], "deadline": e["deadline"]}

    ensure_categories(data, [e["category"] for e in inweek + other])

    # 주간: 선택한 주는 메모 내용으로 교체 (같은 날짜·내용이면 완료 체크 유지)
    #  - "(매주)" 항목은 반복 일정으로 연결 (없으면 새로 만듦)
    #  - 반복 일정은 메모에 없어도 지우지 않음 (자동으로 들어가는 일정이므로)
    if inweek:
        keys = [iso(week_start + dt.timedelta(days=i)) for i in range(7)]
        was_done = {(k, x.get("text"), x.get("label")) for k in keys
                    for x in data["items"].get(k, []) if x.get("done")}
        prev_rep = [(k, x) for k in keys for x in data["items"].get(k, []) if x.get("rid")]
        for k in keys:
            data["items"].pop(k, None)
        for e in inweek:
            k = iso(e["date"])
            it = make(e, (k, e["text"], e["label"]) in was_done)
            same = next((x for pk, x in prev_rep if pk == k and x.get("text") == e["text"]), None)
            if same is not None:
                it.update(rid=same["rid"], rdate=same.get("rdate", k))
            elif e.get("repeat"):
                r = next((r for r in data["recurring"]
                          if r["text"] == e["text"] and r["category"] == e["category"]
                          and (not r.get("end") or r["end"] >= k)), None)
                if r is None:
                    r = add_recurring(data, e["text"], e["category"], [], e["date"])
                if e["date"].weekday() not in r["weekdays"]:
                    r["weekdays"] = sorted(r["weekdays"] + [e["date"].weekday()])
                r["start"] = min(r["start"], k)
                if k in r.get("skip", []):
                    r["skip"].remove(k)
                it.update(rid=r["id"], rdate=k)
            data["items"].setdefault(k, []).append(it)
        have = _occurrences(data)
        for k, x in prev_rep:
            if (x["rid"], x.get("rdate")) not in have:
                data["items"].setdefault(k, []).append(x)

    # 다른 주의 날짜 항목(마감 등): 그 날짜에 추가 (이미 있으면 갱신)
    for e in other:
        k = iso(e["date"])
        lst = data["items"].setdefault(k, [])
        ex = next((x for x in lst if x.get("text") == e["text"]
                   and x.get("label") == e["label"]), None)
        if ex:
            ex.update(category=e["category"], important=e["important"],
                      label=e["label"], due=True, deadline=e["deadline"])
            if e["done"]:
                ex["done"] = True
        else:
            lst.append(make(e, False))

    # 전체: 메모의 목록으로 교체 (같은 목록·내용이면 완료 체크, 색, 접힘 유지)
    if lists:
        prev = {L["name"]: L for L in data["lists"]}
        was_done = {(L["name"], it.get("text")) for L in data["lists"]
                    for it in L["items"] if it.get("done")}
        new_lists = []
        for i, L in enumerate(lists):
            p = prev.get(L["name"], {})
            new_lists.append({
                "id": p.get("id", new_id()), "name": L["name"],
                "color": p.get("color", LIST_PALETTE[i % len(LIST_PALETTE)]),
                "folded": p.get("folded", False),
                "items": [{"id": new_id(), "text": e["text"], "important": e["important"],
                           "done": e["done"] or (L["name"], e["text"]) in was_done,
                           "due_date": e["due_date"]}
                          for e in L["items"]],
            })
        data["lists"] = new_lists

    if plan["sections"]:
        data["section_order"] = plan["sections"]
        data["day_sections"] = plan["day_sections"]
    return len(inweek) + len(other), len(lists)


def move_item(data, from_key, item, to_date):
    lst = data["items"].get(from_key, [])
    data["items"][from_key] = [x for x in lst if x is not item]
    if not data["items"][from_key]:
        data["items"].pop(from_key, None)
    data["items"].setdefault(iso(to_date), []).append(item)


def carry_over_candidates(data, today, days=30):
    """오늘 이전(최근 days일) 날짜의 미완료 항목 — D-day 항목(날짜가 의미 있음)과
    반복 일정(어차피 또 돌아옴)은 제외"""
    out = []
    for k, lst in data["items"].items():
        d = from_iso(k)
        if d and d < today and (today - d).days <= days:
            out += [(k, it) for it in lst
                    if not it.get("done") and not it.get("due") and not it.get("rid")]
    return sorted(out, key=lambda x: x[0])


def carry_over(data, today):
    cands = carry_over_candidates(data, today)
    for k, it in cands:
        move_item(data, k, it, today)
    return len(cands)


def week_progress(data, week_start):
    items = [it for i in range(7)
             for it in data["items"].get(iso(week_start + dt.timedelta(days=i)), [])]
    return sum(1 for it in items if it.get("done")), len(items)


def list_progress(data):
    items = [it for L in data["lists"] for it in L["items"]]
    return sum(1 for it in items if it.get("done")), len(items)


def reorder_item(data, from_key, item, to_key, index):
    """주간 항목을 to_key 날짜의 index 위치로 (같은 날이면 순서만 바꿈)"""
    src = data["items"].get(from_key, [])
    if from_key == to_key:
        old = next((i for i, x in enumerate(src) if x is item), None)
        if old is not None and old < index:
            index -= 1
    data["items"][from_key] = [x for x in src if x is not item]
    if not data["items"][from_key]:
        data["items"].pop(from_key, None)
    dst = data["items"].setdefault(to_key, [])
    dst.insert(max(0, min(index, len(dst))), item)


def move_list_item(src, item, dst, index):
    """전체 목록 항목을 dst 목록의 index 위치로"""
    if src is dst:
        old = next((i for i, x in enumerate(src["items"]) if x is item), None)
        if old is not None and old < index:
            index -= 1
    src["items"] = [x for x in src["items"] if x is not item]
    dst["items"].insert(max(0, min(index, len(dst["items"]))), item)


# ------------------------------------------------------------------
# 반복 일정 (매주 같은 요일)
#   규칙: data["recurring"] = [{id, text, category, weekdays, start, end, skip}]
#   주를 볼 때 그 주의 항목을 실제로 만들어 둠(rid=규칙, rdate=원래 날짜) →
#   완료 체크·옮기기·메모 내보내기가 보통 항목과 똑같이 동작
# ------------------------------------------------------------------
REPEAT_MARK = "(매주)"
_RE_REPEAT = re.compile(r"\s*\((?:매주|반복)\)\s*$")


def strip_repeat(text):
    m = _RE_REPEAT.search(text)
    return (text[:m.start()].strip(), True) if m else (text, False)


def find_rule(data, rid):
    return next((r for r in data["recurring"] if r["id"] == rid), None)


def add_recurring(data, text, category, weekdays, start):
    r = {"id": new_id(), "text": text, "category": category,
         "weekdays": sorted(set(weekdays)), "start": iso(start), "end": None, "skip": []}
    data["recurring"].append(r)
    return r


def _occurrences(data):
    return {(it["rid"], it.get("rdate")) for lst in data["items"].values()
            for it in lst if it.get("rid")}


def materialize_recurring(data, start, end):
    """start~end 사이 반복 일정 항목을 만들어 둠 (이미 있거나 지운 날은 건너뜀). 반환: 만든 개수"""
    if not data["recurring"]:
        return 0
    have = _occurrences(data)
    n = 0
    d = start
    while d <= end:
        k = iso(d)
        for r in data["recurring"]:
            if (d.weekday() in r["weekdays"] and r["start"] <= k
                    and (not r.get("end") or k <= r["end"])
                    and k not in r.get("skip", []) and (r["id"], k) not in have):
                data["items"].setdefault(k, []).append(
                    {"id": new_id(), "text": r["text"], "category": r["category"],
                     "done": False, "important": False, "label": None, "due": False,
                     "deadline": False, "rid": r["id"], "rdate": k})
                have.add((r["id"], k))
                n += 1
        d += dt.timedelta(days=1)
    return n


def skip_occurrence(data, item):
    """반복 항목 하나를 지울 때: 그 날은 다시 만들지 않도록 기록"""
    r = find_rule(data, item.get("rid"))
    if r and item.get("rdate") and item["rdate"] not in r.setdefault("skip", []):
        r["skip"].append(item["rdate"])


def _drop_future(data, rid, after_key, keep=lambda it: False):
    """rid 반복 항목 중 원래 날짜가 after_key 이후이고 완료 안 된 것을 지움"""
    for k in list(data["items"]):
        lst = [it for it in data["items"][k]
               if not (it.get("rid") == rid and (it.get("rdate") or k) > after_key
                       and not it.get("done") and not keep(it))]
        if lst:
            data["items"][k] = lst
        else:
            data["items"].pop(k)


def end_recurring(data, rid, last_day):
    """last_day 까지만 하고 반복 끝내기 (그 뒤의 미완료 항목은 지움)"""
    r = find_rule(data, rid)
    if r:
        r["end"] = iso(last_day)
        _drop_future(data, rid, iso(last_day))


def update_recurring(data, rid, from_day, text, category, weekdays):
    """from_day 이후 반복 일정의 내용·요일 변경 (이미 완료한 항목은 그대로)"""
    r = find_rule(data, rid)
    if not r:
        return
    k0 = iso(from_day)
    if not weekdays:
        end_recurring(data, rid, from_day)
        return
    r.update(text=text, category=category, weekdays=sorted(set(weekdays)))
    _drop_future(data, rid, k0,
                 keep=lambda it: (from_iso(it.get("rdate")) or from_day).weekday() in r["weekdays"])
    for lst in data["items"].values():
        for it in lst:
            if it.get("rid") == rid and (it.get("rdate") or "") >= k0 and not it.get("done"):
                it.update(text=text, category=category)


# ------------------------------------------------------------------
# 실행 취소 / 다시 실행 (창 위치 같은 설정은 제외하고 내용만 기억)
# ------------------------------------------------------------------
def _content(data):
    return json.dumps({k: v for k, v in data.items() if k != "window"},
                      ensure_ascii=False, sort_keys=True)


class History:
    def __init__(self, data, limit=40):
        self.limit = limit
        self.undo_stack, self.redo_stack = [], []
        self._cur = _content(data)

    def record(self, data, label):
        """바뀐 게 있으면 바뀌기 전 상태를 기억. 반환: 기록 여부"""
        s = _content(data)
        if s == self._cur:
            return False
        if label is None:              # 자동 생성(반복 일정 등) — 되돌릴 대상 아님
            self._cur = s
            return False
        self.undo_stack.append((label, self._cur))
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()
        self._cur = s
        return True

    def _swap(self, data, src, dst):
        if not src:
            return None
        label, s = src.pop()
        dst.append((label, self._cur))
        self._cur = s
        new = json.loads(s)
        new["window"] = data.get("window", {})
        return label, _with_defaults(new)

    def undo(self, data):
        return self._swap(data, self.undo_stack, self.redo_stack)

    def redo(self, data):
        return self._swap(data, self.redo_stack, self.undo_stack)


# ------------------------------------------------------------------
# 메인 앱
# ------------------------------------------------------------------
class ScheduleWidget:
    def __init__(self, root):
        global SCALE
        self.root = root
        SCALE = root.winfo_fpixels("1i") / 96.0
        self.W, self.H = S(W_WIDTH), S(W_HEIGHT)

        self.data, notice = load_data()
        self.history = History(self.data)
        self._dnd = None
        try:
            backup_daily()
        except Exception as e:
            log_error("백업 실패", e)
        self.week_start = monday_of(dt.date.today())
        self.tab = self.data["window"].get("tab", "week")
        self._drag = {"x": 0, "y": 0}
        self._updating = False
        self._toast_job = None
        self._sb_shown = False
        self._sig = code_signature()
        self._today_block = None
        self._banner = None
        self._hwnd_cache = None
        self._desk_mode = False
        self._summoned = False
        self._summon_prev_fg = None
        self._summon_own = False
        self._watch_logged = False

        root.overrideredirect(True)
        root.configure(bg=C["frame"])
        self.topmost = bool(self.data["window"].get("topmost", False))
        root.attributes("-topmost", self.topmost)

        self._init_fonts()
        self._place_window()
        self._build()
        self.set_tab(self.tab, save=False)

        root.bind("<MouseWheel>", self._on_wheel)
        root.bind("<Control-KeyPress>", self._on_ctrl_key)       # Ctrl+Z / Ctrl+Y (한/영 무관)
        root.bind("<Button-1>", self._take_focus, add="+")
        root.bind("<Button-3>", self._bg_menu)
        root.bind("<Escape>", self._dnd_cancel)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.report_callback_exception = self._on_tk_error
        root.after(150, self._scroll_to_today)
        root.after(2000, lambda: self.check_update(manual=False))
        root.after(5000, self._mark_good)
        root.after(1000, self._watch_desktop)
        self._schedule_midnight()
        self._start_hotkey()
        if FALLBACK_MODE:
            self._show_banner("새 버전이 시작 중 오류가 나서 이전 버전으로 실행 중입니다. "
                              "내용은 data/error.log — 고친 뒤 '새로고침'을 누르세요.")
        elif notice:
            self._show_banner(notice)

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
        self.f_tag = F(8, weight="bold")
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

    def _schedule_midnight(self):
        """자정이 지나면 '오늘'·D-day 갱신"""
        now = dt.datetime.now()
        nxt = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(0, 0, 5))
        self.root.after(int((nxt - now).total_seconds() * 1000),
                        lambda: (self.render(keep_scroll=True), self._schedule_midnight()))

    # ---------- 위젯 헬퍼 ----------
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

    def _badge(self, parent, text, bg, fg, font=None):
        return tk.Label(parent, text=text, font=font or self.f_tag, bg=bg, fg=fg,
                        padx=S(4), pady=0)

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

    @staticmethod
    def _ellipsize(text, font, width):
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "…") > width:
            text = text[:-1]
        return text + "…"

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
        self.lbl_prog = tk.Label(self.nav_week, text="", font=self.f_status, bg=C["bg"],
                                 fg=C["muted"])
        self.lbl_prog.pack(side="left", padx=(S(8), 0))
        self._solid(self.nav_week, "오늘", self.goto_today).pack(side="right")

        self.nav_all = tk.Frame(row2, bg=C["bg"])
        self.lbl_summary = tk.Label(self.nav_all, text="", font=self.f_sub, bg=C["bg"], fg=C["sub"])
        self.lbl_summary.pack(side="left", pady=S(3))
        self._solid(self.nav_all, "＋ 새 목록", self.new_list).pack(side="right")

        for w in (header, row1, row2, self.nav_week, self.nav_all,
                  self.lbl_week, self.lbl_summary, self.lbl_prog):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        # 진행률 막대 (헤더 아래 구분선 겸용, 접어도 보임)
        self.prog_track = tk.Frame(outer, bg=C["sep"], height=S(3))
        self.prog_track.pack(fill="x")
        self.prog_fill = tk.Frame(self.prog_track, bg=C["accent"])

        # 본문 + 푸터 (접기 시 함께 숨김)
        self.main = tk.Frame(outer, bg=C["bg"])
        self.main.pack(fill="both", expand=True)

        footer = tk.Frame(self.main, bg=C["bg"])
        footer.pack(side="bottom", fill="x")
        tk.Frame(self.main, bg=C["sep"], height=max(1, S(1))).pack(side="bottom", fill="x")
        fin = tk.Frame(footer, bg=C["bg"])
        fin.pack(fill="x", padx=S(14), pady=S(8))
        tk.Label(fin, text="메모", font=self.f_act, bg=C["bg"], fg=C["muted"]).pack(side="left")
        self._txt(fin, "가져오기", self.open_import, font=self.f_act_b,
                  fg=C["accent"], hi=C["accent_dk"]).pack(side="left", padx=(S(6), 0))
        tk.Label(fin, text="·", font=self.f_act, bg=C["bg"], fg=C["muted"]).pack(
            side="left", padx=S(4))
        self._txt(fin, "보내기", self.open_export, font=self.f_act_b,
                  fg=C["accent"], hi=C["accent_dk"]).pack(side="left")
        self._txt(fin, "새로고침", lambda: self.check_update(manual=True),
                  font=self.f_act, fg=C["sub"], hi=C["title"]).pack(side="right")
        self.lbl_status = tk.Label(fin, text="", font=self.f_status, bg=C["bg"],
                                   fg=C["muted"], anchor="center")
        self.lbl_status.pack(side="left", fill="x", expand=True, padx=S(6))

        self.body_wrap = body_wrap = tk.Frame(self.main, bg=C["bg"])
        body_wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body_wrap, bg=C["bg"], highlightthickness=0, bd=0)
        self.scroll = ThinScroll(body_wrap, self.canvas)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=C["bg"])
        self._body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self._update_scroll())
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # 되돌리기 알림줄 (본문 아래쪽에 잠깐 떠 있음)
        sb = C["snack"]
        self.snack = tk.Frame(self.main, bg=sb)
        self.snack_msg = tk.Label(self.snack, text="", font=self.f_act, bg=sb, fg="#ffffff",
                                  anchor="w")
        self.snack_btn = tk.Label(self.snack, text="", font=self.f_act_b, bg=sb,
                                  fg=C["snack_fg"], cursor="hand2")
        self.snack_btn.pack(side="right", padx=(S(8), S(12)))
        self.snack_msg.pack(side="left", fill="x", expand=True, padx=(S(12), 0), pady=S(7))
        self.snack_btn.bind("<Enter>", lambda e: self.snack_btn.configure(fg="#ffffff"))
        self.snack_btn.bind("<Leave>", lambda e: self.snack_btn.configure(fg=C["snack_fg"]))
        self.snack_btn.bind("<Button-1>", lambda e: self._snack_click())
        self._snack_cmd = self._snack_job = None

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
        self.render(focus_today=(key == "week"))

    # ---------- 렌더링 ----------
    def _week_range_text(self):
        ws = self.week_start
        we = ws + dt.timedelta(days=6)
        fmt = "%m.%d" if ws.year == dt.date.today().year else "%Y.%m.%d"
        return f"{ws.strftime(fmt)}  –  {we.strftime('%m.%d')}"

    def render(self, keep_scroll=False, focus_today=False):
        if self._dnd:
            self._dnd_cleanup()
        pos = self.canvas.yview()[0] if keep_scroll else 0.0
        for ch in self.body.winfo_children():
            ch.destroy()
        self._today_block = None
        self._dnd_targets = []
        if self.tab == "week":
            if materialize_recurring(self.data, self.week_start,
                                     self.week_start + dt.timedelta(days=6)):
                self._persist(None)
            self.lbl_week.configure(text=self._week_range_text())
            done, total = week_progress(self.data, self.week_start)
            self.lbl_prog.configure(text=f"·  {done}/{total} 완료" if total else "")
            self._set_progress(done, total)
            self._render_carry()
            self._render_upcoming()
            today = dt.date.today()
            for i in range(7):
                day = self.week_start + dt.timedelta(days=i)
                self._render_day(day, i, is_today=(day == today))
        else:
            self._set_progress(*list_progress(self.data))
            self._render_lists()
        tk.Frame(self.body, bg=C["bg"], height=S(6)).pack()
        self.body.update_idletasks()
        self._update_scroll()
        self.canvas.yview_moveto(pos)
        if focus_today:
            self.root.after(30, self._scroll_to_today)

    def _upcoming(self):
        """완료 안 된 D-day 항목: [(date, item, list or None)] — 지난 14일 ~ 앞으로 30일"""
        today = dt.date.today()
        ups = []
        for k, lst in self.data["items"].items():
            d = from_iso(k)
            if not d:
                continue
            for it in lst:
                if it.get("due") and not it.get("done") and -14 <= (d - today).days <= 30:
                    ups.append((d, it, None))
        for L in self.data["lists"]:
            for it in L["items"]:
                d = from_iso(it.get("due_date"))
                if d and not it.get("done") and -14 <= (d - today).days <= 30:
                    ups.append((d, it, L))
        ups.sort(key=lambda x: x[0])
        return ups

    def _render_upcoming(self):
        ups = self._upcoming()
        if not ups:
            return
        bg = C["up_bg"]
        box = tk.Frame(self.body, bg=bg)
        box.pack(fill="x")
        head = tk.Frame(box, bg=bg)
        head.pack(fill="x", padx=(S(13), S(10)), pady=(S(8), S(3)))
        tk.Label(head, text="다가오는 일정", font=self.f_date, bg=bg, fg=C["sub"]).pack(side="left")
        tk.Label(head, text=str(len(ups)), font=self.f_status, bg=bg,
                 fg=C["muted"]).pack(side="left", padx=(S(5), 0))

        badge_w = self.f_tag.measure("D-30") + S(10)
        for d, it, L in ups[:5]:
            t, n, (b, f) = dday_info(d)
            row = tk.Frame(box, bg=bg, cursor="hand2")
            row.pack(fill="x", padx=(S(13), S(10)), pady=S(2))
            holder = tk.Frame(row, bg=bg, width=badge_w, height=self.f_tag.metrics("linespace") + S(2))
            holder.pack_propagate(False)
            holder.pack(side="left")
            self._badge(holder, t, b, f).pack(side="left")
            when = md(d) + ("  마감" if it.get("deadline") or L else "")
            wl = tk.Label(row, text=when, font=self.f_status, bg=bg, fg=C["muted"])
            wl.pack(side="right")
            chips = [it["label"]] if it.get("label") else []
            body = it.get("text", "")
            m = _RE_TAG.match(body)
            if m:
                chips.append(m.group(1))
                body = m.group(2)
            widgets = [row, holder, wl]
            used = 0
            for c in chips:
                cl = self._badge(row, c, *tag_colors(c))
                cl.pack(side="left", padx=(S(4), 0))
                widgets.append(cl)
                used += self.f_tag.measure(c) + S(12)
            avail = self.W - S(13 + 10 + 24) - badge_w - self.f_status.measure(when) - used
            tl = tk.Label(row, text=self._ellipsize(body, self.f_act, max(S(30), avail)),
                          font=self.f_act, bg=bg, fg=C["text"], anchor="w")
            tl.pack(side="left", fill="x", expand=True, padx=(S(5), 0))
            widgets.append(tl)
            go = (lambda e, d=d: self._goto_week(d)) if L is None else (lambda e: self.set_tab("all"))
            for w in widgets:
                w.bind("<Button-1>", go)
                w.configure(cursor="hand2")
        if len(ups) > 5:
            tk.Label(box, text=f"외 {len(ups) - 5}개", font=self.f_status, bg=bg,
                     fg=C["muted"]).pack(anchor="w", padx=S(13))
        tk.Frame(box, bg=bg, height=S(6)).pack()
        tk.Frame(self.body, bg=C["sep"], height=max(1, S(1))).pack(fill="x")

    def _goto_week(self, d):
        self.week_start = monday_of(d)
        self.render()

    def _render_day(self, day, idx, is_today):
        items = self.data["items"].get(iso(day), [])
        bg = C["today_bg"] if is_today else C["bg"]

        block = tk.Frame(self.body, bg=bg)
        block.pack(fill="x")
        if is_today:
            self._today_block = block
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

        target = {"kind": "day", "key": iso(day), "block": block, "rows": [], "count": 0}
        self._dnd_targets.append(target)
        for it in items:
            self._render_item(inner, bg, self._cat_color(it.get("category")), it,
                              on_edit=lambda d=day, i=it: ItemDialog(self, d, i),
                              due_date=day if it.get("due") else None,
                              on_menu=lambda e, d=day, i=it: self._item_menu(e, d, i),
                              drag=target)
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
        self._txt(head, "▸" if folded else "▾", toggle, font=self.f_date,
                  fg=C["muted"], hi=C["accent"]).pack(side="left")
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

        target = {"kind": "list", "key": L, "block": block, "rows": [],
                  "count": len(items) if folded else 0}
        self._dnd_targets.append(target)
        if not folded:
            if not items:
                tk.Label(block, text="할 일 없음", font=self.f_status, bg=bg,
                         fg=C["muted"]).pack(anchor="w", padx=S(34), pady=(0, S(4)))
            for it in items:
                self._render_item(block, bg, L.get("color", C["accent"]), it,
                                  on_edit=lambda L=L, i=it: self.edit_list_item(L, i),
                                  due_date=from_iso(it.get("due_date")),
                                  on_menu=lambda e, L=L, i=it: self._list_item_menu(e, L, i),
                                  drag=target)
            tk.Frame(block, bg=bg, height=S(6)).pack()

        tk.Frame(self.body, bg=C["sep"], height=max(1, S(1))).pack(fill="x", padx=S(12))

    def _render_item(self, parent, bg, color, it, on_edit, due_date=None, on_menu=None,
                     drag=None):
        done = it.get("done", False)
        imp = it.get("important", False)

        # 태그: 그룹 라벨(혜윰 등) + 텍스트 앞의 [과목]
        chips = []
        if it.get("label"):
            chips.append(it["label"])
        text = it.get("text", "")
        m = _RE_TAG.match(text)
        if m:
            chips.append(m.group(1))
            text = m.group(2)

        right = []                                  # 오른쪽 배지 (먼저 넣은 것이 가장 오른쪽)
        if due_date and not done:
            t, n, (b, f) = dday_info(due_date)
            right.append((t, b, f))
        if imp and not done:
            right.append(("중요", C["imp_bg"], C["imp_fg"]))
        if it.get("rid") and not done:
            right.append(("매주", C["chip_bg"], C["sub"]))

        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", padx=(S(13), S(10)), pady=S(2))

        tk.Frame(row, bg=C["done"] if done else color, width=S(3)).pack(side="left", fill="y")

        chk = self._checkbox(row, bg, done, lambda i=it: self.toggle_done(i))
        line_h = self.f_item.metrics("linespace")
        off = max(0, (line_h - chk.winfo_reqheight()) // 2) + S(2)
        chk.pack(side="left", anchor="n", padx=(S(8), 0), pady=(off, 0))

        tag_off = max(0, (line_h - self.f_tag.metrics("linespace")) // 2) + S(1)
        for c in chips:
            cb, cf = (C["chip_bg"], C["done"]) if done else tag_colors(c)
            lbl = self._badge(row, c, cb, cf)
            lbl.configure(cursor="hand2")
            lbl.pack(side="left", anchor="n", padx=(S(7), 0), pady=(tag_off, 0))

        for t, b, f in right:
            self._badge(row, t, b, f).pack(side="right", anchor="n",
                                           padx=(S(4), 0), pady=(tag_off, 0))

        if text or not chips:
            if done:
                font, fg = self.f_item_done, C["done"]
            elif imp:
                font, fg = self.f_item_b, C["title"]
            else:
                font, fg = self.f_item, C["text"]
            extra = (sum(self.f_tag.measure(c) + S(15) for c in chips) +
                     sum(self.f_tag.measure(t) + S(12) for t, _, _ in right))
            txt = tk.Label(row, text=text, font=font, bg=bg, fg=fg, cursor="hand2",
                           anchor="w", justify="left",
                           wraplength=max(S(80), self.W - S(85) - extra))
            txt.pack(side="left", fill="x", expand=True, padx=(S(6), 0))

        # 누르면 편집, 끌면 옮기기 (체크박스는 제외)
        parts = [w for w in [row] + list(row.winfo_children()) if w is not chk]
        for w in parts:
            if drag is not None:
                w.bind("<ButtonPress-1>", lambda e, r=row: self._dnd_press(e, drag, it, r))
                w.bind("<B1-Motion>", self._dnd_motion)
                w.bind("<ButtonRelease-1>", lambda e: self._dnd_release(e, on_edit))
            elif isinstance(w, tk.Label):
                w.bind("<Button-1>", lambda e: on_edit())
        if drag is not None:
            drag["rows"].append((row, it))

        if on_menu:                                  # 우클릭 메뉴
            for w in [row] + list(row.winfo_children()):
                w.bind("<Button-3>", lambda e: (on_menu(e), "break")[1])

    def _cat_color(self, name):
        for c in self.data["categories"]:
            if c["name"] == name:
                return c["color"]
        return "#94a3b8"

    # ---------- 공통 동작 ----------
    def _commit(self, label="변경"):
        self._persist(label)
        self.render(keep_scroll=True)

    def toggle_done(self, it):
        it["done"] = not it.get("done", False)
        self._commit("완료 체크" if it["done"] else "완료 해제")

    # ---------- 우클릭 메뉴 ----------
    def _popup(self, e, entries):
        m = tk.Menu(self.root, tearoff=0, font=self.f_act, bg=C["bg"], fg=C["text"],
                    activebackground=C["accent"], activeforeground="#ffffff")
        for ent in entries:
            if ent is None:
                m.add_separator()
            else:
                label, cmd = ent[0], ent[1]
                on = ent[2] if len(ent) > 2 else True
                m.add_command(label=label, command=cmd, state="normal" if on else "disabled",
                              accelerator=ent[3] if len(ent) > 3 else "")
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _item_menu(self, e, day, it):
        today = dt.date.today()
        nxt = day + dt.timedelta(days=1)
        ents = []
        if day != today:
            ents.append(("오늘로 옮기기", lambda: self._move(day, it, today)))
        ents.append(("내일로 미루기" if day == today else
                     f"다음 날 {nxt.month}/{nxt.day}({WEEKDAYS_KR[nxt.weekday()]})로 미루기",
                     lambda: self._move(day, it, nxt)))
        if not it.get("rid"):
            ents.append(("다음 주 같은 요일로",
                         lambda: self._move(day, it, day + dt.timedelta(days=7))))
        ents.append(None)
        ents.append(("중요 해제" if it.get("important") else "중요 표시",
                     lambda: self._flip(it, "important")))
        ents.append(("D-day 해제" if it.get("due") else "D-day 표시", lambda: self._flip_due(it)))
        ents.append(None)
        ents.append(("편집…", lambda: ItemDialog(self, day, it)))
        if it.get("rid"):
            ents.append(("반복 끝내기 (이번이 마지막)", lambda: self.stop_repeat(day, it)))
            ents.append(("이번만 삭제", lambda: self.delete_item(day, it)))
        else:
            ents.append(("삭제", lambda: self.delete_item(day, it)))
        self._popup(e, ents)

    def _list_item_menu(self, e, L, it):
        self._popup(e, [
            ("오늘 할 일로 추가", lambda: self.list_item_to_today(L, it)),
            None,
            ("중요 해제" if it.get("important") else "중요 표시", lambda: self._flip(it, "important")),
            None,
            ("편집…", lambda: self.edit_list_item(L, it)),
            ("삭제", lambda: self._delete_list_item(L, it)),
        ])

    def _flip(self, it, key):
        it[key] = not it.get(key, False)
        self._commit("중요 표시" if it[key] else "중요 해제")

    def _flip_due(self, it):
        on = not it.get("due", False)
        it["due"] = on
        it["deadline"] = on and (it.get("deadline", False) if it.get("label") else True)
        self._commit("D-day 표시" if on else "D-day 해제")

    def _move(self, day, it, to):
        move_item(self.data, iso(day), it, to)
        self._commit("옮기기")
        self._undoable(f"{to.month}/{to.day}({WEEKDAYS_KR[to.weekday()]})로 옮김")

    def _delete_list_item(self, L, it):
        L["items"].remove(it)
        self._commit("삭제")
        self._undoable("삭제함")

    def stop_repeat(self, day, it):
        end_recurring(self.data, it["rid"], day)
        self._commit("반복 끝내기")
        self._undoable("반복 끝냄")

    def list_item_to_today(self, L, it):
        today = dt.date.today()
        ensure_categories(self.data, [L["name"]], color=L.get("color"))
        self.data["items"].setdefault(iso(today), []).append(
            {"id": new_id(), "text": it.get("text", ""), "category": L["name"],
             "important": it.get("important", False), "done": False,
             "label": None, "due": False, "deadline": False})
        self._commit("오늘 할 일로 추가")
        self._undoable("오늘 할 일로 추가함")

    # ---------- 이월 / 진행률 / 오늘로 스크롤 ----------
    def _render_carry(self):
        today = dt.date.today()
        if not (self.week_start <= today <= self.week_start + dt.timedelta(days=6)):
            return
        cands = carry_over_candidates(self.data, today)
        if not cands:
            return
        bg = C["carry_bg"]
        bar = tk.Frame(self.body, bg=bg)
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=bg)
        inner.pack(fill="x", padx=(S(13), S(10)), pady=S(7))
        tk.Label(inner, text=f"지난 날 못 끝낸 일 {len(cands)}개", font=self.f_date, bg=bg,
                 fg=C["carry_fg"]).pack(side="left")
        self._txt(inner, "오늘로 옮기기", self.carry_to_today, font=self.f_act_b,
                  fg=C["accent"], hi=C["accent_dk"], bg=bg).pack(side="right")
        tk.Frame(self.body, bg=C["sep"], height=max(1, S(1))).pack(fill="x")

    def carry_to_today(self):
        n = carry_over(self.data, dt.date.today())
        self._persist("못 끝낸 일 옮기기")
        self.render(focus_today=True)
        self._undoable(f"{n}개를 오늘로 옮김")

    def _set_progress(self, done, total):
        if not total or not done:
            self.prog_fill.place_forget()
            return
        self.prog_fill.configure(bg=C["good"] if done == total else C["accent"])
        self.prog_fill.place(x=0, y=0, relheight=1, relwidth=done / total)

    def _scroll_to_today(self):
        """오늘이 화면 아래로 밀려 있으면 오늘이 맨 위에 오도록 스크롤"""
        b = self._today_block
        if self.tab != "week" or b is None or not b.winfo_exists():
            return
        self.root.update_idletasks()
        view_h = self.canvas.winfo_height()
        total = max(1, self.body.winfo_height())
        y, h = b.winfo_y(), b.winfo_height()
        if y + h > view_h and total > view_h:
            self.canvas.yview_moveto(max(0.0, (y - S(4)) / total))

    # ---------- 주간 ----------
    def shift_week(self, delta):
        self.week_start += dt.timedelta(weeks=delta)
        self.render()

    def goto_today(self):
        self.week_start = monday_of(dt.date.today())
        self.render(focus_today=True)

    def save_item(self, day, item, text, category, due, weekdays=()):
        """weekdays: 매주 반복할 요일 (비어 있으면 반복 안 함)"""
        weekdays = sorted(set(weekdays))
        if item is None:
            if weekdays:
                r = add_recurring(self.data, text, category, weekdays, day)
                materialize_recurring(self.data, day, self.week_start + dt.timedelta(days=6))
                for lst in self.data["items"].values():     # 그날 항목에 D-day 반영
                    for it in lst:
                        if due and it.get("rid") == r["id"] and it.get("rdate") == iso(day):
                            it.update(due=True, deadline=True)
                self._commit("반복 일정 추가")
                days = "".join(WEEKDAYS_KR[i] for i in weekdays)
                self._undoable(f"매주 {days} 반복 추가")
                return
            self.data["items"].setdefault(iso(day), []).append(
                {"id": new_id(), "text": text, "category": category,
                 "done": False, "due": due, "deadline": due})
            self._commit("추가")
            return
        if due and not item.get("due"):
            item["deadline"] = True
        item.update(text=text, category=category, due=due)
        if not due:
            item["deadline"] = False
        if item.get("rid"):
            if find_rule(self.data, item["rid"]):
                update_recurring(self.data, item["rid"], day, text, category, weekdays)
        elif weekdays:                                       # 보통 일정을 반복으로 바꿈
            r = add_recurring(self.data, text, category, weekdays, day)
            if day.weekday() in weekdays:
                item.update(rid=r["id"], rdate=iso(day))
        self._commit("편집")

    def delete_item(self, day, item):
        key = iso(day)
        if item.get("rid"):
            skip_occurrence(self.data, item)
        self.data["items"][key] = [x for x in self.data["items"].get(key, [])
                                   if x.get("id") != item.get("id")]
        if not self.data["items"][key]:
            self.data["items"].pop(key, None)
        self._commit("삭제")
        self._undoable("삭제함")

    # ---------- 전체 목록 ----------
    def toggle_fold(self, L):
        L["folded"] = not L.get("folded", False)
        self._commit("목록 접기" if L["folded"] else "목록 펼치기")

    def new_list(self):
        def save(name, _imp, _due):
            used = {L.get("color") for L in self.data["lists"]}
            color = next((c for c in LIST_PALETTE if c not in used),
                         LIST_PALETTE[len(self.data["lists"]) % len(LIST_PALETTE)])
            self.data["lists"].append({"id": new_id(), "name": name, "color": color,
                                       "folded": False, "items": []})
            if self.tab != "all":
                self.set_tab("all")
            self._commit("새 목록")
        TextDialog(self, "새 목록", "", save, field_label="목록 이름")

    def edit_list(self, L):
        def save(name, _imp, _due):
            L["name"] = name
            self._commit("목록 이름 변경")

        def delete():
            self.data["lists"].remove(L)
            self._commit("목록 삭제")
            self._undoable(f"'{L['name']}' 목록 삭제함")
        TextDialog(self, "목록 편집", L["name"], save, on_delete=delete,
                   delete_label="목록 삭제", confirm_delete=True, field_label="목록 이름")

    def add_list_item(self, L):
        def save(text, imp, due):
            L["items"].append({"id": new_id(), "text": text, "important": imp,
                               "done": False, "due_date": due})
            L["folded"] = False
            self._commit("추가")
        TextDialog(self, f"할 일 추가 · {L['name']}", "", save, important=False,
                   show_due=True)

    def edit_list_item(self, L, it):
        def save(text, imp, due):
            it.update(text=text, important=imp, due_date=due)
            self._commit("편집")

        def delete():
            L["items"].remove(it)
            self._commit("삭제")
            self._undoable("삭제함")
        TextDialog(self, f"할 일 편집 · {L['name']}", it.get("text", ""), save,
                   on_delete=delete, important=it.get("important", False),
                   show_due=True, due=it.get("due_date"))

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
            h = self.header.winfo_reqheight() + S(3) + 2
            self.root.geometry(f"{self.W}x{h}+{x}+{y}")
        else:
            self.main.pack(fill="both", expand=True)
            self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.data["window"]["collapsed"] = self.collapsed
        self._persist()

    # ---------- 메모 가져오기 / 보내기 ----------
    def open_import(self):
        ImportDialog(self)

    def open_export(self):
        ExportDialog(self)

    def apply_import(self, text, week_start=None):
        ws = week_start or self.week_start
        plan = plan_import(text, ws)
        if not plan["inweek"] and not plan["other"] and not plan["lists"]:
            self._toast("인식된 항목 없음")
            return False
        n_week, n_lists = merge_import(self.data, plan, ws)
        self._persist("메모 가져오기")
        self.week_start = ws
        self.data["window"]["tab"] = "week"
        self.set_tab("week", save=False)
        self._persist(None)
        parts = ([f"주간 {n_week}"] if n_week else []) + ([f"목록 {n_lists}"] if n_lists else [])
        self._undoable("·".join(parts) + " 가져옴")
        return True

    def copy_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

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
        ok = (script_compiles() and tests_pass()) if changed else True
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
            self._toast("새 코드 검사 실패 — 재시작 안 함 (error.log)", ms=5000)
        elif pull == "conflict":
            self._toast("충돌로 받기 실패", ms=4000)
        elif pull in ("error", "no_remote", "no_git"):
            self._toast("깃허브 확인 실패", ms=4000)
        else:
            self._toast("이미 최신 버전")

    def _toast(self, msg, ms=2600, action=None):
        """짧은 알림은 푸터에, 누를 수 있는 동작(action=(글자, 함수))이 있으면 알림줄로"""
        if action:
            self._snack(msg, action)
            return
        self.lbl_status.configure(text=msg)
        if self._toast_job:
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(ms, lambda: self.lbl_status.configure(text=""))

    def _snack(self, msg, action, ms=6000):
        self._snack_cmd = action[1]
        room = self.W - S(20 + 32) - self.f_act_b.measure(action[0])
        self.snack_msg.configure(text=self._ellipsize(msg, self.f_act, room))
        self.snack_btn.configure(text=action[0])
        self.snack.place(in_=self.body_wrap, relx=0.5, rely=1.0, anchor="s",
                         relwidth=1.0, width=-S(20), y=-S(8))
        self.snack.lift()
        if self._snack_job:
            self.root.after_cancel(self._snack_job)
        self._snack_job = self.root.after(ms, self._hide_snack)

    def _hide_snack(self):
        self._snack_job = self._snack_cmd = None
        self.snack.place_forget()

    def _snack_click(self):
        cmd = self._snack_cmd
        self._hide_snack()
        if cmd:
            cmd()

    def _undoable(self, msg):
        """되돌리기 버튼이 붙은 알림"""
        self._toast(msg, action=("되돌리기", self.undo))

    # ---------- 실행 취소 ----------
    def undo(self):
        self._history_step(self.history.undo, "되돌림", ("다시 실행", self.redo))

    def redo(self):
        self._history_step(self.history.redo, "다시 실행함", ("되돌리기", self.undo))

    def _history_step(self, fn, verb, action):
        if self._dnd:
            return
        res = fn(self.data)
        if res is None:
            self._toast("되돌릴 내용 없음" if verb == "되돌림" else "다시 실행할 내용 없음")
            return
        label, self.data = res
        self._persist(None)
        self.render(keep_scroll=True)
        self._toast(f"{verb} · {label}", action=action)

    def _on_ctrl_key(self, e):
        if e.keycode == 90:                                 # Z (Shift 함께면 다시 실행)
            self.redo() if e.state & 0x1 else self.undo()
            return "break"
        if e.keycode == 89:                                 # Y
            self.redo()
            return "break"

    def _take_focus(self, e):
        """클릭하면 키보드 입력(Ctrl+Z)을 받을 수 있게"""
        if self.root.focus_get() is None:
            try:
                self.root.focus_force()
            except tk.TclError:
                pass

    def _bg_menu(self, e):
        """빈 곳 우클릭: 되돌리기 / 다시 실행"""
        h = self.history
        self._popup(e, [
            ("되돌리기" + (f" · {h.undo_stack[-1][0]}" if h.undo_stack else ""), self.undo,
             bool(h.undo_stack), "Ctrl+Z"),
            ("다시 실행" + (f" · {h.redo_stack[-1][0]}" if h.redo_stack else ""), self.redo,
             bool(h.redo_stack), "Ctrl+Y"),
        ])

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
            self._toast("재시작 실패 — 직접 다시 실행", ms=5000)
            return
        self.root.destroy()

    # ---------- 끌어서 옮기기 (항목 순서 / 다른 요일·목록으로) ----------
    def _dnd_press(self, e, target, it, row):
        self._dnd_cand = {"x": e.x_root, "y": e.y_root, "target": target, "item": it, "row": row}

    def _dnd_motion(self, e):
        c = getattr(self, "_dnd_cand", None)
        if c is None:
            return
        if self._dnd is None:
            if abs(e.x_root - c["x"]) < S(6) and abs(e.y_root - c["y"]) < S(6):
                return
            self._dnd_begin(c)
        self._dnd_update(e.x_root, e.y_root)

    def _dnd_release(self, e, click):
        c, self._dnd_cand = getattr(self, "_dnd_cand", None), None
        if self._dnd is None:
            if c is not None and click:
                click()
            return
        self._dnd_finish(e.x_root, e.y_root)

    def _dnd_begin(self, c):
        row, it = c["row"], c["item"]
        kids = row.winfo_children()
        color = kids[0].cget("bg") if kids else C["accent"]
        for w in kids:                                   # 원래 자리는 흐리게
            if isinstance(w, tk.Label):
                w.configure(fg=C["muted"])
        g = tk.Toplevel(self.root)
        g.overrideredirect(True)
        g.attributes("-topmost", True)
        try:
            g.attributes("-alpha", 0.92)
        except tk.TclError:
            pass
        g.configure(bg=C["accent"])
        box = tk.Frame(g, bg=C["bg"])
        box.pack(padx=1, pady=1)
        tk.Frame(box, bg=color, width=S(3)).pack(side="left", fill="y")
        tk.Label(box, text=self._ellipsize(it.get("text", ""), self.f_item, S(220)),
                 font=self.f_item, bg=C["bg"], fg=C["text"],
                 padx=S(8), pady=S(3)).pack(side="left")
        line = tk.Frame(self.body, bg=C["accent"], height=S(2))
        self._dnd = {"src": c["target"], "item": it, "ghost": g, "line": line,
                     "drop": None, "edge": 0, "pos": (c["x"], c["y"]), "job": None}
        self._dnd["job"] = self.root.after(30, self._dnd_autoscroll)

    def _dnd_update(self, x, y):
        d = self._dnd
        d["pos"] = (x, y)
        g = d["ghost"]
        g.geometry(f"+{x + S(14)}+{y - g.winfo_reqheight() // 2}")
        g.lift()
        cv = self.canvas
        cx, cy, cw, ch = cv.winfo_rootx(), cv.winfo_rooty(), cv.winfo_width(), cv.winfo_height()
        near_x = cx - S(60) <= x <= cx + cw + S(60)
        d["edge"] = 0
        if near_x and y < cy + S(28):
            d["edge"] = -1
        elif near_x and y > cy + ch - S(28):
            d["edge"] = 1
        drop = None
        if near_x and cy <= y <= cy + ch:
            tgt = None
            for t in self._dnd_targets:
                if t["block"].winfo_rooty() <= y:
                    tgt = t
                else:
                    break
            if tgt and y <= tgt["block"].winfo_rooty() + tgt["block"].winfo_height() + S(4):
                rows = tgt["rows"]
                idx = sum(1 for r, _ in rows if r.winfo_rooty() + r.winfo_height() / 2 < y)
                if rows and idx < len(rows):
                    ly = rows[idx][0].winfo_rooty() - S(2)
                elif rows:
                    r = rows[-1][0]
                    ly = r.winfo_rooty() + r.winfo_height() + S(1)
                else:
                    b = tgt["block"]
                    ly = b.winfo_rooty() + b.winfo_height() - S(5)
                    idx = tgt["count"]
                drop = (tgt, idx)
                d["line"].place(x=S(16), y=ly - self.body.winfo_rooty(), relwidth=1,
                                width=-S(28), height=S(2))
                d["line"].lift()
        if drop is None:
            d["line"].place_forget()
        d["drop"] = drop

    def _dnd_autoscroll(self):
        d = self._dnd
        if d is None:
            return
        if d["edge"] and self._sb_shown:
            top = self.canvas.yview()[0]
            self.canvas.yview_moveto(top + d["edge"] * S(8) / max(1, self.body.winfo_height()))
            self._dnd_update(*d["pos"])
        d["job"] = self.root.after(30, self._dnd_autoscroll)

    def _dnd_cleanup(self):
        d, self._dnd = self._dnd, None
        if d is None:
            return
        if d["job"]:
            self.root.after_cancel(d["job"])
        for w in (d["ghost"], d["line"]):
            try:
                w.destroy()
            except tk.TclError:
                pass
        return d

    def _dnd_cancel(self, e=None):
        if self._dnd:
            self._dnd_cleanup()
            self.render(keep_scroll=True)

    def _dnd_finish(self, x, y):
        self._dnd_update(x, y)
        d = self._dnd_cleanup()
        if not d["drop"]:
            self.render(keep_scroll=True)
            return
        (tgt, index), src, it = d["drop"], d["src"], d["item"]
        if src["kind"] != tgt["kind"]:
            self.render(keep_scroll=True)
            return
        if tgt["kind"] == "day":
            cur = self.data["items"].get(src["key"], [])
        else:
            cur = src["key"]["items"]
        old = next((i for i, x in enumerate(cur) if x is it), None)
        same = (src["key"] == tgt["key"]) if tgt["kind"] == "day" else (src["key"] is tgt["key"])
        if same:
            if old is None or index in (old, old + 1):      # 제자리
                self.render(keep_scroll=True)
                return
            if tgt["kind"] == "day":
                reorder_item(self.data, src["key"], it, tgt["key"], index)
            else:
                move_list_item(src["key"], it, tgt["key"], index)
            self._commit("순서 바꾸기")
            return
        if tgt["kind"] == "day":
            reorder_item(self.data, src["key"], it, tgt["key"], index)
            to = from_iso(tgt["key"])
            self._commit("옮기기")
            self._undoable(f"{to.month}/{to.day}({WEEKDAYS_KR[to.weekday()]})로 옮김")
        else:
            move_list_item(src["key"], it, tgt["key"], index)
            self._commit("옮기기")
            self._undoable(f"'{tgt['key']['name']}'(으)로 옮김")

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

    # ---------- Win+D 대응 / 전역 단축키 ----------
    def _hwnd(self):
        if not self._hwnd_cache and _u32:
            self._hwnd_cache = _u32.GetAncestor(self.root.winfo_id(), 2)    # GA_ROOT
        return self._hwnd_cache

    def _set_z(self, top):
        hwnd = self._hwnd()
        if hwnd:
            _u32.SetWindowPos(hwnd, ctypes.c_void_p(-1 if top else -2), 0, 0, 0, 0,
                              0x0001 | 0x0002 | 0x0010)    # NOSIZE | NOMOVE | NOACTIVATE

    def _watch_desktop(self):
        """바탕화면 보기(Win+D)로 바탕화면이 맨 앞에 오면 위젯을 그 위로 다시 올림 (0.4초마다)"""
        if _u32 is None:
            return
        try:
            hwnd = self._hwnd()
            fg = _u32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(64)
            if fg:
                _u32.GetClassNameW(fg, buf, 64)
            desk = buf.value in ("WorkerW", "Progman")
            if desk:
                if not _u32.IsWindowVisible(hwnd) or _u32.IsIconic(hwnd):
                    _u32.ShowWindow(hwnd, 4)                 # SW_SHOWNOACTIVATE
                if not self._desk_mode:
                    self._set_z(True)
            elif self._summoned:
                # 단축키로 불러온 뒤: 위젯을 한 번 쓰고 다른 창으로 넘어가면 원래대로
                if fg == hwnd:
                    self._summon_own = True
                elif fg and (fg != self._summon_prev_fg or self._summon_own):
                    self._summoned = False
                    if not self.topmost:
                        self._set_z(False)
            elif self._desk_mode and not self.topmost:
                self._set_z(False)
            self._desk_mode = desk
        except Exception as e:
            if not self._watch_logged:
                self._watch_logged = True
                log_error("바탕화면 감시 오류", e)
        self.root.after(400, self._watch_desktop)

    def _start_hotkey(self):
        if _u32 is None:
            return

        def run():
            for _ in range(20):        # 재시작 직후엔 이전 프로세스가 잠깐 잡고 있을 수 있음
                if _u32.RegisterHotKey(None, 1, HOTKEY_MODS, HOTKEY_VK):
                    break
                time.sleep(0.5)
            else:
                self.root.after(0, lambda: self._toast(f"단축키 {HOTKEY_LABEL} 사용 불가", ms=6000))
                return
            msg = ctypes.wintypes.MSG()
            while _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:                    # WM_HOTKEY
                    self.root.after(0, self.summon)
        threading.Thread(target=run, daemon=True, name="hotkey").start()

    def summon(self):
        """단축키: 위젯을 맨 앞으로 불러오기 (이미 앞에 있으면 다시 뒤로)"""
        hwnd = self._hwnd()
        if self._summoned and _u32.GetForegroundWindow() == hwnd:
            self._summoned = False
            if not self.topmost:
                self._set_z(False)
            self.root.lower()
            return
        if self.collapsed:
            self.toggle_collapse()
        self._summon_prev_fg = _u32.GetForegroundWindow()
        self._summon_own = False
        self._summoned = True
        _u32.ShowWindow(hwnd, 5)                             # SW_SHOW
        self._set_z(True)
        _u32.SetForegroundWindow(hwnd)
        self.root.focus_force()

    # ---------- 오류 처리 ----------
    def _mark_good(self):
        """5초간 정상 동작 → 지금 코드를 비상용 이전 버전으로 보관"""
        try:
            save_fallback()
        except Exception as e:
            log_error("비상용 사본 저장 실패", e)

    def _on_tk_error(self, exc, val, tb):
        log_error("화면 처리 중 오류", val)
        try:
            self._toast("오류가 기록됨 (data/error.log)", ms=4000)
        except Exception:
            pass

    def _show_banner(self, msg):
        """푸터에 다 안 들어가는 중요한 알림을 본문 위에 표시 (✕ 로 닫기)"""
        if self._banner is not None:
            self._banner.destroy()
        b = tk.Frame(self.main, bg=C["danger_bg"])
        b.pack(side="top", fill="x", before=self.body_wrap)
        self._txt(b, "✕", b.destroy, font=self.f_status, fg=C["danger_fg"],
                  hi=C["title"], bg=C["danger_bg"]).pack(side="right", anchor="n",
                                                           padx=S(10), pady=S(7))
        tk.Label(b, text=msg, font=self.f_status, bg=C["danger_bg"], fg=C["danger_fg"],
                 justify="left", anchor="w", wraplength=self.W - S(60)).pack(
            side="left", fill="x", padx=(S(13), 0), pady=S(7))
        self._banner = b

    def _persist(self, label="변경"):
        """저장. label: 되돌리기 목록에 남길 이름 (None 이면 기록 안 함)"""
        try:
            self.history.record(self.data, label)
        except Exception as e:
            log_error("되돌리기 기록 실패", e)
        try:
            save_data(self.data)
        except Exception as e:
            log_error("저장 실패", e)
            self._toast("저장 실패 — data/error.log", ms=5000)

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


def _toggle_chip(app, parent, text, on):
    b = tk.Label(parent, text=text, font=app.f_act, padx=S(9), pady=S(3), cursor="hand2")

    def style(v):
        b.configure(bg=C["imp_bg"] if v else C["chip_bg"],
                    fg=C["imp_fg"] if v else C["sub"])
    style(on)
    return b, style


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
        _accent_head(wrap, app, "메모 가져오기")

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=S(14), pady=S(12))

        # 어느 주에 넣을지: 이번 주 / 다음 주 (+ 다른 주를 보고 있으면 그 주)
        this_ws = monday_of(dt.date.today())
        next_ws = this_ws + dt.timedelta(days=7)
        opts = [(this_ws, "이번 주"), (next_ws, "다음 주")]
        if app.week_start not in (this_ws, next_ws):
            opts.append((app.week_start, "보는 주"))
            self.target = app.week_start
        elif app.week_start == next_ws or dt.date.today().weekday() >= 5:
            self.target = next_ws            # 주말엔 보통 다음 주 계획을 씀
        else:
            self.target = this_ws
        seg = tk.Frame(inner, bg=C["bg"])
        seg.pack(fill="x", pady=(0, S(10)))
        self.seg_btns = {}
        for ws_, name in opts:
            b = tk.Label(seg, text=f"{name} {ws_.month}/{ws_.day}~", font=app.f_act,
                         padx=S(9), pady=S(3), cursor="hand2")
            b.pack(side="left", padx=(0, S(5)))
            b.bind("<Button-1>", lambda e, w=ws_: self._pick_week(w))
            self.seg_btns[ws_] = b
        self._style_seg()

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

        tk.Label(inner, text="※ 선택한 주의 일정과 전체 목록이 메모 내용으로 바뀝니다 (완료 체크는 유지)",
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

    def _pick_week(self, ws):
        self.target = ws
        self._style_seg()
        self._refresh()

    def _style_seg(self):
        for ws_, b in self.seg_btns.items():
            on = ws_ == self.target
            b.configure(bg=C["accent"] if on else C["chip_bg"], fg="#ffffff" if on else C["sub"])

    def _line(self, e):
        tag = (e["label"] + " · ") if e.get("label") else ""
        t = tag + e["text"]
        t = t if len(t) <= 20 else t[:19] + "…"
        due = "  " + dday_info(e["date"])[0] if e.get("due") else ""
        return f"  {WEEKDAYS_KR[e['date'].weekday()]} {e['date'].month}/{e['date'].day}   {t}{due}\n"

    def _refresh(self):
        plan = plan_import(self.text.get("1.0", "end"), self.target)
        inweek, other, lists = plan["inweek"], plan["other"], plan["lists"]
        p = self.preview
        p.configure(state="normal")
        p.delete("1.0", "end")
        if not inweek and not other and not lists:
            p.insert("end", "아직 인식된 항목이 없습니다.\n\n", "m")
            p.insert("end", "====== [ 학교 일정 ] ======   → 주간\n<수요일>\n⦁ 할 일\n"
                            "[혜윰, ~11/29 일]   → 마감 D-day\n\n"
                            "---- [ 종강 후 할 일 ] ----   → 전체 목록\n⦁ 할 일", "m")
        else:
            p.insert("end", f"주간 {self.target.month}/{self.target.day}~  {len(inweek)}개\n", "h")
            for e in inweek:
                p.insert("end", self._line(e))
            if not inweek:
                p.insert("end", "  (없음)\n", "m")
            if other:
                p.insert("end", f"\n다른 주  {len(other)}개  (그 날짜에 추가)\n", "h")
                for e in other:
                    p.insert("end", self._line(e))
            if lists:
                p.insert("end", f"\n전체 목록  {len(lists)}개\n", "h")
                for L in lists:
                    dues = sum(1 for e in L["items"] if e["due_date"])
                    extra = f"  (마감 {dues})" if dues else ""
                    p.insert("end", f"  {L['name']}  ·  {len(L['items'])}개{extra}\n")
        p.configure(state="disabled")
        n = len(inweek) + len(other) + sum(len(L["items"]) for L in lists)
        self.apply_btn.configure(text=f"적용 ({n})" if n else "적용")

    def _apply(self):
        if self.app.apply_import(self.text.get("1.0", "end"), self.target):
            _close_modal(self.top)


# ------------------------------------------------------------------
# 메모로 보내기 (위젯 → 클립보드)
# ------------------------------------------------------------------
class ExportDialog:
    def __init__(self, app):
        self.app = app
        top, wrap = _modal(app)
        self.top = top
        ws = app.week_start
        we = ws + dt.timedelta(days=6)
        _accent_head(wrap, app, f"메모로 보내기 · {ws.strftime('%m/%d')}~{we.strftime('%m/%d')} 주")

        self.content = export_note(app.data, ws)
        app.copy_to_clipboard(self.content)

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=S(14), pady=S(12))
        tk.Label(inner, text="클립보드에 복사했습니다.", font=app.f_act_b, bg=C["bg"],
                 fg=C["accent_dk"]).pack(anchor="w")
        tk.Label(inner, text="Sticky Notes 메모에서 Ctrl+A → Ctrl+V 하면 바뀐 내용이 반영됩니다.\n"
                             "완료한 항목은 '✓' 로 표시되고, 다시 가져와도 완료로 인식됩니다.",
                 font=app.f_status, bg=C["bg"], fg=C["sub"], justify="left",
                 wraplength=S(310)).pack(anchor="w", pady=(S(2), S(8)))

        box = tk.Text(inner, height=16, font=app.f_act, wrap="word", relief="flat", bd=0,
                      bg=C["today_bg"], padx=S(8), pady=S(6))
        box.insert("1.0", self.content)
        box.configure(state="disabled")
        box.pack(fill="x", pady=(0, S(10)))

        btns = tk.Frame(inner, bg=C["bg"])
        btns.pack(fill="x")
        _dbtn(app, btns, "닫기", lambda: _close_modal(top), C["chip_bg"], C["text"]).pack(
            side="right", padx=(S(6), 0))
        _dbtn(app, btns, "다시 복사", self._copy, C["accent"], "#ffffff").pack(side="right")

        _place_modal(app, top, 340, 20)
        top.bind("<Escape>", lambda e: _close_modal(top))
        top.bind("<Return>", lambda e: _close_modal(top))
        app._toast("메모 형식으로 복사됨")

    def _copy(self):
        self.app.copy_to_clipboard(self.content)
        self.app._toast("다시 복사됨")


# ------------------------------------------------------------------
# 텍스트 입력 대화상자 (목록 / 목록 항목용)
# ------------------------------------------------------------------
class TextDialog:
    def __init__(self, app, title, initial, on_save, on_delete=None, important=None,
                 delete_label="삭제", confirm_delete=False, field_label="할 일",
                 show_due=False, due=None):
        self.app, self.on_save, self.on_delete = app, on_save, on_delete
        self.confirm_delete, self._armed = confirm_delete, False
        top, wrap = _modal(app)
        self.top = top
        _accent_head(wrap, app, title)

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=S(16), pady=S(14))

        tk.Label(inner, text=field_label, font=app.f_act, bg=C["bg"],
                 fg=C["sub"]).pack(anchor="w")
        self.entry = self._entry(inner)
        self.entry.pack(fill="x", pady=(S(4), S(4)), ipady=S(4))
        self.entry.insert(0, initial)
        if field_label == "할 일":
            tk.Label(inner, text="앞에 [과목] 을 붙이면 색 태그로 표시됩니다",
                     font=app.f_status, bg=C["bg"], fg=C["muted"]).pack(anchor="w")
        tk.Frame(inner, bg=C["bg"], height=S(8)).pack()

        self.due_entry = None
        if show_due:
            r = tk.Frame(inner, bg=C["bg"])
            r.pack(fill="x", pady=(0, S(10)))
            tk.Label(r, text="마감일", font=app.f_act, bg=C["bg"], fg=C["sub"]).pack(side="left")
            self.due_entry = self._entry(r, width=7)
            self.due_entry.pack(side="left", padx=(S(8), S(6)), ipady=S(2))
            d = from_iso(due)
            if d:
                self.due_entry.insert(0, f"{d.month}/{d.day}")
            tk.Label(r, text="예) 12/15  · 비우면 없음", font=app.f_status, bg=C["bg"],
                     fg=C["muted"]).pack(side="left")

        self.imp = important
        if important is not None:
            self.imp_btn, self._imp_style = _toggle_chip(app, inner, "중요 표시", important)
            self.imp_btn.pack(anchor="w", pady=(0, S(14)))
            self.imp_btn.bind("<Button-1>", lambda e: self._toggle_imp())

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

    def _entry(self, parent, width=None):
        kw = {"width": width} if width else {}
        return tk.Entry(parent, font=self.app.f_item, relief="solid", bd=1,
                        highlightthickness=1, highlightbackground=C["field_bd"],
                        highlightcolor=C["accent"], **kw)

    def _toggle_imp(self):
        self.imp = not self.imp
        self._imp_style(self.imp)

    def _save(self):
        text = self.entry.get().strip()
        if not text:
            self.entry.configure(highlightbackground=C["danger_fg"])
            return
        due = None
        if self.due_entry is not None and self.due_entry.get().strip():
            m = re.search(r"(\d{1,2})\s*[/\.\-]\s*(\d{1,2})", self.due_entry.get())
            d = _make_date(int(m.group(1)), int(m.group(2))) if m else None
            if not d:
                self.due_entry.configure(highlightbackground=C["danger_fg"])
                return
            due = iso(d)
        _close_modal(self.top)
        self.on_save(text, bool(self.imp), due)

    def _delete(self):
        if self.confirm_delete and not self._armed:
            self._armed = True
            self.del_btn.configure(text="한 번 더 누르면 삭제")
            return
        _close_modal(self.top)
        self.on_delete()


# ------------------------------------------------------------------
# 주간 항목 추가/편집 (카테고리 + D-day)
# ------------------------------------------------------------------
class ItemDialog:
    def __init__(self, app, day, item):
        self.app, self.day, self.item = app, day, item
        top, wrap = _modal(app)
        self.top = top
        title = "일정 편집" if item else "일정 추가"
        label = f" · {item['label']}" if item and item.get("label") else ""
        _accent_head(wrap, app, f"{title} · {day.month}/{day.day} ({WEEKDAYS_KR[day.weekday()]}){label}")

        inner = tk.Frame(wrap, bg=C["bg"])
        inner.pack(fill="both", expand=True, padx=S(16), pady=S(14))

        tk.Label(inner, text="할 일", font=app.f_act, bg=C["bg"], fg=C["sub"]).pack(anchor="w")
        self.entry = tk.Entry(inner, font=app.f_item, relief="solid", bd=1,
                              highlightthickness=1, highlightbackground=C["field_bd"],
                              highlightcolor=C["accent"])
        self.entry.pack(fill="x", pady=(S(4), S(4)), ipady=S(4))
        self.entry.insert(0, item.get("text", "") if item else "")
        tk.Label(inner, text="앞에 [과목] 을 붙이면 색 태그로 표시됩니다",
                 font=app.f_status, bg=C["bg"], fg=C["muted"]).pack(anchor="w", pady=(0, S(10)))

        tk.Label(inner, text="카테고리", font=app.f_act, bg=C["bg"], fg=C["sub"]).pack(anchor="w")
        cat_frame = tk.Frame(inner, bg=C["bg"])
        cat_frame.pack(fill="x", pady=(S(6), S(12)))
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

        self.due = bool(item.get("due")) if item else False
        self.due_btn, self._due_style = _toggle_chip(app, inner, "D-day 표시 (이 날짜가 마감)", self.due)
        self.due_btn.pack(anchor="w", pady=(0, S(12)))
        self.due_btn.bind("<Button-1>", lambda e: self._toggle_due())

        # 매주 반복: 요일 선택
        rule = find_rule(app.data, item.get("rid")) if item else None
        self.weekdays = set(rule["weekdays"]) if rule else set()
        tk.Label(inner, text="매주 반복", font=app.f_act, bg=C["bg"], fg=C["sub"]).pack(anchor="w")
        wd = tk.Frame(inner, bg=C["bg"])
        wd.pack(fill="x", pady=(S(6), S(4)))
        self.wd_btns = []
        for i, name in enumerate(WEEKDAYS_KR):
            b = tk.Label(wd, text=name, font=app.f_act, padx=S(7), pady=S(3), cursor="hand2")
            b.pack(side="left", padx=(0, S(4)))
            b.bind("<Button-1>", lambda e, i=i: self._toggle_wd(i))
            self.wd_btns.append(b)
        self._style_wd()
        hint = ("이 날 이후의 반복 일정이 모두 바뀝니다\n요일을 모두 끄면 반복이 끝납니다"
                if rule else "요일을 고르면 매주 그 요일에 자동으로 들어갑니다")
        tk.Label(inner, text=hint, font=app.f_status, bg=C["bg"], fg=C["muted"],
                 wraplength=S(290), justify="left").pack(anchor="w", pady=(0, S(14)))

        btns = tk.Frame(inner, bg=C["bg"])
        btns.pack(fill="x")
        if item:
            _dbtn(app, btns, "이번만 삭제" if item.get("rid") else "삭제", self._delete,
                  C["danger_bg"], C["danger_fg"]).pack(side="left")
        _dbtn(app, btns, "취소", lambda: _close_modal(top), C["chip_bg"], C["text"]).pack(
            side="right", padx=(S(6), 0))
        _dbtn(app, btns, "저장", self._save, C["accent"], "#ffffff").pack(side="right")

        _place_modal(app, top, 320, 90)
        self.entry.focus_set()
        top.bind("<Return>", lambda e: self._save())
        top.bind("<Escape>", lambda e: _close_modal(top))

    def _toggle_due(self):
        self.due = not self.due
        self._due_style(self.due)

    def _toggle_wd(self, i):
        self.weekdays ^= {i}
        self._style_wd()

    def _style_wd(self):
        for i, b in enumerate(self.wd_btns):
            on = i in self.weekdays
            b.configure(bg=C["accent"] if on else C["chip_bg"], fg="#ffffff" if on else C["sub"])

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
        self.app.save_item(self.day, self.item, text, self.cat, self.due, self.weekdays)

    def _delete(self):
        _close_modal(self.top)
        if self.item:
            self.app.delete_item(self.day, self.item)


def main():
    enable_dpi_awareness()
    install_error_hooks()
    wait = 8 if "--restarted" in sys.argv else 0
    if not acquire_single_instance(wait):
        return      # 이미 실행 중
    root = None
    try:
        root = tk.Tk()
        root.title("주간 일정")
        ScheduleWidget(root)
    except Exception as e:
        # 시작하다 죽으면: 기록하고, 보관해 둔 이전 버전으로 대신 실행
        log_error("시작 실패" + (" (비상용 이전 버전)" if FALLBACK_MODE else ""), e)
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass
        release_single_instance()
        launch_fallback()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
