"""task_merge 测例：预览不写库、确认后看板与迁移清单同钉、pending 冲突拒、脏任务拒、拆回还原/拒。

纯 stdlib 即可运行（不依赖 fastapi）；pytest 下同样可跑。
"""
import os, tempfile
from app.db import connect
from app import seed
from app.modules import task_merge as tm

def fresh_db():
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
    seed.init_db()  # 种子：成员1-3 clean，任务1-3 clean、任务4 dirty，周1-2
    return connect()

def add_cells(c, week_id, task_ids, days=2):
    mid = 1
    for d in range(days):
        for t in task_ids:
            c.execute("INSERT INTO assignments(week_id,day,task_id,member_id) VALUES (?,?,?,?)",
                      (week_id, d, t, mid))
            mid = mid % 3 + 1
    c.commit()

def raises_reason(fn, *args):
    try:
        fn(*args)
    except tm.MergeError as e:
        return e
    raise AssertionError("expected MergeError")

def test_preview_does_not_write():
    c = fresh_db()
    add_cells(c, 1, [1, 2])
    before = [dict(r) for r in c.execute("SELECT * FROM assignments")]
    p = tm.preview_merge(c, 1, 2, "餐后收拾", [1])
    assert p["would_migrate"] == 4 and p["target_title"] == "餐后收拾"
    assert p["per_week"][0]["task_a_cells"] == 2 and p["per_week"][0]["task_b_cells"] == 2
    after = [dict(r) for r in c.execute("SELECT * FROM assignments")]
    assert before == after  # assignments 不动
    assert c.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 4      # 不建新任务
    assert c.execute("SELECT COUNT(*) c FROM task_merges").fetchone()["c"] == 0
    assert c.execute("SELECT COUNT(*) c FROM task_merge_cells").fetchone()["c"] == 0
    c.close()

def test_confirm_migrates_selected_weeks_and_manifest_pins_board():
    c = fresh_db()
    add_cells(c, 1, [1, 2, 3])   # 选中周：含无关任务3
    add_cells(c, 2, [1, 2])      # 未选中周
    r = tm.apply_merge(c, 1, 2, "餐后收拾", [1]); c.commit()
    new_id = r["new_task_id"]
    assert r["migrated"] == 4
    w1 = [dict(x) for x in c.execute("SELECT * FROM assignments WHERE week_id=1")]
    migrated = [x for x in w1 if x["task_id"] == new_id]
    assert len(migrated) == 4
    assert sum(1 for x in w1 if x["task_id"] == 3) == 2          # 无关任务格不动
    w2 = [dict(x) for x in c.execute("SELECT * FROM assignments WHERE week_id=2")]
    assert {x["task_id"] for x in w2} == {1, 2}                  # 未选中周保持旧任务格
    # 看板与迁移清单同钉：看板新标题格集合 == 清单格集合，标题同源
    manifest = [dict(x) for x in c.execute(
        "SELECT * FROM task_merge_cells WHERE merge_id=? AND status='migrated'", (r["merge_id"],))]
    assert {m["assignment_id"] for m in manifest} == {x["id"] for x in migrated}
    assert all(m["new_task_id"] == new_id for m in manifest)
    assert {m["old_task_id"] for m in manifest} == {1, 2}
    title = c.execute("SELECT title FROM tasks WHERE id=?", (new_id,)).fetchone()["title"]
    assert title == "餐后收拾"
    listed = tm.list_merges(c)
    assert listed[0]["title"] == "餐后收拾" and len(listed[0]["cells"]) == 4
    assert {cell["new_task_title"] for cell in listed[0]["cells"]} == {"餐后收拾"}
    c.close()

def test_pending_swap_blocks_merge():
    c = fresh_db()
    add_cells(c, 1, [1, 2, 3])
    c.execute("INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note)"
              " VALUES (1,0,1,1,2,'pending','')")                # 挂在源任务1上
    c.execute("INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note)"
              " VALUES (1,0,3,1,3,'confirmed','')")              # 非 pending 不拦
    c.commit()
    e1 = raises_reason(tm.preview_merge, c, 1, 2, "x", [1])
    e2 = raises_reason(tm.apply_merge, c, 1, 2, "x", [1])
    assert e1.reason == e2.reason == "pending_swap_conflict"
    assert e1.detail["swap_ids"]
    assert c.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 4
    assert c.execute("SELECT COUNT(*) c FROM task_merges").fetchone()["c"] == 0
    # 与源任务无关的 pending 对调不拦合并
    c.execute("UPDATE swap_requests SET a_task=3, b_task=3 WHERE status='pending'"); c.commit()
    r = tm.apply_merge(c, 1, 2, "x", [1]); c.commit()
    assert r["migrated"] == 4
    c.close()

def test_dirty_same_missing_sources_rejected():
    c = fresh_db()
    assert raises_reason(tm.preview_merge, c, 1, 4, "x", [1]).reason == "task_dirty"   # 脏任务不可作源
    assert raises_reason(tm.preview_merge, c, 4, 1, "x", [1]).reason == "task_dirty"
    assert raises_reason(tm.preview_merge, c, 1, 1, "x", [1]).reason == "same_task"
    assert raises_reason(tm.preview_merge, c, 1, 99, "x", [1]).reason == "task_missing"
    assert raises_reason(tm.preview_merge, c, 1, 2, "x", []).reason == "no_weeks"
    assert raises_reason(tm.preview_merge, c, 1, 2, "x", [99]).reason == "week_missing"
    c.close()

def test_split_restores_migrated_cells():
    c = fresh_db()
    add_cells(c, 1, [1, 2])
    before = {r["id"]: r["task_id"] for r in c.execute("SELECT id,task_id FROM assignments WHERE week_id=1")}
    r = tm.apply_merge(c, 1, 2, "合并任务", [1]); c.commit()
    s = tm.split_merge(c, r["merge_id"]); c.commit()
    assert s["restored"] == 4
    after = {r["id"]: r["task_id"] for r in c.execute("SELECT id,task_id FROM assignments WHERE week_id=1")}
    assert before == after                                       # 旧周格还原
    assert c.execute("SELECT status FROM task_merges WHERE id=?", (r["merge_id"],)).fetchone()["status"] == "split"
    cells = [dict(x) for x in c.execute("SELECT status FROM task_merge_cells WHERE merge_id=?", (r["merge_id"],))]
    assert cells and all(x["status"] == "restored" for x in cells)
    t = c.execute("SELECT data_quality FROM tasks WHERE id=?", (r["new_task_id"],)).fetchone()
    assert t["data_quality"] == "archived"                       # 新任务退役，不可再作源
    assert raises_reason(tm.split_merge, c, r["merge_id"]).reason == "not_confirmed"
    c.close()

def test_split_rejected_when_cells_unrestorable():
    c = fresh_db()
    add_cells(c, 1, [1, 2])
    r = tm.apply_merge(c, 1, 2, "合并任务", [1]); c.commit()
    c.execute("DELETE FROM assignments WHERE week_id=1"); c.commit()  # 模拟重新生成周表
    e = raises_reason(tm.split_merge, c, r["merge_id"])
    assert e.reason == "cells_not_restorable" and e.detail["week_ids"] == [1]
    # 拒绝后不留半拆状态
    assert c.execute("SELECT status FROM task_merges WHERE id=?", (r["merge_id"],)).fetchone()["status"] == "confirmed"
    assert c.execute("SELECT data_quality FROM tasks WHERE id=?", (r["new_task_id"],)).fetchone()["data_quality"] == "clean"
    c.close()

def test_split_rejected_when_pending_swap_on_new_task():
    c = fresh_db()
    add_cells(c, 1, [1, 2])
    r = tm.apply_merge(c, 1, 2, "合并任务", [1]); c.commit()
    c.execute("INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note)"
              " VALUES (1,0,?,1,?,'pending','')", (r["new_task_id"], r["new_task_id"]))
    c.commit()
    assert raises_reason(tm.split_merge, c, r["merge_id"]).reason == "pending_swap_conflict"
    c.close()
