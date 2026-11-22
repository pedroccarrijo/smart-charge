import type { InsightsState, Prediction } from './insights'

// A RAF timestamp can precede performance.now() sampled during scene setup.
// Negative time would move particles outside the cable curve's valid [0, 1] range.
export function frameDelta(now: number, previous: number): number {
  return Number.isFinite(now) && Number.isFinite(previous)
    ? Math.min(0.05, Math.max(0, (now - previous) / 1000))
    : 0
}

export interface Telemetry {
  temperature_c: number
  current_a: number
  voltage_v: number
  power_kw: number
  battery_percent: number
  energy_kwh: number
  contactor_on: boolean
  power_limit_percent: number
  automatic_limit_active: boolean
  estimated_minutes: number | null
  occupied: boolean
}
export interface ChargingPoint {
  ponto: string
  device_id?: string
  online?: boolean
  display_name?: string
  commands_enabled?: boolean
  status: 'DISPONIVEL' | 'EM USO' | 'SEM DADOS'
  horario: string | null
  telemetry?: Telemetry | null
}
export interface DeviceComponent {
  id: string
  device_id: string
  name: string
  kind: 'sensor' | 'actuator' | 'equipment'
  telemetry_key: string | null
  normal_min: number | null
  normal_max: number | null
  critical_min: number | null
  critical_max: number | null
  revision: number
}
export interface RegisteredDevice {
  id: string
  name: string
  location: string
  description: string
  commands_enabled: boolean
  revision: number
}
export interface Catalog {
  devices: RegisteredDevice[]
  components: DeviceComponent[]
}
export type State = 'normal' | 'warning' | 'critical' | 'nodata'
export const COLORS: Record<State, number> = {
  normal: 0xccff00,
  warning: 0xffbd69,
  critical: 0xff6376,
  nodata: 0x7b826e,
}
export const STATION_X: Record<string, number> = { ponto01: -5.6, ponto02: 0, ponto03: 5.6 }
export const OFFSETS: Record<string, [number, number, number]> = {
  module: [0, 1.3, 0.05],
  temperature: [-0.48, 1.95, 0.48],
  current: [0, 1.95, 0.48],
  voltage: [0.48, 1.95, 0.48],
  contactor: [-0.45, 0.65, 0.48],
  limiter: [0.45, 0.65, 0.48],
}
export function fresh(
  point: ChargingPoint | undefined,
  connected: boolean,
  frameAt: number,
  now: number
): boolean {
  return connected && frameAt > 0 && now - frameAt <= 3500 && !!point?.online && !!point.telemetry
}
export function reading(
  component: DeviceComponent,
  point: ChargingPoint | undefined,
  prediction: Prediction | undefined
): number | boolean | null {
  if (component.kind === 'equipment') return prediction?.health ?? null
  const value = point?.telemetry?.[component.telemetry_key as keyof Telemetry]
  return typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value))
    ? value
    : null
}
export function level(
  component: DeviceComponent,
  value: number | boolean | null,
  prediction: Prediction | undefined,
  live: boolean,
  automatic = false
): State {
  if (!live || value == null) return 'nodata'
  if (component.kind === 'equipment') return prediction?.level ?? 'normal'
  if (component.kind === 'actuator')
    return component.id.endsWith('.limiter') && automatic ? 'warning' : 'normal'
  if (typeof value !== 'number') return 'nodata'
  if (
    (component.critical_min != null && value < component.critical_min) ||
    (component.critical_max != null && value >= component.critical_max)
  )
    return 'critical'
  if (
    (component.normal_min != null && value < component.normal_min) ||
    (component.normal_max != null && value > component.normal_max)
  )
    return 'warning'
  return 'normal'
}
export function pointFor(points: ChargingPoint[], id: string): ChargingPoint | undefined {
  return points.find((point) => (point.device_id ?? `ponto${point.ponto}`) === id)
}
export function predictionFor(insights: InsightsState, id: string): Prediction | undefined {
  return insights.devices.find((point) => point.device_id === id)
}
export function cableEndpoints(
  device: string,
  occupied: boolean
): { start: [number, number, number]; end: [number, number, number] } {
  const x = STATION_X[device] ?? 0
  return {
    start: [x + 0.82, 1.1, -2.0],
    end: occupied ? [x + 1.04, 0.85, 1.2] : [x + 0.82, 0.5, -2.0],
  }
}
