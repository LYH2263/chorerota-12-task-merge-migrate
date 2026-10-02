<template>
  <div>
    <h1 class="brand">任务</h1>
    <form @submit.prevent="add">
      <input v-model="title" placeholder="任务名" />
      <button type="submit">添加</button>
    </form>
    <ul class="list">
      <li v-for="t in rows" :key="t.id">
        <strong>{{ t.title }}</strong>
        <span class="muted"> · 权重 {{ t.weight }} · {{ t.data_quality }}</span>
      </li>
    </ul>

    <div class="week-card" style="margin-top:16px">
      <header>合并任务（迁移周格）</header>
      <p class="muted">两个 clean 任务合为新任务，仅选中周的格子迁走；源任务有 pending 对调则拒合</p>
      <label>源任务 A
        <select v-model.number="merge.task_a">
          <option v-for="t in cleanTasks" :key="t.id" :value="t.id">{{ t.title }}</option>
        </select>
      </label>
      <label>源任务 B
        <select v-model.number="merge.task_b">
          <option v-for="t in cleanTasks" :key="t.id" :value="t.id">{{ t.title }}</option>
        </select>
      </label>
      <label>新任务名 <input v-model="merge.title" placeholder="留空则 A+B" /></label>
      <div style="margin-bottom:10px">
        <span class="muted">迁移周：</span>
        <label v-for="w in weeks" :key="w.id" style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">
          <input type="checkbox" :value="w.id" v-model="merge.week_ids" style="width:auto;margin:0" /> {{ w.label }}
        </label>
      </div>
      <button class="ghost" @click="preview">预览</button>
      <button style="margin-left:8px" @click="confirmMerge">确认合并</button>
      <p v-if="previewInfo" class="muted" style="margin-top:8px">
        将迁 {{ previewInfo.migrate_count }} 格 → 《{{ previewInfo.title }}》
        <span v-for="w in previewInfo.weeks" :key="w.week_id" class="chip">{{ weekLabel(w.week_id) }} {{ w.count }} 格</span>
      </p>
      <p v-if="done" class="muted" style="margin-top:8px">{{ done }}，可去「迁移单」查看清单或拆回</p>
      <p v-if="err" class="err">{{ err }}</p>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
const rows = ref([])
const weeks = ref([])
const title = ref('')
const err = ref('')
const done = ref('')
const previewInfo = ref(null)
const merge = ref({ task_a: null, task_b: null, title: '', week_ids: [] })
const cleanTasks = computed(() => rows.value.filter(t => t.data_quality === 'clean'))
function weekLabel(id) { const w = weeks.value.find(w => w.id === id); return w ? w.label : '第' + id + '周' }
async function load() {
  rows.value = await api('/tasks')
  weeks.value = await api('/weeks')
}
async function add() {
  if (!title.value.trim()) return
  await api('/tasks', { method: 'POST', body: JSON.stringify({ title: title.value }) })
  title.value = ''; await load()
}
function mergeBody() { return JSON.stringify(merge.value) }
async function preview() {
  err.value = ''; done.value = ''; previewInfo.value = null
  try { previewInfo.value = await api('/tasks/merge/preview', { method: 'POST', body: mergeBody() }) }
  catch (e) { err.value = e.message }
}
async function confirmMerge() {
  err.value = ''; done.value = ''
  try {
    const r = await api('/tasks/merge', { method: 'POST', body: mergeBody() })
    previewInfo.value = null
    merge.value = { task_a: null, task_b: null, title: '', week_ids: [] }
    await load()
    done.value = `已合并为《${r.title}》，迁 ${r.migrated} 格`
  } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
