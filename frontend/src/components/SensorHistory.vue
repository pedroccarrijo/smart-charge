<script setup lang="ts">
  import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
  import {
    Chart,
    LineController,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
  } from 'chart.js'
  Chart.register(LineController, CategoryScale, LinearScale, PointElement, LineElement)
  const props = defineProps<{ api: (path: string, options?: RequestInit) => Promise<Response> }>()
  type Row = {
    timestamp: string
    temperature_c: number | null
    current_a: number | null
    voltage_v: number | null
  }
  const device = ref('ponto01'),
    minutes = ref(30),
    field = ref<'temperature_c' | 'current_a' | 'voltage_v'>('temperature_c')
  const rows = ref<Row[]>([]),
    error = ref(''),
    loading = ref(false),
    canvas = ref<HTMLCanvasElement | null>(null),
    interval = ref(0)
  const labels = {
    temperature_c: 'Temperatura (°C)',
    current_a: 'Corrente (A)',
    voltage_v: 'Tensão (V)',
  }
  let chart: Chart<'line'> | null = null,
    controller: AbortController | null = null
  async function draw(): Promise<void> {
    await nextTick()
    chart?.destroy()
    chart = null
    if (!canvas.value || !rows.value.length) return
    chart = new Chart(canvas.value, {
      type: 'line',
      data: {
        labels: rows.value.map((row) => new Date(row.timestamp).toLocaleTimeString('pt-BR')),
        datasets: [
          {
            label: labels[field.value],
            data: rows.value.map((row) => row[field.value]),
            borderColor: '#ccff00',
            pointRadius: 0,
            borderWidth: 2,
            spanGaps: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { ticks: { color: '#a4aa9a', maxTicksLimit: 8 } },
          y: { ticks: { color: '#a4aa9a' } },
        },
        plugins: { legend: { labels: { color: '#f5f6ef' } } },
      },
    })
  }
  async function load(): Promise<void> {
    controller?.abort()
    const current = new AbortController()
    controller = current
    loading.value = true
    error.value = ''
    rows.value = []
    chart?.destroy()
    chart = null
    try {
      const data = await (
        await props.api(
          `/api/telemetry/history?device_id=${device.value}&minutes=${minutes.value}`,
          { signal: current.signal }
        )
      ).json()
      if (current.signal.aborted) return
      rows.value = data.readings
      interval.value = data.aggregation_seconds
      await draw()
    } catch (e) {
      if (!current.signal.aborted)
        error.value = e instanceof Error ? e.message : 'Falha ao consultar histórico'
    } finally {
      if (controller === current) loading.value = false
    }
  }
  watch(field, draw)
  onMounted(load)
  onBeforeUnmount(() => {
    controller?.abort()
    chart?.destroy()
  })
</script>

<template>
  <section class="painel-dados sensor-history">
    <h3>Histórico dos sensores</h3>
    <p>Leituras armazenadas no InfluxDB. Selecione uma estação e atualize a consulta.</p>
    <form class="history-filters" @submit.prevent="load">
      <label
        >Estação<select v-model="device">
          <option v-for="id in ['01', '02', '03']" :key="id" :value="`ponto${id}`">
            Estação {{ id }}
          </option>
        </select></label
      >
      <label
        >Período<select v-model.number="minutes">
          <option :value="5">Últimos 5 minutos</option>
          <option :value="30">Últimos 30 minutos</option>
          <option :value="1440">Últimas 24 horas</option>
        </select></label
      >
      <label
        >Sensor<select v-model="field">
          <option v-for="(label, key) in labels" :key="key" :value="key">{{ label }}</option>
        </select></label
      >
      <button :disabled="loading">{{ loading ? 'Consultando…' : 'Atualizar histórico' }}</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!loading && !rows.length">
      Ainda não há leituras nesse período. Aguarde o simulador publicar dados.
    </p>
    <div v-show="rows.length" class="history-chart">
      <canvas ref="canvas" role="img" :aria-label="`Histórico de ${labels[field]}`"></canvas>
    </div>
    <p v-if="rows.length" class="muted">
      {{ rows.length }} pontos · médias a cada {{ interval }} segundos · consulta histórica, sem
      atualização automática.
    </p>
  </section>
</template>

<style scoped>
  p {
    margin: 12px 0;
    line-height: 1.6;
  }
  .history-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: end;
  }
  label {
    display: grid;
    gap: 8px;
  }
  .history-chart {
    height: 260px;
    margin-top: 20px;
  }
  .muted {
    color: #a4aa9a;
    font-size: 0.85rem;
  }
</style>
