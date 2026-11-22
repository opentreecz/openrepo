<template>
  <v-container>
    <h1>Maintenance</h1>
    <v-alert v-if="!store.state.is_superuser" type="warning">Superuser access required.</v-alert>
    <template v-else>
      <h2 class="mt-4">Storage audit</h2>
      <p class="my-4">Compare live repository indexes with files on the worker. The audit reads package
        contents to verify checksums and can take time on large repositories. No packages are changed.</p>
      <v-btn color="primary" :disabled="busy" @click="start">Run storage audit</v-btn>
      <p class="my-3" role="status">{{ status }}</p>
      <v-alert v-if="error" type="error">{{ error }}</v-alert>
      <template v-if="report">
        <v-alert v-if="report.counts.Incomplete" type="warning">Incomplete coverage. Review the reported errors.</v-alert>
        <h2>Findings</h2>
        <p>Unreferenced candidates at least seven days old: {{ report.candidate_bytes.toLocaleString() }} bytes.</p>
        <ul class="ml-5"><li v-for="(count, kind) in report.counts" :key="kind">{{ kind }}: {{ count }}</li></ul>
        <a :href="`/api/maintenance/storage-audits/${id}/manifest/`">Download all findings (JSON Lines)</a>
        <h3 class="mt-4">Review files</h3>
        <p>Check candidates to include them in a review list. Filename warnings and recovery copies
          are for investigation. Exporting a list does not move or remove files.</p>
        <form class="d-flex flex-wrap align-center ga-2 my-3" @submit.prevent="filter">
          <label>Finding <select v-model="kind">
            <option value="">All findings</option>
            <option v-for="category in Object.keys(report.counts)" :key="category">{{ category }}</option>
          </select></label>
          <label>Path <input v-model="query" type="search" placeholder="Contains…"></label>
          <v-btn type="submit" :disabled="loading">Filter</v-btn>
        </form>
        <p aria-live="polite">{{ selected.size }} selected · {{ selectedBytes.toLocaleString() }} bytes</p>
        <v-btn :disabled="!selected.size" @click="downloadSelection">Export selected list</v-btn>
        <v-btn variant="text" :disabled="!selected.size" @click="selected.clear()">Clear selection</v-btn>
        <p v-if="loading" role="status">Loading findings…</p>
        <p v-else-if="!rows.length">No matching findings.</p>
        <v-table v-if="rows.length" class="mt-3">
          <thead><tr><th>Select</th><th>Finding</th><th>Exact path</th><th>Details</th></tr></thead>
          <tbody><tr v-for="(row, i) in rows" :key="i">
            <td><input v-if="selectable(row)" type="checkbox" :checked="selected.has(row.path)"
              :aria-label="`Include ${row.path} in review list`" @change="toggle(row)"></td>
            <td>{{ row.kind }}</td><td><code>{{ row.path }}</code></td>
            <td><div v-for="(value, key) in details(row)" :key="key">{{ key }}: {{ value }}</div></td>
          </tr></tbody>
        </v-table>
        <div class="d-flex align-center ga-2">
          <v-btn variant="text" :disabled="loading || page === 0" @click="loadPage(page - 1)">Previous</v-btn>
          <span>Page {{ page + 1 }}</span>
          <v-btn variant="text" :disabled="loading || next === null" @click="loadPage(page + 1)">Next</v-btn>
        </div>
      </template>
    </template>
  </v-container>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import http from '@/http_common'
import store from '@/store'

interface Finding { kind: string; path: string; [key: string]: unknown }
interface Report { counts: Record<string, number>; candidate_bytes: number; preview: Finding[] }
const details = (row: Finding) => Object.fromEntries(Object.entries(row).filter(([k]) => !['kind', 'path'].includes(k)))
const base = '/maintenance/storage-audits/'
const key = 'openrepo-storage-audit'
const id = ref('')
const report = ref<Report>()
const status = ref('')
const error = ref('')
const busy = ref(false)
let timer: ReturnType<typeof setTimeout>
let stopped = false
let started = 0
const rows = ref<Finding[]>([])
const selected = ref(new Map<string, Finding>())
const selectedBytes = computed(() => [...selected.value.values()].reduce((sum, row) => sum + Number(row.bytes), 0))
const kind = ref('')
const query = ref('')
const loading = ref(false)
const page = ref(0)
const next = ref<number | null>(null)
let offsets = [0]
let params = { kind: '', search: '' }
let revision = 0
function selectable(row: Finding) {
  return row.kind === 'Unreferenced storage candidate' && !report.value?.counts.Incomplete
}
function toggle(row: Finding) {
  if (!selectable(row)) return
  if (selected.value.has(row.path)) selected.value.delete(row.path)
  else selected.value.set(row.path, row)
}
function downloadSelection() {
  const body = JSON.stringify({audit: id.value, purpose: 'Review only', files: [...selected.value.values()]}, null, 2)
  const url = window.URL.createObjectURL(new window.Blob([body], {type: 'application/json'}))
  const link = document.createElement('a')
  link.href = url
  link.download = `storage-review-${id.value}.json`
  link.click()
  setTimeout(() => window.URL.revokeObjectURL(url), 1000)
}
async function loadPage(index: number) {
  const current = ++revision
  loading.value = true
  error.value = ''
  try {
    const { data } = await http.get(`${base}${id.value}/findings/`, { params: { ...params, after: offsets[index] } })
    if (current !== revision || stopped) return
    rows.value = data.rows
    page.value = index
    next.value = data.next
    if (data.next !== null) offsets[index + 1] = data.next
  } catch (e) {
    if (current === revision) failed(e)
  } finally { if (current === revision) loading.value = false }
}
function filter() {
  offsets = [0]
  next.value = null
  page.value = 0
  rows.value = []
  params = { kind: kind.value, search: query.value }
  return loadPage(0)
}

function failed(e: unknown) {
  error.value = axios.isAxiosError(e) ? e.response?.data?.detail || e.message : String(e)
  busy.value = false
  status.value = ''
}
async function poll() {
  try {
    const { data } = await http.get(`${base}${id.value}/`)
    if (stopped) return
    if (data.state === 'SUCCESS') {
      report.value = data.report
      busy.value = false
      status.value = 'Audit finished.'
      await filter()
    } else if (['FAILURE', 'REVOKED'].includes(data.state)) {
      failed(data.detail || 'Audit stopped.')
    } else if (Date.now() - started > 86400000) {
      failed('Audit status expired. Start a new audit.')
    } else {
      status.value = 'Waiting for the worker to finish. You can return to this page later in this tab.'
      timer = setTimeout(poll, 4000)
    }
  } catch (e) { failed(e) }
}
async function start() {
  busy.value = true
  revision++
  selected.value.clear()
  kind.value = ''
  query.value = ''
  error.value = ''
  report.value = undefined
  status.value = 'Queueing audit…'
  try {
    const { data } = await http.post(base)
    id.value = data.id
    started = Date.now()
    window.sessionStorage.setItem(key, JSON.stringify([id.value, started]))
    if (!stopped) await poll()
  } catch (e) { failed(e) }
}
onMounted(() => {
  const saved = window.sessionStorage.getItem(key)
  if (store.state.is_superuser && saved) {
    const [previous, timestamp] = JSON.parse(saved)
    if (Date.now() - timestamp < 86400000) {
      id.value = previous
      started = timestamp
      busy.value = true
      poll()
    }
  }
})
onBeforeUnmount(() => { stopped = true; clearTimeout(timer) })
</script>
