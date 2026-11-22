<script setup lang="ts">
  import { computed, ref, watch, nextTick, onBeforeUnmount } from 'vue'
  import { Chart, ScatterController, LinearScale, PointElement, LineElement } from 'chart.js'
  import type { LabState } from '../lab'

  Chart.register(ScatterController, LinearScale, PointElement, LineElement)
  const props = defineProps<{
    lab: LabState
    administrator: boolean
    api: (path: string, options?: RequestInit) => Promise<Response>
  }>()
  const config = ref({
    rows: 1000000,
    equipment: 120,
    days: 30,
    temperature_sensors: 1,
    current_sensors: 1,
    voltage_sensors: 1,
    failure_percent: 40,
    failure_modes: ['cooling_loss', 'capacitor_wear', 'resistance_growth'],
    noise: 1,
    missing_percent: 1,
    outlier_percent: 0.2,
    seed: 42,
  })
  const modes = [
    { value: 'cooling_loss', label: 'Perda de refrigeração' },
    { value: 'capacitor_wear', label: 'Desgaste de capacitores' },
    { value: 'resistance_growth', label: 'Aumento de resistência' },
  ]
  const submitting = ref(false)
  const error = ref('')
  const notice = ref('')
  const datasetId = ref('')
  const modelId = ref('')
  const target = ref<'health' | 'rul_hours'>('health')
  const maxTrainRows = ref(200000)
  const plot = ref<HTMLCanvasElement | null>(null)
  let chart: Chart<'scatter'> | null = null
  const busy = computed(
    () => submitting.value || props.lab.jobs.some((j) => ['queued', 'running'].includes(j.status))
  )
  const datasets = computed(() =>
    props.lab.jobs.filter((j) => j.kind === 'generate' && j.status === 'completed')
  )
  const selected = computed(
    () => props.lab.models.find((m) => m.id === modelId.value) ?? props.lab.models[0]
  )
  const metrics = computed(() => selected.value?.metrics.targets[target.value])
  const activeJob = computed(() =>
    props.lab.jobs.find((j) => ['queued', 'running'].includes(j.status))
  )

  watch(
    datasets,
    (rows) => {
      if (!datasetId.value && rows[0]) datasetId.value = rows[0].id
    },
    { immediate: true }
  )

  async function submit(path: string, body: unknown): Promise<void> {
    submitting.value = true
    error.value = ''
    notice.value = ''
    try {
      await props.api(path, { method: 'POST', body: JSON.stringify(body) })
      notice.value = path.includes('/models/')
        ? 'Versão selecionada. A inferência deve carregá-la nos próximos segundos; confira a versão em uso nos Insights.'
        : 'Job enviado. O progresso aparecerá abaixo.'
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Falha ao iniciar job'
    } finally {
      submitting.value = false
    }
  }

  function number(value: number, digits = 3): string {
    return value.toLocaleString('pt-BR', { maximumFractionDigits: digits })
  }

  function state(value: string): string {
    return (
      (
        {
          queued: 'Na fila',
          running: 'Executando',
          completed: 'Concluído',
          failed: 'Falhou',
        } as Record<string, string>
      )[value] ?? value
    )
  }

  function attributeName(name: string): string {
    const extra: Record<string, string> = {
      power_kw: 'Potência de entrada',
      hour_sin: 'Ciclo diário (seno)',
      hour_cos: 'Ciclo diário (cosseno)',
      thermal_residual: 'Desvio térmico',
      voltage_sag: 'Queda de tensão',
    }
    const labels: Record<string, string> = {
      last: 'última leitura',
      mean: 'média',
      std: 'desvio padrão',
      trend_per_hour: 'tendência por hora',
      max: 'máximo',
    }
    if (extra[name]) return extra[name]
    for (const [prefix, label] of [
      ['temperature_c_', 'Temperatura'],
      ['current_a_', 'Corrente'],
      ['voltage_v_', 'Tensão'],
    ]) {
      if (prefix && name.startsWith(prefix)) {
        const stat = name.slice(prefix.length)
        return `${label} — ${labels[stat] ?? stat}`
      }
    }
    return name
  }

  async function draw(): Promise<void> {
    await nextTick()
    chart?.destroy()
    chart = null
    if (!plot.value || !metrics.value) return
    const samples = metrics.value.predicted_vs_actual
    const max = Math.max(1, ...samples.flatMap((p) => [p.actual, p.predicted]))
    chart = new Chart(plot.value, {
      type: 'scatter',
      data: {
        datasets: [
          {
            label: 'Amostra de teste',
            data: samples.map((p) => ({ x: p.actual, y: p.predicted })),
            backgroundColor: '#ccff00',
            pointRadius: 3,
          },
          {
            label: 'Previsão ideal',
            data: [
              { x: 0, y: 0 },
              { x: max, y: max },
            ],
            showLine: true,
            pointRadius: 0,
            borderColor: '#899872',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#b9c5a3' } } },
        scales: {
          x: {
            title: { display: true, text: 'Valor real', color: '#b9c5a3' },
            ticks: { color: '#b9c5a3' },
          },
          y: {
            title: { display: true, text: 'Valor previsto', color: '#b9c5a3' },
            ticks: { color: '#b9c5a3' },
          },
        },
      },
    })
  }
  watch(() => `${selected.value?.id ?? ''}:${target.value}`, draw, { immediate: true })
  onBeforeUnmount(() => chart?.destroy())
</script>

<template>
  <section class="painel-dados laboratorio">
    <h2>Laboratório de Dados</h2>
    <p>Simule a vida dos módulos de potência para criar os dados de manutenção preditiva.</p>
    <p v-if="!administrator">
      Seu papel permite acompanhar os resultados. A geração e o treinamento são reservados ao
      administrador.
    </p>
    <form @submit.prevent="submit('/api/lab/generate', config)">
      <fieldset :disabled="!administrator || busy" class="grade-laboratorio">
        <legend>Configuração da geração</legend>
        <label
          >Leituras completas<input
            v-model.number="config.rows"
            type="number"
            min="1000000"
            max="3000000"
            step="10000"
            required
        /></label>
        <label
          >Equipamentos<input
            v-model.number="config.equipment"
            type="number"
            min="20"
            max="300"
            required
        /></label>
        <label
          >Período em dias<input
            v-model.number="config.days"
            type="number"
            min="2"
            max="365"
            required
        /></label>
        <details class="lab-advanced">
          <summary>Ajustar sensores, falhas e qualidade dos dados</summary>
          <div class="grade-laboratorio">
            <label
              >Sensores de temperatura por equipamento<input
                v-model.number="config.temperature_sensors"
                type="number"
                min="1"
                max="4"
                required
            /></label>
            <label
              >Sensores de corrente por equipamento<input
                v-model.number="config.current_sensors"
                type="number"
                min="1"
                max="4"
                required
            /></label>
            <label
              >Sensores de tensão por equipamento<input
                v-model.number="config.voltage_sensors"
                type="number"
                min="1"
                max="4"
                required
            /></label>
            <label
              >Equipamentos que falham (%)<input
                v-model.number="config.failure_percent"
                type="number"
                min="5"
                max="95"
                step="1"
                required
            /></label>
            <label
              >Intensidade do ruído<input
                v-model.number="config.noise"
                type="number"
                min="0.2"
                max="5"
                step="0.1"
                required
            /></label>
            <label
              >Leituras faltantes (%)<input
                v-model.number="config.missing_percent"
                type="number"
                min="0"
                max="20"
                step="0.1"
                required
            /></label>
            <label
              >Valores absurdos (%)<input
                v-model.number="config.outlier_percent"
                type="number"
                min="0"
                max="5"
                step="0.1"
                required
            /></label>
            <label
              >Semente aleatória<input
                v-model.number="config.seed"
                type="number"
                min="0"
                max="2147483647"
                required
            /></label>
            <div class="modos-falha">
              <span>Modos de falha</span
              ><label v-for="mode in modes" :key="mode.value"
                ><input v-model="config.failure_modes" type="checkbox" :value="mode.value" />{{
                  mode.label
                }}</label
              >
            </div>
          </div>
        </details>
        <button type="submit" :disabled="!config.failure_modes.length">Gerar dados</button>
      </fieldset>
    </form>
    <p>
      Cada leitura reúne os sensores do equipamento. Um milhão de leituras completas contém pelo
      menos três milhões de medições individuais.
    </p>
    <p v-if="error" class="aviso-erro" role="alert">{{ error }}</p>
    <p v-if="notice" class="aviso-comando" role="status">{{ notice }}</p>
    <div v-if="activeJob" class="progresso-job" role="status">
      <strong
        >{{ activeJob.kind === 'generate' ? 'Gerando dados' : 'Treinando modelos' }} —
        {{ number(activeJob.progress, 1) }}%</strong
      >
      <progress :value="activeJob.progress" max="100"></progress>
      <p>{{ activeJob.message }}</p>
    </div>
    <div class="tabela-scroll">
      <table>
        <thead>
          <tr>
            <th>Job</th>
            <th>Tipo</th>
            <th>Estado</th>
            <th>Progresso</th>
            <th>Resultado</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in lab.jobs" :key="job.id">
            <td :title="job.id">{{ job.id.slice(0, 8) }}</td>
            <td>{{ job.kind === 'generate' ? 'Geração' : 'Treinamento' }}</td>
            <td>{{ state(job.status) }}</td>
            <td>{{ number(job.progress, 1) }}%</td>
            <td>
              {{
                job.result?.rows
                  ? `${number(job.result.rows, 0)} leituras / ${number(job.result.sensor_readings ?? 0, 0)} medições`
                  : job.message
              }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="painel-dados laboratorio">
    <h2>Treinamento</h2>
    <p>
      Dois regressores: saúde de 0 a 100 e vida útil restante em horas, limitada ao horizonte de 168
      horas.
    </p>
    <form
      @submit.prevent="
        submit('/api/lab/train', {
          dataset_id: datasetId,
          seed: config.seed,
          max_train_rows: maxTrainRows,
        })
      "
    >
      <fieldset :disabled="!administrator || busy || !datasets.length" class="grade-laboratorio">
        <legend>Conjunto de dados e limite de treinamento</legend>
        <label
          >Conjunto de dados<select v-model="datasetId" required>
            <option v-for="dataset in datasets" :key="dataset.id" :value="dataset.id">
              {{ dataset.id.slice(0, 8) }} · {{ number(dataset.result?.rows ?? 0, 0) }} leituras
            </option>
          </select></label
        >
        <label
          >Máximo de amostras de treino<input
            v-model.number="maxTrainRows"
            type="number"
            min="10000"
            max="300000"
            step="10000"
            required
        /></label>
        <button type="submit" :disabled="!datasetId">Treinar os dois modelos</button>
      </fieldset>
    </form>
    <p>
      O limite controla o consumo de memória. Todos os equipamentos participam da divisão; as
      amostras são selecionadas dentro de cada grupo, após calcular os atributos.
    </p>
    <div v-if="selected">
      <label
        >Versão<select v-model="modelId">
          <option value="">Mais recente</option>
          <option v-for="model in lab.models" :key="model.id" :value="model.id">
            {{ model.id.slice(0, 8) }}{{ model.active ? ' · versão aprovada' : '' }}
          </option>
        </select></label
      >
      <p :class="selected.accepted ? 'resultado-aprovado' : 'aviso-erro'">
        {{
          selected.accepted
            ? 'Os dois modelos venceram o baseline em MAE e RMSE.'
            : 'Versão reprovada: pelo menos um modelo não venceu o baseline em MAE e RMSE.'
        }}
      </p>
      <button
        v-if="administrator && selected.accepted && !selected.active"
        :disabled="submitting"
        @click="submit(`/api/lab/models/${selected.id}/activate`, {})"
      >
        Usar esta versão na inferência
      </button>
      <details>
        <summary>Como os dados foram divididos</summary>
        <p>
          Treino: {{ number(selected.metrics.sample_counts.train, 0) }} · Validação:
          {{ number(selected.metrics.sample_counts.validation, 0) }} · Teste:
          {{ number(selected.metrics.sample_counts.test, 0) }}
        </p>
        <p>
          Equipamentos: {{ selected.metrics.equipment_split.train.length }} /
          {{ selected.metrics.equipment_split.validation.length }} /
          {{ selected.metrics.equipment_split.test.length }}. Grupos sem equipamentos
          compartilhados.
        </p>
      </details>
      <p>
        MAE é o erro médio; RMSE destaca erros maiores (menor é melhor nos dois). R² mede o ajuste
        (mais próximo de 1 é melhor). Baseline é a comparação com uma previsão simples pela média.
      </p>
      <label
        >Alvo<select v-model="target">
          <option value="health">Índice de saúde (0–100)</option>
          <option value="rul_hours">Vida útil restante (horas)</option>
        </select></label
      >
      <div v-if="metrics" class="tabela-scroll">
        <table>
          <thead>
            <tr>
              <th>Métrica</th>
              <th>Validação</th>
              <th>Teste</th>
              <th>Baseline no teste</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="key in ['mae', 'rmse', 'r2'] as const" :key="key">
              <td>{{ key.toUpperCase() }}</td>
              <td>{{ number(metrics.validation[key]) }}</td>
              <td>{{ number(metrics.test[key]) }}</td>
              <td>{{ number(metrics.baseline[key]) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="grafico-regressao">
        <canvas ref="plot" aria-label="Valores previstos contra reais" role="img"></canvas>
      </div>
      <details>
        <summary>Quais leituras mais influenciam a previsão?</summary>
        <h3>Atributos mais importantes</h3>
        <p>Aumento do MAE quando cada atributo é embaralhado, em uma amostra do teste.</p>
        <ol>
          <li v-for="attribute in metrics?.feature_importance.slice(0, 8)" :key="attribute.feature">
            {{ attributeName(attribute.feature) }}: {{ number(attribute.importance) }}
          </li>
        </ol>
      </details>
      <p>
        A inferência acompanha a versão aprovada sem reiniciar o serviço. Veja a versão efetivamente
        carregada e os indicadores na aba Insights de IA.
      </p>
    </div>
    <p v-else>Nenhum treinamento concluído.</p>
  </section>
</template>
