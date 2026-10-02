# Chorerota · 家庭值日轮转

底座：成员+任务 → round-robin 生成周表 → 申请对调 → 确认改表。

| 服务 | 端口 |
| --- | --- |
| 前端 | 5100 |
| API | 10100 |

```bash
docker compose up --build
pytest backend/app/tests
```

种子含 clean/dirty。0-1 空桩：`streak_badge` / `skip_week` / `chore_photo`。

任务拆合迁移（`task_merge` 模块）：任务页选两个 clean 任务 + 目标周 → 预览（将迁格数/目标标题，不写库）→ 确认合并（新任务、迁格、迁移清单同事务落库，看板任务名与清单同钉）。源任务有 pending 对调或脏任务即拒。迁移单页可查清单并显式拆回：清单格全数完好则整单还原并退役新任务，任一格漂移则整单拒绝。
