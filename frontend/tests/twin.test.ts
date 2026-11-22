import test from 'node:test'
import assert from 'node:assert/strict'
import { fresh, level, reading, cableEndpoints, STATION_X, frameDelta } from '../src/twin.ts'
import type { ChargingPoint, DeviceComponent } from '../src/twin.ts'

const point: ChargingPoint = {
  ponto: '01',
  device_id: 'ponto01',
  online: true,
  status: 'EM USO',
  horario: '2026-11-12T12:00:00Z',
  telemetry: {
    temperature_c: 44,
    current_a: 32,
    voltage_v: 398,
    power_kw: 22,
    battery_percent: 50,
    energy_kwh: 1,
    contactor_on: true,
    power_limit_percent: 100,
    automatic_limit_active: false,
    estimated_minutes: 60,
    occupied: true,
  },
}

test('first animation frame cannot move cable particles backwards; resumed frames stay bounded', () => {
  assert.equal(frameDelta(10, 12), 0)
  assert.equal(frameDelta(33, 0), 0.033)
  assert.equal(frameDelta(10000, 0), 0.05)
  assert.equal(frameDelta(Number.NaN, 0), 0)
})
const sensor: DeviceComponent = {
  id: 'ponto01.temperature',
  device_id: 'ponto01',
  name: 'Temperatura',
  kind: 'sensor',
  telemetry_key: 'temperature_c',
  normal_min: -10,
  normal_max: 55,
  critical_min: -20,
  critical_max: 65,
  revision: 1,
}

test('REST data alone cannot animate: a recent WebSocket frame is required', () => {
  assert.equal(fresh(point, false, 10000, 10000), false)
  assert.equal(fresh(point, true, 0, 10000), false)
  assert.equal(fresh(point, true, 10000, 12000), true)
  assert.equal(fresh(point, true, 10000, 14000), false)
  assert.equal(fresh({ ...point, online: false }, true, 10000, 10000), false)
})
test('sensor colors follow catalog thresholds, with missing data overriding all states', () => {
  assert.equal(level(sensor, 44, undefined, true), 'normal')
  assert.equal(level(sensor, 60, undefined, true), 'warning')
  assert.equal(level(sensor, 65, undefined, true), 'critical')
  assert.equal(level(sensor, 70, undefined, false), 'nodata')
  assert.equal(level(sensor, null, undefined, true), 'nodata')
  assert.equal(reading(sensor, point, undefined), 44)
})
test('both cable variants terminate on the physical socket coordinates', () => {
  for (const device of Object.keys(STATION_X)) {
    const charging = cableEndpoints(device, true),
      parked = cableEndpoints(device, false)
    assert.deepEqual(charging.start, [STATION_X[device] + 0.82, 1.1, -2])
    assert.deepEqual(charging.end, [STATION_X[device] + 1.04, 0.85, 1.2])
    assert.deepEqual(parked.start, charging.start)
    assert.deepEqual(parked.end, [STATION_X[device] + 0.82, 0.5, -2])
  }
})
