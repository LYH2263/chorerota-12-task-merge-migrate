"""任务拆合迁移：两个 clean 任务合并为新任务，按选定周迁格并留存迁移清单。

取舍拍板：拆回走「整单还原或整单拒绝」——清单中每格必须仍挂在合并任务上，
任一格漂移（被改/被删）即整单拒绝，不做部分还原；还原成功后合并任务退役为 dirty，
不再作源/目标，也不再进 generate。
"""

class MergeError(Exception):
    """业务拒绝：任务缺失/脏任务/pending 对调/格子漂移/状态不符。"""


def _task(c, tid):
    return c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()


def _check_sources(c, task_a, task_b):
    """源任务校验：存在、互异、均 clean、无 pending 对调引用。"""
    if task_a == task_b:
        raise MergeError("same_task")
    ta, tb = _task(c, task_a), _task(c, task_b)
    if ta is None or tb is None:
        raise MergeError("task_missing")
    if ta["data_quality"] != "clean" or tb["data_quality"] != "clean":
        raise MergeError("dirty_source")  # 脏任务不可作源/目标
    pending = c.execute(
        "SELECT COUNT(*) n FROM swap_requests "
        "WHERE status='pending' AND (a_task IN (?,?) OR b_task IN (?,?))",
        (task_a, task_b, task_a, task_b)).fetchone()["n"]
    if pending:
        raise MergeError("pending_swap")  # 源任务存在 pending 对调，拒合并
    return ta, tb


def _cells(c, task_a, task_b, week_ids):
    """选定周内挂在两个源任务上的格子；未选中的周不动。"""
    if not week_ids:
        return []
    marks = ",".join("?" for _ in week_ids)
    return [dict(r) for r in c.execute(
        f"SELECT id, week_id, task_id FROM assignments "
        f"WHERE task_id IN (?,?) AND week_id IN ({marks}) ORDER BY week_id, id",
        (task_a, task_b, *week_ids))]


def _title(ta, tb, title):
    return (title or "").strip() or f"{ta['title']}+{tb['title']}"


def preview_merge(c, task_a, task_b, week_ids, title=""):
    """只读预览：目标标题 + 将迁格数（按周分列），不写库。"""
    ta, tb = _check_sources(c, task_a, task_b)
    cells = _cells(c, task_a, task_b, week_ids)
    per_week = {}
    for cell in cells:
        per_week[cell["week_id"]] = per_week.get(cell["week_id"], 0) + 1
    return {
        "title": _title(ta, tb, title),
        "migrate_count": len(cells),
        "weeks": [{"week_id": w, "count": n} for w, n in sorted(per_week.items())],
        "sources": [dict(ta), dict(tb)],
    }


def confirm_merge(c, task_a, task_b, week_ids, title=""):
    """确认合并：新任务 + 迁格 + 迁移清单同一事务落库（看板任务名与清单同钉）。"""
    ta, tb = _check_sources(c, task_a, task_b)
    title = _title(ta, tb, title)
    new_id = c.execute(
        "INSERT INTO tasks(title,weight,data_quality) VALUES (?,?,?)",
        (title, ta["weight"] + tb["weight"], "clean")).lastrowid
    cells = _cells(c, task_a, task_b, week_ids)
    merge_id = c.execute(
        "INSERT INTO task_merges(title,new_task_id,src_a,src_b,status,migrated) "
        "VALUES (?,?,?,?,?,?)",
        (title, new_id, task_a, task_b, "confirmed", len(cells))).lastrowid
    for cell in cells:
        c.execute("UPDATE assignments SET task_id=? WHERE id=?", (new_id, cell["id"]))
        c.execute(
            "INSERT INTO task_merge_cells(merge_id,week_id,assignment_id,old_task_id,new_task_id) "
            "VALUES (?,?,?,?,?)",
            (merge_id, cell["week_id"], cell["id"], cell["task_id"], new_id))
    return {"merge_id": merge_id, "new_task_id": new_id, "title": title, "migrated": len(cells)}


def list_merges(c):
    return [dict(r) for r in c.execute(
        "SELECT m.*, ta.title src_a_title, tb.title src_b_title, tn.title new_title "
        "FROM task_merges m "
        "LEFT JOIN tasks ta ON ta.id=m.src_a "
        "LEFT JOIN tasks tb ON tb.id=m.src_b "
        "LEFT JOIN tasks tn ON tn.id=m.new_task_id ORDER BY m.id DESC")]


def merge_detail(c, merge_id):
    for m in list_merges(c):
        if m["id"] == merge_id:
            m["cells"] = [dict(r) for r in c.execute(
                "SELECT mc.*, a.day, a.member_id FROM task_merge_cells mc "
                "LEFT JOIN assignments a ON a.id=mc.assignment_id "
                "WHERE mc.merge_id=? ORDER BY mc.week_id, mc.id", (merge_id,))]
            return m
    return None


def split_back(c, merge_id):
    """显式拆回：清单格全数完好则还原旧 task_id 并退役新任务；任一漂移整单拒。"""
    m = c.execute("SELECT * FROM task_merges WHERE id=?", (merge_id,)).fetchone()
    if m is None:
        raise MergeError("merge_missing")
    if m["status"] != "confirmed":
        raise MergeError("not_confirmed")
    lines = [dict(r) for r in c.execute(
        "SELECT * FROM task_merge_cells WHERE merge_id=?", (merge_id,))]
    for ln in lines:
        a = c.execute("SELECT task_id FROM assignments WHERE id=?",
                      (ln["assignment_id"],)).fetchone()
        if a is None or a["task_id"] != ln["new_task_id"]:
            raise MergeError("cells_drifted")  # 格子已漂移，整单拒绝
    for ln in lines:
        c.execute("UPDATE assignments SET task_id=? WHERE id=?",
                  (ln["old_task_id"], ln["assignment_id"]))
    c.execute("UPDATE task_merges SET status='split_back' WHERE id=?", (merge_id,))
    c.execute("UPDATE tasks SET data_quality='dirty' WHERE id=?", (m["new_task_id"],))
    return {"merge_id": merge_id, "restored": len(lines)}
