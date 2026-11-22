<script setup lang="ts">
  import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
  import { createTwinScene } from '../three/twin-scene'
  import { fresh, level, pointFor, predictionFor, reading } from '../twin'
  import type { ChargingPoint, DeviceComponent } from '../twin'
  import type { InsightsState } from '../insights'

  const props = defineProps<{
    points: ChargingPoint[]
    components: DeviceComponent[]
    insights: InsightsState
    connected: boolean
    frameAt: number
    canCommand: boolean
    busy: string[]
  }>()
  const emit = defineEmits<{
    command: [point: ChargingPoint, action: string, value: boolean | number]
  }>()
  const host = ref<HTMLElement | null>(null)
  const selectedId = ref('ponto01.module')
  const error = ref('')
  const compatible = ref(false)
  const clock = ref(Date.now())
  const limit = ref(100)
  const samples = ref<Record<string, { timestamp: string; value: number }[]>>({})
  const selected = computed(() => props.components.find((c) => c.id === selectedId.value))
  const point = computed(() =>
    selected.value ? pointFor(props.points, selected.value.device_id) : undefined
  )
  const prediction = computed(() =>
    selected.value ? predictionFor(props.insights, selected.value.device_id) : undefined
  )
  const live = computed(() => fresh(point.value, props.connected, props.frameAt, clock.value))
  const liveCount = computed(
    () => props.points.filter((p) => fresh(p, props.connected, props.frameAt, clock.value)).length
  )
  const value = computed(() =>
    live.value && selected.value ? reading(selected.value, point.value, prediction.value) : null
  )
  const chart = computed(() => (live.value ? (samples.value[selectedId.value] ?? []) : []))
  const locked = computed(
    () =>
      !live.value ||
      !point.value ||
      point.value.commands_enabled === false ||
      props.busy.includes(`ponto${point.value.ponto}`)
  )
  let scene: ReturnType<typeof createTwinScene> | undefined
  let timer: number | undefined

  function state(component: DeviceComponent): string {
    const p = pointFor(props.points, component.device_id),
      ai = predictionFor(props.insights, component.device_id)
    return level(
      component,
      reading(component, p, ai),
      ai,
      fresh(p, props.connected, props.frameAt, clock.value),
      p?.telemetry?.automatic_limit_active
    )
  }
  function stateText(component: DeviceComponent): string {
    return (
      { normal: 'Normal', warning: 'Atenção', critical: 'Crítico', nodata: 'Sem dados' } as Record<
        string,
        string
      >
    )[state(component)]
  }
  function number(n: number | null | undefined, digits = 1): string {
    return n == null ? '—' : n.toLocaleString('pt-BR', { maximumFractionDigits: digits })
  }
  function unit(component: DeviceComponent | undefined): string {
    return component
      ? ((
          {
            temperature_c: '°C',
            current_a: 'A',
            voltage_v: 'V',
            power_limit_percent: '%',
          } as Record<string, string>
        )[component.telemetry_key ?? ''] ?? '')
      : ''
  }
  function display(): string {
    if (value.value == null) return 'Sem dados atuais'
    if (typeof value.value === 'boolean') return value.value ? 'Fechado' : 'Aberto'
    return `${number(value.value)} ${selected.value?.kind === 'equipment' ? '/ 100' : unit(selected.value)}`
  }
  function path(): string {
    const rows = chart.value
    const values = rows.map((r) => r.value),
      low = Math.min(...values),
      high = Math.max(...values)
    return rows
      .map(
        (row, i) =>
          `${i ? 'L' : 'M'}${(i / Math.max(1, rows.length - 1)) * 260},${65 - ((row.value - low) / Math.max(0.1, high - low)) * 55}`
      )
      .join(' ')
  }
  function command(action: string, value: boolean | number): void {
    if (point.value && !locked.value) emit('command', point.value, action, value)
  }

  watch(
    () => props.frameAt,
    () => {
      for (const component of props.components) {
        const p = pointFor(props.points, component.device_id),
          ai = predictionFor(props.insights, component.device_id)
        if (!fresh(p, props.connected, props.frameAt, Date.now())) continue
        const result = reading(component, p, ai)
        const timestamp = component.kind === 'equipment' ? ai?.source_timestamp : p?.horario
        if (result == null || !timestamp) continue
        const rows = samples.value[component.id] ?? (samples.value[component.id] = [])
        if (rows[rows.length - 1]?.timestamp === timestamp) continue
        rows.push({ timestamp, value: Number(result) })
        if (rows.length > 60) rows.shift()
      }
    },
    { immediate: true }
  )

  function toggleCompatibility(): void {
    compatible.value = !compatible.value
    startScene()
  }

  function startScene(): void {
    scene?.dispose()
    scene = undefined
    if (!host.value) return
    host.value.replaceChildren()
    error.value = ''
    try {
      scene = createTwinScene(
        host.value,
        () => props,
        (id) => {
          selectedId.value = id
        },
        (message) => {
          error.value = message
        },
        compatible.value
      )
    } catch (failure) {
      error.value = `Não foi possível iniciar o 3D: ${failure instanceof Error ? failure.message : 'WebGL2 indisponível'}. Tente o Modo compatível. As leituras continuam disponíveis no painel.`
    }
  }
  onMounted(() => {
    timer = window.setInterval(() => {
      clock.value = Date.now()
    }, 200)
    startScene()
  })
  onBeforeUnmount(() => {
    window.clearInterval(timer)
    scene?.dispose()
  })
</script>

<template>
  <section class="painel-dados twin-heading">
    <h2>Gêmeo digital 3D</h2>
    <p>
      Arraste para girar, use a roda para aproximar e clique em um sensor, atuador ou módulo. Os
      mesmos itens estão disponíveis nos botões abaixo.
    </p>
    <div class="twin-toolbar">
      <button @click="scene?.resetCamera()">Recentrar câmera</button>
      <button @click="startScene">Reiniciar 3D</button>
      <button :aria-pressed="compatible" @click="toggleCompatibility">
        {{ compatible ? 'Modo compatível ativo' : 'Modo compatível' }}
      </button>
    </div>
    <p class="twin-status" :data-live="liveCount > 0" role="status">
      {{
        liveCount
          ? `${liveCount}/3 estações com telemetria · animações comandadas pelos dados`
          : 'Sem dados ao vivo · animações pausadas'
      }}
    </p>
    <div class="twin-legend">
      <span
        v-for="(label, state) in {
          normal: 'Normal',
          warning: 'Atenção',
          critical: 'Crítico',
          nodata: 'Sem dados',
        }"
        :key="state"
        :class="`state-${state}`"
        >● {{ label }}</span
      >
    </div>
  </section>
  <section class="twin-layout">
    <div class="twin-viewport">
      <div ref="host" class="twin-canvas"></div>
      <p v-if="error" class="twin-overlay" role="alert">{{ error }}</p>
      <p v-else-if="!liveCount" class="twin-overlay">
        Aguardando telemetria pelo WebSocket. Os últimos estados ficam congelados.
      </p>
      <div class="twin-caption">
        T temperatura · I corrente · V tensão · C contator · L limitador
      </div>
    </div>
    <aside
      class="painel-dados twin-detail"
      aria-label="Detalhes do item selecionado"
      v-if="selected"
    >
      <span class="identificador">ESTAÇÃO {{ selected.device_id.slice(-2) }}</span>
      <h3>{{ selected.name }}</h3>
      <code>{{ selected.id }}</code>
      <p :class="`state-${state(selected)}`">{{ stateText(selected) }}</p>
      <strong class="twin-reading">{{ display() }}</strong>
      <p v-if="live && point?.horario">
        Última leitura: {{ new Date(point.horario).toLocaleTimeString('pt-BR') }}
      </p>
      <svg
        v-if="chart.length > 1"
        class="twin-chart"
        viewBox="0 0 260 75"
        role="img"
        aria-label="Minigráfico das últimas leituras do item selecionado"
      >
        <path :d="path()" fill="none" stroke="currentColor" stroke-width="2" />
      </svg>
      <p v-else>Aguardando leituras para o minigráfico.</p>
      <p>
        Saúde prevista: <strong>{{ live ? number(prediction?.health) : '—' }}</strong> / 100
      </p>
      <p>
        Vida útil restante: <strong>{{ live ? number(prediction?.rul_hours) : '—' }}</strong> h
      </p>
      <p v-if="prediction?.status === 'low_load' && live">
        Estimativa de IA limitada por falta de carga.
      </p>
      <p v-if="live && point?.telemetry">
        Bateria {{ number(point.telemetry.battery_percent) }}% · Potência
        {{ number(point.telemetry.power_kw) }} kW
      </p>
      <div v-if="selected.kind === 'actuator' && canCommand" class="twin-command">
        <p v-if="point?.commands_enabled === false">
          Novos comandos bloqueados pelo administrador no cadastro.
        </p>
        <template v-if="selected.id.endsWith('.contactor')">
          <button
            :disabled="locked"
            @click="command('set_contactor', !point?.telemetry?.contactor_on)"
          >
            {{ point?.telemetry?.contactor_on ? 'Abrir contator' : 'Fechar contator' }}
          </button>
        </template>
        <template v-else>
          <label for="twin-power-limit">Limite solicitado</label>
          <select id="twin-power-limit" v-model.number="limit" :disabled="locked">
            <option v-for="n in [100, 75, 50, 25, 0]" :key="n" :value="n">{{ n }}%</option>
          </select>
          <button :disabled="locked" @click="command('set_power_limit', limit)">
            Aplicar limite
          </button>
        </template>
        <p v-if="selected && busy.includes(selected.device_id)">
          Aguardando confirmação pela telemetria…
        </p>
      </div>
      <p v-else-if="selected.kind === 'actuator'">
        Somente operador e administrador podem enviar comandos.
      </p>
    </aside>
  </section>
  <section class="painel-dados twin-catalog">
    <h3>Itens monitorados</h3>
    <div
      v-for="station in ['ponto01', 'ponto02', 'ponto03']"
      :key="station"
      class="twin-component-group"
    >
      <h4>Estação {{ station.slice(-2) }}</h4>
      <button
        v-for="component in components.filter((c) => c.device_id === station)"
        :key="component.id"
        :data-component-id="component.id"
        :aria-pressed="selectedId === component.id"
        :class="`state-${state(component)}`"
        @click="selectedId = component.id"
      >
        {{ component.name }} · {{ stateText(component) }}
      </button>
    </div>
    <p>
      O fluxo nos cabos segue a potência; a barra sobre o veículo segue a bateria e a presença segue
      a ocupação. O efeito térmico segue a temperatura. A oscilação do módulo representa a
      degradação prevista, não uma medição de vibração.
    </p>
  </section>
</template>
