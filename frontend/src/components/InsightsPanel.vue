<script setup lang="ts">
  import type { InsightsState, Prediction } from '../insights'
  defineProps<{ data: InsightsState }>()
  function number(value: number | null): string {
    return value == null ? '—' : value.toLocaleString('pt-BR', { maximumFractionDigits: 1 })
  }
  function status(point: Prediction): string {
    return {
      ready: 'Inferência ao vivo',
      low_load: 'Sem carga suficiente: estimativa limitada',
      warming: 'Reunindo leituras para a janela',
      no_model: 'Treine e aprove uma versão no Laboratório',
      offline: 'Sem dados de telemetria',
      waiting: 'Aguardando o serviço de inferência',
    }[point.status]
  }
  function trend(value: string | undefined): string {
    return (
      (
        { rising: 'Saúde melhorando', falling: 'Saúde caindo', stable: 'Saúde estável' } as Record<
          string,
          string
        >
      )[value ?? ''] ?? '—'
    )
  }
  function time(value: string): string {
    return new Date(value).toLocaleString('pt-BR')
  }
  function path(point: Prediction): string {
    return point.history
      .map(
        (row, index) =>
          `${index ? 'L' : 'M'}${(index / Math.max(1, point.history.length - 1)) * 240},${60 - (row.health / 100) * 60}`
      )
      .join(' ')
  }
</script>

<template>
  <section class="painel-dados">
    <h2>Insights de manutenção preditiva</h2>
    <p>
      Acompanhe a saúde dos módulos de potência e identifique quais estações precisam de atenção.
    </p>
    <details>
      <summary>Como interpretar as previsões</summary>
      <p>
        Saúde é uma nota de zero a cem. Vida útil restante é uma estimativa em horas, feita com
        dados sintéticos; não é uma garantia de falha.
      </p>
      <p>
        Versão aprovada: <strong>{{ data.active_model_id?.slice(0, 8) ?? 'Nenhuma' }}</strong>
      </p>
      <p>
        Alertas exigem três previsões consecutivas abaixo dos limites. A liberação exige dez
        previsões com saúde ≥ 75 e RUL ≥ 84 h, com o módulo sob carga.
      </p>
    </details>
  </section>
  <section class="estacoes insights-cards">
    <article
      v-for="point in data.devices"
      :key="point.device_id"
      class="painel-dados insight-card"
      :class="point.health == null ? 'insight-offline' : `insight-${point.level ?? 'normal'}`"
    >
      <h3>Estação {{ point.device_id.slice(-2) }}</h3>
      <p class="estado-conexao">{{ status(point) }}</p>
      <p v-if="point.model_warning" role="alert" class="aviso-erro">{{ point.model_warning }}</p>
      <dl class="indicadores-ia">
        <div>
          <dt>Índice de saúde</dt>
          <dd>{{ number(point.health) }}<small v-if="point.health != null"> / 100</small></dd>
        </div>
        <div>
          <dt>Vida útil restante</dt>
          <dd>
            {{ point.rul_at_horizon ? '≥ ' : '' }}{{ number(point.rul_hours)
            }}<small v-if="point.rul_hours != null"> h</small>
          </dd>
        </div>
      </dl>
      <p>{{ point.health == null ? '—' : trend(point.trend) }}</p>
      <svg
        v-if="point.history.length > 1"
        class="tendencia-saude"
        viewBox="0 0 240 64"
        role="img"
        aria-label="Tendência recente da saúde, de zero a cem"
      >
        <path :d="path(point)" fill="none" stroke="currentColor" stroke-width="2" />
      </svg>
      <details>
        <summary>Detalhes da previsão</summary>
        <p>
          Versão em uso: {{ point.model_id?.slice(0, 8) ?? '—' }} · Leituras na janela:
          {{ point.samples ?? 0 }}/16
        </p>
        <p v-if="point.source_timestamp">Última inferência: {{ time(point.source_timestamp) }}</p>
      </details>
    </article>
  </section>
  <section class="painel-dados">
    <h3>Alertas preditivos</h3>
    <p v-if="!data.alerts.length">Nenhum alerta registrado.</p>
    <div v-else class="tabela-scroll">
      <table>
        <thead>
          <tr>
            <th>Estação</th>
            <th>Nível</th>
            <th>Estado</th>
            <th>Motivo</th>
            <th>Última mudança</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="alert in data.alerts" :key="alert.id">
            <td>{{ alert.device_id }}</td>
            <td>{{ alert.severity === 'critical' ? 'Crítico' : 'Atenção' }}</td>
            <td>{{ alert.active ? 'Ativo' : 'Encerrado' }}</td>
            <td>{{ alert.reason }}</td>
            <td>{{ time(alert.updated_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p>
      Os tempos de vida útil vêm de treinamento sintético, com horizonte de 168 horas. Sem carga, os
      alertas existentes ficam preservados até haver leituras suficientes para reavaliá-los.
    </p>
  </section>
</template>
