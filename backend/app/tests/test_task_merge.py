import os, tempfile
import pytest
from app.db import connect
from app import seed
from app.modules import task_merge
from app.modules.task_merge import MergeError

def fresh_db():
    """每测例一座新库：种子含 clean 任务 1洗碗/2倒垃圾/3扫地、dirty 任务 4、周 1。"""
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
    seed.init_db()
    return connect()

def gen(c, week_id, tids, days=2, mid=1):
    for d in range(days):
        for t in tids:
            c.execute("INSERT INTO assignments(week_id,day,task_id,member_id) VALUES (?,?,?,?)",
                      (week_id, d, t, mid))
    c.commit()

def snapshot(c):
    out = {}
    for t in ("tasks", "assignments", "task_merges", "task_merge_cells"):
        out[t] = [tuple(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY 1")]
    return out

def test_preview_does_not_write_db():
    c = fresh_db(); gen(c, 1, [1, 2], days=3)
    before = snapshot(c)
    p = task_merge.preview_merge(c, 1, 2, [1], "厨房组合")
    assert p["title"] == "厨房组合"
    assert p["migrate_count"] == 6
    assert p["weeks"] == [{"week_id": 1, "count": 6}]
    assert snapshot(c) == before  # 预览不写库
    c.close()

def test_confirm_pins_board_name_and_manifest():
    c = fresh_db()
    gen(c, 1, [1, 2], days=2)
    c.execute("INSERT INTO weeks(label,status) VALUES ('第13周','ready')")
    gen(c, 2, [1], days=1)  # 未选中的周
    r = task_merge.confirm_merge(c, 1, 2, [1], "洗倒一体"); c.commit()
    assert r["migrated"] == 4
    # 看板同钉：第1周格子全部挂新任务名
    board = c.execute(
        "SELECT t.title FROM assignments a JOIN tasks t ON t.id=a.task_id "
        "WHERE a.week_id=1").fetchall()
    assert len(board) == 4 and all(row["title"] == "洗倒一体" for row in board)
    # 清单同钉：逐格对上，且新任务权重为源权重之和
    d = task_merge.merge_detail(c, r["merge_id"])
    assert d["status"] == "confirmed" and d["migrated"] == 4
    week1_ids = {row["id"] for row in c.execute("SELECT id FROM assignments WHERE week_id=1")}
    assert {ln["assignment_id"] for ln in d["cells"]} == week1_ids
    assert {ln["old_task_id"] for ln in d["cells"]} == {1, 2}
    assert c.execute("SELECT weight FROM tasks WHERE id=?",
                     (r["new_task_id"],)).fetchone()["weight"] == 2
    # 未选中的第2周保持旧任务格不动
    assert [row["task_id"] for row in c.execute(
        "SELECT task_id FROM assignments WHERE week_id=2")] == [1]
    c.close()

def test_pending_swap_rejects_merge():
    c = fresh_db(); gen(c, 1, [1, 2])
    c.execute("INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note) "
              "VALUES (1,0,1,1,2,'pending','')")
    c.commit()
    with pytest.raises(MergeError, match="pending_swap"):
        task_merge.confirm_merge(c, 1, 2, [1], "x")
    with pytest.raises(MergeError, match="pending_swap"):
        task_merge.preview_merge(c, 1, 2, [1], "x")
    c.close()

def test_dirty_or_same_task_rejected():
    c = fresh_db(); gen(c, 1, [1, 4])
    with pytest.raises(MergeError, match="dirty_source"):
        task_merge.confirm_merge(c, 1, 4, [1], "x")  # 脏任务不可作源
    with pytest.raises(MergeError, match="same_task"):
        task_merge.preview_merge(c, 1, 1, [1], "x")
    c.close()

def test_split_back_restores_and_retires():
    c = fresh_db(); gen(c, 1, [1, 2], days=2)
    r = task_merge.confirm_merge(c, 1, 2, [1], "组合"); c.commit()
    out = task_merge.split_back(c, r["merge_id"]); c.commit()
    assert out["restored"] == 4
    tids = sorted(row["task_id"] for row in c.execute(
        "SELECT task_id FROM assignments WHERE week_id=1"))
    assert tids == [1, 1, 2, 2]  # 旧周格还原
    m = task_merge.merge_detail(c, r["merge_id"])
    assert m["status"] == "split_back"
    # 新任务退役为 dirty，不可再作源
    assert c.execute("SELECT data_quality FROM tasks WHERE id=?",
                     (r["new_task_id"],)).fetchone()["data_quality"] == "dirty"
    with pytest.raises(MergeError, match="dirty_source"):
        task_merge.confirm_merge(c, r["new_task_id"], 3, [1], "y")
    with pytest.raises(MergeError, match="not_confirmed"):
        task_merge.split_back(c, r["merge_id"])  # 重复拆回拒绝
    c.close()

def test_split_back_rejects_drifted_cells():
    c = fresh_db(); gen(c, 1, [1, 2], days=2)
    r = task_merge.confirm_merge(c, 1, 2, [1], "组合"); c.commit()
    victim = c.execute("SELECT id FROM assignments WHERE week_id=1 LIMIT 1").fetchone()["id"]
    c.execute("UPDATE assignments SET task_id=3 WHERE id=?", (victim,))  # 格子漂移
    c.commit()
    with pytest.raises(MergeError, match="cells_drifted"):
        task_merge.split_back(c, r["merge_id"])
    # 整单拒绝：其余格也未还原
    left = c.execute("SELECT COUNT(*) n FROM assignments WHERE task_id=?",
                     (r["new_task_id"],)).fetchone()["n"]
    assert left == 3
    c.close()
