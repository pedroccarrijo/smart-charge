import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import {
  COLORS,
  OFFSETS,
  STATION_X,
  cableEndpoints,
  fresh,
  frameDelta,
  level,
  pointFor,
  predictionFor,
  reading,
} from '../twin'
import type { ChargingPoint, DeviceComponent } from '../twin'
import type { InsightsState } from '../insights'

interface Frame {
  points: ChargingPoint[]
  components: DeviceComponent[]
  insights: InsightsState
  connected: boolean
  frameAt: number
}

export function createTwinScene(
  host: HTMLElement,
  frame: () => Frame,
  select: (id: string) => void,
  problem: (message: string) => void,
  compatible = false
) {
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x1c1e1a)
  scene.fog = new THREE.Fog(0x1c1e1a, 27, 60)
  const renderer = new THREE.WebGLRenderer({
    antialias: !compatible,
    alpha: false,
    powerPreference: 'high-performance',
  })
  renderer.setPixelRatio(compatible ? 1 : Math.min(window.devicePixelRatio || 1, 1.5))
  renderer.shadowMap.enabled = !compatible
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.3
  renderer.domElement.setAttribute(
    'aria-label',
    'Gêmeo digital das três estações; arraste para orbitar e clique nos componentes'
  )
  renderer.domElement.setAttribute('role', 'img')
  host.appendChild(renderer.domElement)
  const initialWidth = Math.max(1, host.clientWidth || 640),
    initialHeight = Math.max(1, host.clientHeight || 580)
  renderer.setSize(initialWidth, initialHeight)
  const camera = new THREE.PerspectiveCamera(42, initialWidth / initialHeight, 0.1, 100)
  camera.position.set(14, 13, 19)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.target.set(0, 1, 0)
  controls.enableDamping = true
  controls.enablePan = false
  controls.minDistance = 9
  controls.maxDistance = 32
  controls.maxPolarAngle = Math.PI / 2.1
  controls.update()
  controls.saveState()
  function resetCamera() {
    controls.enableDamping = false
    controls.reset()
    controls.target.set(0, 1, 0)
    camera.position.set(14, 13, 19)
    camera.up.set(0, 1, 0)
    controls.update()
    controls.enableDamping = true
  }
  scene.add(new THREE.HemisphereLight(0xdaeaff, 0x303820, 2.5))
  const sun = new THREE.DirectionalLight(0xfff4dd, 3)
  sun.position.set(6, 14, 8)
  sun.castShadow = true
  sun.shadow.mapSize.set(1024, 1024)
  Object.assign(sun.shadow.camera, { left: -14, right: 14, top: 12, bottom: -12 })
  sun.shadow.bias = -0.0005
  scene.add(sun)

  function box(
    parent: THREE.Object3D,
    size: [number, number, number],
    position: [number, number, number],
    color: number
  ) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(...size),
      new THREE.MeshStandardMaterial({ color, roughness: 0.65, metalness: 0.18 })
    )
    mesh.position.set(...position)
    mesh.castShadow = true
    mesh.receiveShadow = true
    parent.add(mesh)
    return mesh
  }
  function sphere(
    parent: THREE.Object3D,
    radius: number,
    position: [number, number, number],
    color: number
  ) {
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(radius, 12, 8),
      new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.3 })
    )
    mesh.position.set(...position)
    parent.add(mesh)
    return mesh
  }
  function label(
    parent: THREE.Object3D,
    text: string,
    position: [number, number, number],
    width: number
  ) {
    const canvas = document.createElement('canvas')
    canvas.width = 512
    canvas.height = 100
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = 'rgba(20,24,15,.9)'
    ctx.fillRect(0, 0, 512, 100)
    ctx.fillStyle = '#e5fff6'
    ctx.font = 'bold 48px system-ui'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(text, 256, 50)
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false })
    )
    sprite.position.set(...position)
    sprite.scale.set(width, width / 5.12, 1)
    parent.add(sprite)
  }
  box(scene, [21, 0.18, 12], [0, -0.12, 0], 0x343e29)
  const treeTrunks = new THREE.InstancedMesh(
    new THREE.CylinderGeometry(0.12, 0.17, 1.5, 8),
    new THREE.MeshStandardMaterial({ color: 0x6c5a42 }),
    4
  )
  const treeTops = new THREE.InstancedMesh(
    new THREE.ConeGeometry(0.8, 2, 8),
    new THREE.MeshStandardMaterial({ color: 0x657c35 }),
    4
  )
  const matrix = new THREE.Matrix4()
  ;[
    [-9, -4],
    [-9, 4],
    [9, -4],
    [9, 4],
  ].forEach(([x, z], i) => {
    treeTrunks.setMatrixAt(i, matrix.makeTranslation(x, 0.75, z))
    treeTops.setMatrixAt(i, matrix.makeTranslation(x, 2.2, z))
  })
  treeTops.castShadow = true
  scene.add(treeTrunks, treeTops)
  const stations = Object.entries(STATION_X).map(([id, x]) => {
    const group = new THREE.Group()
    group.position.set(x, 0, -2.3)
    group.userData.componentId = `${id}.module`
    scene.add(group)
    const posts = [
      box(group, [1.8, 0.22, 1], [0, 0.11, 0], 0x7e95a4),
      box(group, [0.12, 2.3, 0.95], [-0.8, 1.3, 0], 0x7e95a4),
      box(group, [0.12, 2.3, 0.95], [0.8, 1.3, 0], 0x7e95a4),
    ]
    box(group, [1.75, 0.14, 0.95], [0, 2.5, 0], 0xc7d6dd)
    box(group, [1.6, 2.15, 0.08], [0, 1.3, -0.45], 0x102332)
    label(group, `ESTAÇÃO ${id.slice(-2)}`, [0, 3.05, 0], 2.6)
    const items = new Map<
      string,
      { group: THREE.Group; mesh: THREE.Mesh<THREE.BoxGeometry, THREE.MeshStandardMaterial> }
    >()
    for (const [suffix, offset] of Object.entries(OFFSETS)) {
      const item = new THREE.Group()
      item.position.set(...offset)
      item.userData.componentId = `${id}.${suffix}`
      group.add(item)
      const size: [number, number, number] =
        suffix === 'module'
          ? [1.25, 0.7, 0.4]
          : suffix === 'contactor' || suffix === 'limiter'
            ? [0.55, 0.42, 0.25]
            : [0.34, 0.34, 0.18]
      const mesh = box(item, size, [0, 0, 0], COLORS.nodata)
      items.set(suffix, { group: item, mesh })
      if (suffix !== 'module')
        label(
          item,
          (
            {
              temperature: 'T',
              current: 'I',
              voltage: 'V',
              contactor: 'C',
              limiter: 'L',
            } as Record<string, string>
          )[suffix],
          [0, 0, 0.22],
          0.35
        )
    }
    const fan = new THREE.Group()
    fan.position.set(0.3, 0, 0.25)
    items.get('module')!.group.add(fan)
    for (let i = 0; i < 4; i++) {
      const blade = box(fan, [0.32, 0.09, 0.04], [0.09, 0, 0], 0x132532)
      blade.rotation.z = (i * Math.PI) / 2
    }
    sphere(fan, 0.07, [0, 0, 0.04], 0xe0eeee)
    const contactor = box(items.get('contactor')!.group, [0.12, 0.32, 0.09], [0, 0, 0.23], 0xffffff)
    const needle = box(items.get('limiter')!.group, [0.25, 0.04, 0.04], [0, 0.03, 0.24], 0xffffff)
    const heat = new THREE.Mesh(
      new THREE.ConeGeometry(0.5, 1, 12, 1, true),
      new THREE.MeshBasicMaterial({
        color: 0xff8955,
        transparent: true,
        opacity: 0.0,
        depthWrite: false,
        side: THREE.DoubleSide,
      })
    )
    heat.position.set(x, 2.9, -2.6)
    scene.add(heat)
    const car = new THREE.Group()
    car.position.set(x, 0, 1.8)
    car.userData.componentId = `${id}.module`
    car.visible = false
    scene.add(car)
    const carBody = box(car, [1.95, 0.55, 3.1], [0, 0.65, 0], 0x859765)
    box(car, [1.55, 0.48, 1.55], [0, 1.12, -0.05], 0x303929)
    for (const side of [-1, 1])
      for (const z of [-0.95, 0.95]) {
        const wheel = new THREE.Mesh(
          new THREE.CylinderGeometry(0.3, 0.3, 0.18, 12),
          new THREE.MeshStandardMaterial({ color: 0x121c28 })
        )
        wheel.rotation.z = Math.PI / 2
        wheel.position.set(side, 0.35, z)
        car.add(wheel)
      }
    box(car, [1.65, 0.09, 0.34], [0, 1.45, 0], 0x272f20)
    const battery = box(car, [1.6, 0.08, 0.3], [0, 1.51, 0], 0xccff00)
    const endpoints = cableEndpoints(id, true),
      parkedEndpoints = cableEndpoints(id, false)
    sphere(scene, 0.11, endpoints.start, 0xe5f4ef)
    sphere(car, 0.11, [1.04, 0.85, -0.6], 0x15363d)
    sphere(scene, 0.1, parkedEndpoints.end, 0x526a79)
    function cable(occupied: boolean) {
      const ends = occupied ? endpoints : parkedEndpoints
      const curve = new THREE.CatmullRomCurve3([
        new THREE.Vector3(...ends.start),
        new THREE.Vector3(x + 1.8, 0.5, occupied ? -0.9 : -2.0),
        new THREE.Vector3(...ends.end),
      ])
      const mesh = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 24, 0.055, 6, false),
        new THREE.MeshStandardMaterial({ color: 0x12150e })
      )
      mesh.userData.componentId = `${id}.limiter`
      scene.add(mesh)
      return { curve, mesh }
    }
    const charging = cable(true),
      parked = cable(false)
    charging.mesh.visible = false
    const particles = Array.from({ length: 6 }, () => {
      const p = sphere(scene, 0.08, endpoints.start, 0xccff00)
      p.visible = false
      return p
    })
    for (const dx of [-1.5, 1.5]) box(scene, [0.055, 0.018, 4.6], [x + dx, 0.005, 1.55], 0xb8c49e)
    box(scene, [3.05, 0.018, 0.055], [x, 0.005, 3.85], 0xb8c49e)
    label(scene, id.slice(-2), [x, 0.15, 4.4], 1)
    return {
      id,
      items,
      posts,
      car,
      carBody,
      battery,
      fan,
      contactor,
      needle,
      charging,
      parked,
      particles,
      heat,
      phase: 0,
    }
  })

  const raycaster = new THREE.Raycaster(),
    pointer = new THREE.Vector2()
  let pressed = [0, 0]
  function down(event: PointerEvent) {
    pressed = [event.clientX, event.clientY]
  }
  function pick(event: PointerEvent) {
    if (Math.hypot(event.clientX - pressed[0], event.clientY - pressed[1]) > 5) return
    const rect = renderer.domElement.getBoundingClientRect()
    pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      (-(event.clientY - rect.top) / rect.height) * 2 + 1
    )
    raycaster.setFromCamera(pointer, camera)
    for (const hit of raycaster.intersectObjects(scene.children, true)) {
      let ancestor: THREE.Object3D | null = hit.object,
        visible = true
      while (ancestor) {
        if (!ancestor.visible) visible = false
        ancestor = ancestor.parent
      }
      if (!visible) continue
      let object: THREE.Object3D | null = hit.object
      while (object) {
        if (object.userData.componentId) {
          select(object.userData.componentId)
          return
        }
        object = object.parent
      }
    }
  }
  renderer.domElement.addEventListener('pointerdown', down)
  renderer.domElement.addEventListener('pointerup', pick)
  let contextLost = false
  let shaderFailed = false
  renderer.debug.onShaderError = () => {
    shaderFailed = true
    problem(
      'O navegador não conseguiu compilar o desenho 3D. Tente o Modo compatível ou Reiniciar 3D.'
    )
  }
  const lost = (event: Event) => {
    event.preventDefault()
    contextLost = true
    problem('O contexto gráfico foi interrompido. Aguardando recuperação do navegador.')
  }
  const restored = () => {
    contextLost = false
    shaderFailed = false
    resetCamera()
    problem('')
  }
  renderer.domElement.addEventListener('webglcontextlost', lost)
  renderer.domElement.addEventListener('webglcontextrestored', restored)
  const resize = new ResizeObserver(() => {
    const width = host.clientWidth,
      height = host.clientHeight
    if (!width || !height) return
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    renderer.setSize(width, height)
  })
  resize.observe(host)
  let handle = 0,
    last = performance.now(),
    disposed = false
  function animate(now: number) {
    if (disposed) return
    // Schedule before rendering: one graphics error must not silently kill the loop.
    handle = requestAnimationFrame(animate)
    try {
      const dt = frameDelta(now, last)
      last = now
      const data = frame(),
        wallTime = Date.now()
      for (const station of stations) {
        const point = pointFor(data.points, station.id),
          prediction = predictionFor(data.insights, station.id)
        const live = fresh(point, data.connected, data.frameAt, wallTime)
        for (const component of data.components.filter((c) => c.device_id === station.id)) {
          const suffix = component.id.split('.').pop()!,
            item = station.items.get(suffix)
          if (!item) continue
          const state = level(
            component,
            reading(component, point, prediction),
            prediction,
            live,
            point?.telemetry?.automatic_limit_active
          )
          item.mesh.material.color.setHex(COLORS[state])
        }
        station.posts.forEach((p) => p.material.color.setHex(live ? 0x7e95a4 : 0x4b5968))
        station.carBody.material.color.setHex(live ? 0x859765 : 0x626855)
        if (live && point?.telemetry) {
          const p = point.telemetry
          station.car.visible = p.occupied
          station.charging.mesh.visible = p.occupied
          station.parked.mesh.visible = !p.occupied
          const ratio = THREE.MathUtils.clamp(p.battery_percent / 100, 0.001, 1)
          station.battery.scale.x = ratio
          station.battery.position.x = -0.8 + 0.8 * ratio
          if (p.power_kw > 0) station.phase += (dt * p.power_kw) / 8
          station.fan.rotation.z = station.phase * 2
          station.contactor.rotation.x = p.contactor_on ? 0 : -0.95
          station.contactor.material.emissive.setHex(p.contactor_on ? 0xccff00 : 0)
          station.contactor.material.emissiveIntensity = p.contactor_on
            ? 0.25 + 0.1 * Math.sin(station.phase * 4)
            : 0
          station.needle.rotation.z = Math.PI * 0.75 - (p.power_limit_percent / 100) * Math.PI * 1.5
          const module = station.items.get('module')!.group
          module.position.x =
            Math.sin(station.phase * 16) *
            (prediction?.health == null ? 0 : ((100 - prediction.health) / 100) * 0.035)
          station.heat.scale.y = Math.max(0.01, (p.temperature_c - 35) / 45)
          station.heat.position.y = 2.65 + station.heat.scale.y / 2
          station.heat.material.opacity = THREE.MathUtils.clamp(
            (p.temperature_c - 40) / 160,
            0,
            0.35
          )
        } else station.heat.material.opacity = 0
        station.particles.forEach((particle, i) => {
          particle.visible =
            live && !!point?.telemetry?.occupied && (point?.telemetry?.power_kw ?? 0) > 0
          if (particle.visible)
            particle.position.copy(
              station.charging.curve.getPoint((station.phase * 0.16 + i / 6) % 1)
            )
        })
      }
      controls.update()
      if (!contextLost && !shaderFailed) {
        renderer.render(scene, camera)
        renderer.domElement.dataset.rendered = 'true'
      }
    } catch (error) {
      problem(
        `Falha ao desenhar o 3D: ${error instanceof Error ? error.message : 'erro gráfico'}. Tente Reiniciar 3D ou Modo compatível.`
      )
    }
  }
  // Paint synchronously as well as on animation frames, including the first opening.
  try {
    renderer.render(scene, camera)
    renderer.domElement.dataset.rendered = 'true'
  } catch (error) {
    problem(
      `Falha na primeira renderização: ${error instanceof Error ? error.message : 'erro gráfico'}`
    )
  }
  handle = requestAnimationFrame(animate)
  function dispose() {
    disposed = true
    cancelAnimationFrame(handle)
    resize.disconnect()
    controls.dispose()
    renderer.domElement.removeEventListener('pointerdown', down)
    renderer.domElement.removeEventListener('pointerup', pick)
    renderer.domElement.removeEventListener('webglcontextlost', lost)
    renderer.domElement.removeEventListener('webglcontextrestored', restored)
    const geometries = new Set<THREE.BufferGeometry>(),
      materials = new Set<THREE.Material>(),
      textures = new Set<THREE.Texture>()
    scene.traverse((object) => {
      if (object instanceof THREE.Mesh) geometries.add(object.geometry)
      if (object instanceof THREE.Mesh || object instanceof THREE.Sprite) {
        for (const material of Array.isArray(object.material)
          ? object.material
          : [object.material]) {
          materials.add(material)
          for (const value of Object.values(material))
            if (value instanceof THREE.Texture) textures.add(value)
        }
      }
    })
    geometries.forEach((g) => g.dispose())
    materials.forEach((m) => m.dispose())
    textures.forEach((t) => t.dispose())
    renderer.dispose()
    renderer.forceContextLoss()
    renderer.domElement.remove()
  }
  return { dispose, resetCamera }
}
