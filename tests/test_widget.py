# -*- coding: utf-8 -*-
"""
위젯 핵심 로직 테스트 (화면 없이 실행)
    python -m unittest discover -s tests
위젯의 '새로고침'도 재시작 전에 이 테스트를 돌려, 실패하면 새 버전으로 바꾸지 않습니다.
"""
import os
import json
import shutil
import tempfile
import unittest
import importlib.util
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("schedule_widget",
                                               os.path.join(ROOT, "schedule_widget.pyw"))
sw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sw)

TODAY = dt.date.today()
WS = sw.monday_of(TODAY)
FAR = WS + dt.timedelta(days=16)


def _md(d):
    return f"{d.month}/{d.day}"


def sample_note():
    """실제 사용하는 메모와 같은 형식의 예시 (날짜는 오늘 기준으로 생성)"""
    fri, sun = WS + dt.timedelta(days=4), WS + dt.timedelta(days=6)
    return f"""====== [ 동아리 ] ======
[스터디, ~{_md(sun)} 일]
⦁    5주차 발표 자료 제출

[축제, {_md(fri)} 금]
⦁    0900~ 부스 운영

[기말, ~{_md(FAR)}]
⦁    [자료구조] 시험

====== [ 학교 일정 ] ======
<월요일>
⦁    -
<화요일>
⦁    -
<수요일>
⦁    운영체제 복습
⦁    ✓ 네트워크 과제

<목요일>
⦁    영어 단어

<일요일>
⦁    -


---- [시험 준비] ----
⦁    [자료구조] 요약 노트
⦁    [운영체제] 기출 풀기 ~{_md(FAR)}
⦁    ✓ [영어] 단어장



---- [방학 계획] ----
⦁    자격증 공부 **
⦁    *여행가기*
⦁    포트폴리오 정리
"""


def fresh():
    return sw._with_defaults({})


def imported(text, ws=WS, data=None):
    data = data if data is not None else fresh()
    sw.merge_import(data, sw.plan_import(text, ws), ws)
    return data


def snapshot(data):
    week = sorted((k, it["text"], it.get("category"), it.get("label"), bool(it.get("due")),
                   bool(it.get("deadline")), bool(it.get("important")), bool(it.get("done")))
                  for k, lst in data["items"].items() for it in lst)
    lists = [(L["name"], [(it["text"], bool(it.get("important")), bool(it.get("done")),
                           it.get("due_date")) for it in L["items"]]) for L in data["lists"]]
    return week, lists


class ParserTest(unittest.TestCase):
    def setUp(self):
        self.res = sw.parse_sticky_note(sample_note())

    def test_weekday_items_strip_bullets_and_skip_placeholders(self):
        got = [(e["widx"], e["text"], e["done"]) for e in self.res["weekday"]]
        self.assertEqual(got, [(2, "운영체제 복습", False), (2, "네트워크 과제", True),
                               (3, "영어 단어", False)])

    def test_sections(self):
        self.assertEqual(self.res["sections"], ["동아리", "학교 일정"])
        self.assertEqual(self.res["day_sections"], ["학교 일정"])

    def test_dated_groups_label_and_deadline(self):
        d = {e["label"]: e for e in self.res["dated"]}
        self.assertTrue(d["스터디"]["deadline"])
        self.assertFalse(d["축제"]["deadline"])
        self.assertEqual(d["축제"]["date"], WS + dt.timedelta(days=4))
        self.assertEqual(d["기말"]["text"], "[자료구조] 시험")

    def test_lists_due_done_important(self):
        self.assertEqual([L["name"] for L in self.res["lists"]], ["시험 준비", "방학 계획"])
        exam = self.res["lists"][0]["items"]
        self.assertEqual(exam[1]["text"], "[운영체제] 기출 풀기")
        self.assertEqual(exam[1]["due_date"], sw.iso(FAR))
        self.assertTrue(exam[2]["done"])
        plan = self.res["lists"][1]["items"]
        self.assertEqual([(i["text"], i["important"]) for i in plan],
                         [("자격증 공부", True), ("여행가기", True), ("포트폴리오 정리", False)])

    def test_clean_text(self):
        self.assertEqual(sw.clean_text("✓ 할 일 **"), ("할 일", True, True))
        self.assertEqual(sw.clean_text("  보통   항목 "), ("보통 항목", False, False))


class ImportExportTest(unittest.TestCase):
    def test_round_trip_is_lossless_and_stable(self):
        a = imported(sample_note())
        a["lists"][1]["items"][2]["done"] = True
        out1 = sw.export_note(a, WS)
        b = imported(out1)
        self.assertEqual(snapshot(a), snapshot(b))
        self.assertEqual(out1, sw.export_note(b, WS))

    def test_reimport_keeps_checkmarks(self):
        data = imported(sample_note())
        thu = sw.iso(WS + dt.timedelta(days=3))
        data["items"][thu][0]["done"] = True
        data["lists"][1]["items"][0]["done"] = True
        imported(sample_note(), data=data)
        self.assertTrue(data["items"][thu][0]["done"])
        self.assertTrue(data["lists"][1]["items"][0]["done"])

    def test_other_week_item_saved_once_with_deadline(self):
        data = imported(sample_note())
        imported(sample_note(), data=data)
        far = data["items"][sw.iso(FAR)]
        self.assertEqual(len(far), 1)
        self.assertTrue(far[0]["due"] and far[0]["deadline"])

    def test_import_into_next_week(self):
        nxt = WS + dt.timedelta(days=7)
        data = imported(sample_note(), ws=nxt)
        wed = data["items"][sw.iso(nxt + dt.timedelta(days=2))]
        self.assertEqual([i["text"] for i in wed], ["운영체제 복습", "네트워크 과제"])


class DataSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = {k: getattr(sw, k) for k in ("DATA_DIR", "DATA_FILE", "BACKUP_DIR", "LOG_FILE")}
        sw.DATA_DIR = self.tmp
        sw.DATA_FILE = os.path.join(self.tmp, "schedule.json")
        sw.BACKUP_DIR = os.path.join(self.tmp, "backups")
        sw.LOG_FILE = os.path.join(self.tmp, "error.log")

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(sw, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_corrupt_file_recovers_from_latest_backup(self):
        old, good = fresh(), fresh()
        good["lists"] = [{"name": "최신 백업", "items": []}]
        self._write(os.path.join(sw.BACKUP_DIR, "schedule-2026-01-01.json"), json.dumps(old))
        self._write(os.path.join(sw.BACKUP_DIR, "schedule-2026-01-02.json"), json.dumps(good))
        self._write(sw.DATA_FILE, '{ "items": ')                 # 깨진 파일
        data, notice = sw.load_data()
        self.assertEqual(data["lists"][0]["name"], "최신 백업")
        self.assertIn("2026-01-02", notice)
        corrupt = [n for n in os.listdir(self.tmp) if n.startswith("schedule.corrupt-")]
        self.assertEqual(len(corrupt), 1)
        self.assertTrue(os.path.exists(sw.LOG_FILE))

    def test_corrupt_file_without_backup_is_preserved(self):
        self._write(sw.DATA_FILE, "not json")
        data, notice = sw.load_data()
        self.assertEqual(data["items"], {})
        self.assertIsNotNone(notice)
        corrupt = [n for n in os.listdir(self.tmp) if n.startswith("schedule.corrupt-")]
        with open(os.path.join(self.tmp, corrupt[0]), encoding="utf-8") as f:
            self.assertEqual(f.read(), "not json")

    def test_daily_backup_and_prune(self):
        for i in range(20):
            self._write(os.path.join(sw.BACKUP_DIR, f"schedule-2000-01-{i + 1:02d}.json"), "{}")
        sw.save_data(fresh())        # 파일이 없을 땐 백업할 것도 없음
        sw.save_data(fresh())        # 오늘 첫 백업 + 오래된 것 정리
        names = sorted(os.listdir(sw.BACKUP_DIR))
        self.assertEqual(len(names), sw.BACKUP_KEEP)
        self.assertIn(f"schedule-{TODAY:%Y-%m-%d}.json", names)

    def test_backup_once_per_day(self):
        sw.save_data(fresh())
        sw.save_data(fresh())
        first = fresh()
        first["lists"] = [{"name": "나중 변경", "items": []}]
        sw.save_data(first)
        with open(os.path.join(sw.BACKUP_DIR, f"schedule-{TODAY:%Y-%m-%d}.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["lists"], [])      # 그날 처음 상태가 유지됨


class OperationsTest(unittest.TestCase):
    def test_carry_over_moves_only_unfinished_plain_items(self):
        data = fresh()
        y = TODAY - dt.timedelta(days=1)
        a = {"id": "a", "text": "어제 할 일", "done": False}
        b = {"id": "b", "text": "끝낸 일", "done": True}
        c = {"id": "c", "text": "마감 지난 일", "done": False, "due": True}
        data["items"][sw.iso(y)] = [a, b, c]
        self.assertEqual([it["id"] for _, it in sw.carry_over_candidates(data, TODAY)], ["a"])
        self.assertEqual(sw.carry_over(data, TODAY), 1)
        self.assertEqual([i["id"] for i in data["items"][sw.iso(TODAY)]], ["a"])
        self.assertEqual([i["id"] for i in data["items"][sw.iso(y)]], ["b", "c"])

    def test_move_item_removes_empty_day(self):
        data = fresh()
        it = {"id": "x", "text": "t"}
        data["items"]["2026-01-05"] = [it]
        sw.move_item(data, "2026-01-05", it, dt.date(2026, 1, 6))
        self.assertNotIn("2026-01-05", data["items"])
        self.assertEqual(data["items"]["2026-01-06"], [it])

    def test_progress(self):
        data = imported(sample_note())
        self.assertEqual(sw.week_progress(data, WS), (1, 5))
        self.assertEqual(sw.list_progress(data), (1, 6))

    def test_dday_info(self):
        self.assertEqual(sw.dday_info(TODAY)[0], "D-day")
        self.assertEqual(sw.dday_info(TODAY + dt.timedelta(days=3))[0], "D-3")
        self.assertEqual(sw.dday_info(TODAY - dt.timedelta(days=2))[0], "D+2")


class ReorderTest(unittest.TestCase):
    def test_reorder_within_day_and_move_to_other_day(self):
        data = fresh()
        a, b, c = ({"id": x, "text": x} for x in "abc")
        data["items"]["2026-01-05"] = [a, b, c]
        sw.reorder_item(data, "2026-01-05", a, "2026-01-05", 3)        # 맨 아래로
        self.assertEqual([i["id"] for i in data["items"]["2026-01-05"]], ["b", "c", "a"])
        sw.reorder_item(data, "2026-01-05", a, "2026-01-05", 0)        # 맨 위로
        self.assertEqual([i["id"] for i in data["items"]["2026-01-05"]], ["a", "b", "c"])
        sw.reorder_item(data, "2026-01-05", b, "2026-01-06", 0)
        self.assertEqual([i["id"] for i in data["items"]["2026-01-06"]], ["b"])
        self.assertEqual([i["id"] for i in data["items"]["2026-01-05"]], ["a", "c"])

    def test_move_list_item(self):
        L1 = {"name": "1", "items": [{"id": "a"}, {"id": "b"}]}
        L2 = {"name": "2", "items": [{"id": "c"}]}
        sw.move_list_item(L1, L1["items"][0], L1, 2)
        self.assertEqual([i["id"] for i in L1["items"]], ["b", "a"])
        sw.move_list_item(L1, L1["items"][1], L2, 0)
        self.assertEqual([i["id"] for i in L2["items"]], ["a", "c"])
        self.assertEqual([i["id"] for i in L1["items"]], ["b"])


class RecurringTest(unittest.TestCase):
    def setUp(self):
        self.data = fresh()
        self.rule = sw.add_recurring(self.data, "헬스", "운동", [0, 2, 4], WS)
        self.end = WS + dt.timedelta(days=6)

    def week_texts(self, ws=WS):
        return {i: [it["text"] for it in self.data["items"].get(sw.iso(ws + dt.timedelta(days=i)), [])]
                for i in range(7)}

    def test_materialize_once_per_day(self):
        self.assertEqual(sw.materialize_recurring(self.data, WS, self.end), 3)
        self.assertEqual(sw.materialize_recurring(self.data, WS, self.end), 0)
        w = self.week_texts()
        self.assertEqual([i for i in range(7) if w[i]], [0, 2, 4])

    def test_not_before_start(self):
        self.rule["start"] = sw.iso(WS + dt.timedelta(days=3))
        sw.materialize_recurring(self.data, WS, self.end)
        self.assertEqual([i for i, t in self.week_texts().items() if t], [4])

    def test_deleted_or_moved_occurrence_not_recreated(self):
        sw.materialize_recurring(self.data, WS, self.end)
        mon, wed = sw.iso(WS), sw.iso(WS + dt.timedelta(days=2))
        it = self.data["items"][mon][0]
        sw.skip_occurrence(self.data, it)
        self.data["items"].pop(mon)
        moved = self.data["items"][wed][0]
        sw.reorder_item(self.data, wed, moved, sw.iso(WS + dt.timedelta(days=3)), 0)
        self.assertEqual(sw.materialize_recurring(self.data, WS, self.end), 0)

    def test_end_recurring_drops_future_unfinished(self):
        nxt = WS + dt.timedelta(days=7)
        sw.materialize_recurring(self.data, WS, nxt + dt.timedelta(days=6))
        self.data["items"][sw.iso(nxt)][0]["done"] = True            # 완료한 건 남김
        sw.end_recurring(self.data, self.rule["id"], WS + dt.timedelta(days=2))
        self.assertEqual(sw.materialize_recurring(self.data, WS, nxt + dt.timedelta(days=6)), 0)
        days = sorted(k for k, lst in self.data["items"].items() for it in lst)
        self.assertEqual(days, [sw.iso(WS), sw.iso(WS + dt.timedelta(days=2)), sw.iso(nxt)])

    def test_update_changes_future_text_and_weekdays(self):
        sw.materialize_recurring(self.data, WS, self.end)
        self.data["items"][sw.iso(WS)][0]["done"] = True
        sw.update_recurring(self.data, self.rule["id"], WS, "헬스 1시간", "운동", [0, 4])
        sw.materialize_recurring(self.data, WS, self.end)
        w = self.week_texts()
        self.assertEqual(w[0], ["헬스"])               # 이미 완료한 건 그대로
        self.assertEqual(w[2], [])                     # 뺀 요일은 사라짐
        self.assertEqual(w[4], ["헬스 1시간"])

    def test_not_carried_over(self):
        y = TODAY - dt.timedelta(days=1)
        self.rule["start"] = sw.iso(y)
        self.rule["weekdays"] = [y.weekday()]
        sw.materialize_recurring(self.data, y, y)
        self.assertEqual(sw.carry_over_candidates(self.data, TODAY), [])

    def test_export_import_round_trip_keeps_link(self):
        sw.materialize_recurring(self.data, WS, self.end)
        note = sw.export_note(self.data, WS)
        self.assertIn("헬스 (매주)", note)
        again = imported(note, data=self.data)
        sw.materialize_recurring(again, WS, self.end)
        self.assertEqual(len(again["recurring"]), 1)
        w = self.week_texts()
        self.assertEqual([i for i in range(7) if w[i]], [0, 2, 4])
        self.assertTrue(all(len(t) <= 1 for t in w.values()))       # 중복 없음
        self.assertEqual(note, sw.export_note(again, WS))

    def test_import_without_repeat_lines_keeps_recurring(self):
        sw.materialize_recurring(self.data, WS, self.end)
        imported("====== [ 학교 ] ======\n<화요일>\n⦁    과제\n", data=self.data)
        sw.materialize_recurring(self.data, WS, self.end)
        w = self.week_texts()
        self.assertEqual(w[0], ["헬스"])
        self.assertEqual(w[1], ["과제"])

    def test_repeat_mark_in_note_creates_rule(self):
        data = imported("====== [ 운동 ] ======\n<월요일>\n⦁    요가 (매주)\n<목요일>\n⦁    요가 (매주)\n")
        self.assertEqual(len(data["recurring"]), 1)
        self.assertEqual(data["recurring"][0]["weekdays"], [0, 3])
        nxt = WS + dt.timedelta(days=7)
        sw.materialize_recurring(data, nxt, nxt + dt.timedelta(days=6))
        self.assertEqual([it["text"] for it in data["items"][sw.iso(nxt + dt.timedelta(days=3))]], ["요가"])


class HistoryTest(unittest.TestCase):
    def test_undo_redo(self):
        data = fresh()
        h = sw.History(data)
        data["items"]["2026-01-05"] = [{"id": "a", "text": "첫 일정"}]
        self.assertTrue(h.record(data, "추가"))
        data["items"]["2026-01-05"][0]["done"] = True
        h.record(data, "완료 체크")
        label, data = h.undo(data)
        self.assertEqual(label, "완료 체크")
        self.assertFalse(data["items"]["2026-01-05"][0].get("done"))
        label, data = h.undo(data)
        self.assertEqual(data["items"], {})
        self.assertIsNone(h.undo(data))
        label, data = h.redo(data)
        self.assertEqual(label, "추가")
        self.assertEqual(data["items"]["2026-01-05"][0]["text"], "첫 일정")

    def test_window_changes_and_auto_changes_not_recorded(self):
        data = fresh()
        h = sw.History(data)
        data["window"]["px"] = 10
        self.assertFalse(h.record(data, "창 이동"))
        data["items"]["x"] = []
        self.assertFalse(h.record(data, None))           # 자동 생성은 기록 안 함
        self.assertEqual(h.undo_stack, [])

    def test_undo_keeps_window_and_new_change_clears_redo(self):
        data = fresh()
        h = sw.History(data)
        data["lists"].append({"name": "L", "items": []})
        h.record(data, "새 목록")
        data["window"]["px"] = 99
        _, data = h.undo(data)
        self.assertEqual(data["window"]["px"], 99)
        data["lists"].append({"name": "M", "items": []})
        h.record(data, "새 목록")
        self.assertIsNone(h.redo(data))

    def test_limit(self):
        data = fresh()
        h = sw.History(data, limit=5)
        for i in range(12):
            data["items"][str(i)] = []
            h.record(data, "추가")
        self.assertEqual(len(h.undo_stack), 5)


if __name__ == "__main__":
    unittest.main()
