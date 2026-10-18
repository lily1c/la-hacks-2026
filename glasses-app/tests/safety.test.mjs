import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/safety.ts', import.meta.url), 'utf8')
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { createSafety } = await import('data:text/javascript,' + encodeURIComponent(js))

function setup() {
  let clock = 0
  const changes = []
  const safety = createSafety({ fallG: 3, settleMs: 5000, stillSpreadG: 0.05, confirmMs: 20000,
    onChange: (s) => changes.push(s), now: () => clock })
  // Feed samples at 10 Hz and tick once a second, like the app.
  const run = (ms, sample) => {
    for (let t = 0; t < ms; t += 100) {
      clock += 100
      safety.imu(...sample(clock))
      if (clock % 1000 === 0) safety.tick()
    }
  }
  return { safety, changes, run }
}
const upright = () => [0, 0, 1]
const walking = (t) => [0, 0, 1 + (t % 400 < 200 ? 0.15 : -0.15)]
const impact = () => [2.5, 1.5, 2]  // |a| about 3.5 g

test('impact then stillness asks, then reports man down', () => {
  const { safety, changes, run } = setup()
  run(2000, upright)
  run(100, impact)
  run(6000, upright)
  assert.equal(safety.status, 'check')
  assert.match(safety.line(), /ARE YOU OK/)
  run(20000, upright)
  assert.deepEqual(changes, ['check', 'man_down'])
})

test('tap during the check clears it', () => {
  const { safety, changes, run } = setup()
  run(100, impact)
  run(6000, upright)
  assert.equal(safety.tap(), true)
  assert.equal(safety.status, 'ok')
  assert.deepEqual(changes, ['check', 'ok'])
})

test('impact while still moving is ignored', () => {
  const { safety, run } = setup()
  run(100, impact)
  run(8000, walking)
  assert.equal(safety.status, 'ok')
})

test('walking and taking glasses off (2.5 g) do not trigger', () => {
  const { safety, run } = setup()
  run(5000, walking)
  run(100, () => [1.5, 1, 1.7])  // ~2.5 g, as measured when the glasses came off
  run(8000, upright)
  assert.equal(safety.status, 'ok')
})

test('SOS until tapped; tap when ok does nothing', () => {
  const { safety, changes } = setup()
  assert.equal(safety.tap(), false)
  safety.sos()
  assert.match(safety.line(), /SOS SENT/)
  assert.equal(safety.tap(), true)
  assert.deepEqual(changes, ['sos', 'ok'])
})
