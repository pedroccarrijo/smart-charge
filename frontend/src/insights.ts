export interface Prediction {
  device_id: string
  status: 'ready' | 'low_load' | 'warming' | 'no_model' | 'offline' | 'waiting'
  health: number | null
  rul_hours: number | null
  model_id: string | null
  level?: 'normal' | 'warning' | 'critical'
  trend?: 'rising' | 'falling' | 'stable'
  samples?: number
  rul_at_horizon?: boolean
  source_timestamp?: string
  model_warning?: string | null
  history: { timestamp: string; health: number; rul_hours: number }[]
}
export interface PredictiveAlert {
  id: string
  device_id: string
  severity: string
  active: boolean
  opened_at: string
  updated_at: string
  closed_at: string | null
  reason: string
  model_id: string
}
export interface InsightsState {
  devices: Prediction[]
  alerts: PredictiveAlert[]
  active_model_id: string | null
}
