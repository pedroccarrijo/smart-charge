export interface Job {
  id: string
  kind: 'generate' | 'train'
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  created_at: string
  config: { rows?: number; equipment?: number; days?: number; dataset_id?: string; seed?: number }
  result: {
    rows?: number
    sensor_readings?: number
    missing_cells?: number
    outlier_cells?: number
    failed_equipment?: number
  } | null
}
export interface Scores {
  mae: number
  rmse: number
  r2: number
}
export interface TargetMetrics {
  test: Scores
  baseline: Scores
  validation: Scores
  beats_baseline: boolean
  predicted_vs_actual: { actual: number; predicted: number }[]
  feature_importance: { feature: string; importance: number }[]
}
export interface ModelVersion {
  id: string
  dataset_id: string
  accepted: boolean
  active: boolean
  created_at: string
  metrics: {
    targets: { health: TargetMetrics; rul_hours: TargetMetrics }
    sample_counts: { train: number; validation: number; test: number }
    dataset_rows: number
    feature_version: string
    equipment_split: { train: number[]; validation: number[]; test: number[] }
  }
}
export interface LabState {
  jobs: Job[]
  models: ModelVersion[]
}
