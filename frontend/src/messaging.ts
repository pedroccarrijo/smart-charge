export interface QueueInfo {
  name: string
  messages: number
  ready: number
  unacknowledged: number
  consumers: number
  publish_rate: number
  delivery_rate: number
}
export interface BusMessage {
  id: string
  timestamp: string
  observed_at: string
  type: string
  device_id: string | null
  routing_key: string
  payload: unknown
}
export interface MessagingState {
  available: boolean
  error: string | null
  sampled_at: string | null
  queues: QueueInfo[]
  consumers: { queue: string; tag: string; user: string; ack_required: boolean; prefetch: number }[]
  rates: { publish_in?: number; publish_out?: number }
  recent: BusMessage[]
}
