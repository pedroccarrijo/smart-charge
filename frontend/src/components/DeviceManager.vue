<script setup lang="ts">
  import { ref } from 'vue'
  import type { Catalog, RegisteredDevice, DeviceComponent } from '../twin'
  const props = defineProps<{
    catalog: Catalog
    administrator: boolean
    api: (path: string, options?: RequestInit) => Promise<Response>
  }>()
  const device = ref<RegisteredDevice | null>(null),
    component = ref<DeviceComponent | null>(null)
  const saving = ref(false),
    error = ref(''),
    notice = ref('')
  function editDevice(value: RegisteredDevice): void {
    device.value = { ...value }
    component.value = null
    error.value = ''
    notice.value = ''
  }
  function editComponent(value: DeviceComponent): void {
    component.value = { ...value }
    device.value = null
    error.value = ''
    notice.value = ''
  }
  async function saveDevice(): Promise<void> {
    if (!device.value) return
    const { id, name, location, description, commands_enabled, revision } = device.value
    await save(`/api/catalog/devices/${id}`, {
      name,
      location,
      description,
      commands_enabled,
      revision,
    })
  }
  async function saveComponent(): Promise<void> {
    if (!component.value) return
    const { id, name, revision, normal_min, normal_max, critical_min, critical_max } =
      component.value
    await save(`/api/catalog/components/${id}`, {
      name,
      revision,
      normal_min,
      normal_max,
      critical_min,
      critical_max,
    })
  }
  async function save(path: string, body: unknown): Promise<void> {
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      await props.api(path, { method: 'PUT', body: JSON.stringify(body) })
      device.value = null
      component.value = null
      notice.value =
        'Cadastro salvo e auditado. As outras telas receberão a atualização pelo WebSocket.'
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Não foi possível salvar'
    } finally {
      saving.value = false
    }
  }
  function range(component: DeviceComponent): string {
    return component.kind === 'sensor' ? `${component.normal_min} a ${component.normal_max}` : '—'
  }
  async function reload(): Promise<void> {
    try {
      const latest: Catalog = await (await props.api('/api/catalog')).json()
      const latestDevice = latest.devices.find((row) => row.id === device.value?.id)
      const latestComponent = latest.components.find((row) => row.id === component.value?.id)
      if (latestDevice) editDevice(latestDevice)
      if (latestComponent) editComponent(latestComponent)
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Falha ao recarregar cadastro'
    }
  }
</script>

<template>
  <section class="painel-dados">
    <h2>Dispositivos e sensores</h2>
    <p>
      Os três pontos e seus 18 componentes estão cadastrados no PostgreSQL. Os IDs preservam os
      vínculos com MQTT, sessões e gêmeo digital.
    </p>
    <p v-if="!administrator">
      Seu papel permite consultar o cadastro. As alterações são reservadas ao administrador.
    </p>
    <p v-if="notice" class="aviso-comando" role="status">{{ notice }}</p>
    <p v-if="error" class="aviso-erro" role="alert">{{ error }}</p>
    <div class="tabela-scroll">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Nome</th>
            <th>Localização</th>
            <th>Novos comandos</th>
            <th v-if="administrator">Gerenciar</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in catalog.devices" :key="row.id">
            <td>{{ row.id }}</td>
            <td>{{ row.name }}</td>
            <td>{{ row.location || 'Não informada' }}</td>
            <td>{{ row.commands_enabled ? 'Permitidos' : 'Bloqueados' }}</td>
            <td v-if="administrator">
              <button :disabled="saving" :data-edit-device="row.id" @click="editDevice(row)">
                Editar ponto
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <form v-if="device && administrator" class="catalog-form" @submit.prevent="saveDevice">
      <h3>Editar {{ device.id }}</h3>
      <label>Nome<input v-model="device.name" maxlength="80" required /></label>
      <label>Localização<input v-model="device.location" maxlength="120" /></label>
      <label
        >Descrição<textarea v-model="device.description" maxlength="300" rows="3"></textarea>
      </label>
      <label class="catalog-check"
        ><input v-model="device.commands_enabled" type="checkbox" />Permitir novos comandos da
        aplicação</label
      >
      <p>
        Esta permissão controla o envio de comandos. Para interromper a recarga, utilize o contator.
      </p>
      <div class="catalog-actions">
        <button type="submit" :disabled="saving">Salvar ponto</button
        ><button type="button" :disabled="saving" @click="reload">Recarregar cadastro</button
        ><button type="button" @click="device = null">Cancelar</button>
      </div>
    </form>
  </section>
  <section class="painel-dados">
    <h3>Componentes e faixas dos sensores</h3>
    <p>
      As faixas determinam as cores dos sensores no 3D. Os limites preditivos da IA e a proteção
      térmica do simulador seguem suas regras próprias.
    </p>
    <div class="tabela-scroll">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Nome</th>
            <th>Tipo</th>
            <th>Faixa normal</th>
            <th>Faixa crítica externa</th>
            <th v-if="administrator">Gerenciar</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in catalog.components" :key="row.id">
            <td>{{ row.id }}</td>
            <td>{{ row.name }}</td>
            <td>
              {{ { sensor: 'Sensor', actuator: 'Atuador', equipment: 'Equipamento' }[row.kind] }}
            </td>
            <td>{{ range(row) }}</td>
            <td>{{ row.kind === 'sensor' ? `${row.critical_min} a ${row.critical_max}` : '—' }}</td>
            <td v-if="administrator">
              <button :disabled="saving" :data-edit-component="row.id" @click="editComponent(row)">
                Editar componente
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <form v-if="component && administrator" class="catalog-form" @submit.prevent="saveComponent">
      <h3>Editar {{ component.id }}</h3>
      <label>Nome<input v-model="component.name" maxlength="80" required /></label>
      <div v-if="component.kind === 'sensor'" class="grade-laboratorio">
        <label
          >Crítico mínimo<input
            v-model.number="component.critical_min"
            type="number"
            step="any"
            required
        /></label>
        <label
          >Normal mínimo<input
            v-model.number="component.normal_min"
            type="number"
            step="any"
            required
        /></label>
        <label
          >Normal máximo<input
            v-model.number="component.normal_max"
            type="number"
            step="any"
            required
        /></label>
        <label
          >Crítico máximo<input
            v-model.number="component.critical_max"
            type="number"
            step="any"
            required
        /></label>
      </div>
      <div class="catalog-actions">
        <button type="submit" :disabled="saving">Salvar componente</button
        ><button type="button" :disabled="saving" @click="reload">Recarregar cadastro</button
        ><button type="button" @click="component = null">Cancelar</button>
      </div>
    </form>
  </section>
</template>

<style scoped>
  p {
    margin: 12px 0;
    line-height: 1.6;
    font-size: 13px;
  }
</style>
