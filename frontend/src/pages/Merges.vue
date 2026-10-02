<template>
  <div>
    <h1 class="brand">迁移单</h1>
    <p class="muted">任务合并产生的周格迁移清单；confirmed 可显式拆回（整单还原或整单拒绝）</p>
    <p v-if="err" class="err">{{ err }}</p>
    <ul class="list">
      <li v-for="m in rows" :key="m.id">
        <strong>#{{ m.id }} 《{{ m.title }}》</strong>
        <span class="muted"> {{ m.src_a_title }} + {{ m.src_b_title }} → {{ m.new_title }} · 迁 {{ m.migrated }} 格</span>
        <span class="chip" :class="{ coral: m.status==='confirmed' }">{{ m.status }}</span>
        <button class="ghost" style="margin-left:8px" @click="toggle(m.id)">{{ open===m.id ? '收起' : '清单' }}</button>
        <button v-if="m.status==='confirmed'" style="margin-left:8px" @click="splitBack(m.id)">拆回</button>
        <div v-if="open===m.id && detail" style="margin-top:8px">
          <div v-for="ln in detail.cells" :key="ln.id" class="muted">
            第{{ ln.week_id }}周 · 格#{{ ln.assignment_id }} · Day {{ ln.day }} · 任务 {{ ln.old_task_id }} → {{ ln.new_task_id }}
          </div>
          <p v-if="!detail.cells.length" class="muted">无迁移格</p>
        </div>
      </li>
    </ul>
    <p v-if="!rows.length" class="muted">暂无迁移单</p>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const rows = ref([])
const err = ref('')
const open = ref(null)
const detail = ref(null)
async function load() { rows.value = await api('/merges') }
async function toggle(id) {
  err.value = ''
  if (open.value === id) { open.value = null; detail.value = null; return }
  try { detail.value = await api('/merges/' + id); open.value = id }
  catch (e) { err.value = e.message }
}
async function splitBack(id) {
  err.value = ''
  try {
    await api('/merges/' + id + '/split-back', { method: 'POST', body: '{}' })
    open.value = null; detail.value = null
    await load()
  } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
