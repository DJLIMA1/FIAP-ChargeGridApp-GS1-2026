import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Station } from '../src/api/types'
import { createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import { createTokenStore } from '../src/auth/tokens'
import { reconcileDraft } from '../src/lib/draft'
import { StationRefresh } from '../src/lib/stationRefresh'
import * as data from '../src/mock/data'

const station = () => structuredClone(data.STATIONS[0])
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

afterEach(() => vi.useRealTimers())

describe('station polling', () => {
  it('updates every two seconds without overlapping requests and stops on route departure', async () => {
    vi.useFakeTimers()
    const pending = deferred<Station>()
    const load = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(station())
    const apply = vi.fn()
    const poll = new StationRefresh(load, apply, vi.fn())
    const first = poll.refresh()
    await poll.refresh()
    expect(load).toHaveBeenCalledTimes(1)
    pending.resolve(station())
    await first
    await vi.advanceTimersByTimeAsync(1999)
    expect(load).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(load).toHaveBeenCalledTimes(2)
    poll.stop()
    await vi.advanceTimersByTimeAsync(20_000)
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('ignores an old GET resolved after an acknowledged PATCH', async () => {
    vi.useFakeTimers()
    const pending = deferred<Station>()
    const apply = vi.fn()
    const poll = new StationRefresh(() => pending.promise, apply, vi.fn())
    const reading = poll.refresh()
    const saved = { ...station(), name: 'Saved station' }
    poll.accept(saved)
    pending.resolve({ ...station(), name: 'Old station' })
    await reading
    expect(apply).toHaveBeenCalledTimes(1)
    expect(apply).toHaveBeenCalledWith(saved)
    poll.stop()
  })

  it('keeps the actual PATCH response when the earlier station endpoint finally replies', async () => {
    vi.useFakeTimers()
    const stale = station()
    const savedPoint = { ...stale.connectors[0], charger_address: 23 }
    const oldResponse = deferred<Response>()
    const methods: string[] = []
    const fetchImpl = vi.fn((_input: RequestInfo | URL, init: RequestInit = {}) => {
      methods.push(init.method ?? 'GET')
      if (init.method === 'PATCH') return Promise.resolve(new Response(JSON.stringify(savedPoint), { status: 200 }))
      return oldResponse.promise
    })
    const store = createTokenStore(null)
    store.setTokens({ access_token: 'test-access', refresh_token: 'test-refresh', expires_in: 3600 })
    const ep = endpoints(createApiClient({ store, fetchImpl }))
    const applied: Station[] = []
    const poll = new StationRefresh((signal) => ep.station(stale.id, signal), (value) => applied.push(value), vi.fn())
    const reading = poll.refresh()
    const saved = await ep.patchConnector(savedPoint.id, { charger_address: 23 })
    poll.accept({ ...stale, connectors: stale.connectors.map((c) => c.id === saved.id ? saved : c) })
    oldResponse.resolve(new Response(JSON.stringify(stale), { status: 200 }))
    await reading
    expect(methods).toEqual(['GET', 'PATCH'])
    expect(applied).toHaveLength(1)
    expect(applied[0].connectors[0].charger_address).toBe(23)
    poll.stop()
  })

  it('does no network work while hidden and resumes immediately when shown', async () => {
    vi.useFakeTimers()
    let visible = false
    const load = vi.fn().mockResolvedValue(station())
    const poll = new StationRefresh(load, vi.fn(), vi.fn(), () => visible)
    await poll.refresh()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(load).not.toHaveBeenCalled()
    visible = true
    await poll.refresh()
    expect(load).toHaveBeenCalledTimes(1)
    poll.stop()
  })

  it('discards a response after unmount, and backs off errors before recovering', async () => {
    vi.useFakeTimers()
    const pending = deferred<Station>()
    const apply = vi.fn()
    const fail = vi.fn()
    const disposed = new StationRefresh(() => pending.promise, apply, fail)
    const reading = disposed.refresh()
    disposed.stop()
    pending.resolve(station())
    await reading
    expect(apply).not.toHaveBeenCalled()
    const load = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(station())
    const poll = new StationRefresh(load, apply, fail)
    await poll.refresh()
    expect(fail).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(3999)
    expect(load).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(load).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(load).toHaveBeenCalledTimes(3)
    poll.stop()
  })
})

describe('draft preservation', () => {
  it('keeps edited fields and accepts only remote changes to clean fields', () => {
    const previous = { address: '1', power: '22', price: '1.20' }
    const draft = { ...previous, address: '23', price: '1.35' }
    expect(reconcileDraft(draft, previous, { address: '2', power: '44', price: '1.25' }))
      .toEqual({ address: '23', power: '44', price: '1.35' })
  })

  it('preserves amenities edits across telemetry refreshes and accepts clean remote changes', () => {
    const saved = [{ kind: 'cafe', name: 'Original', distance: '50' }]
    const draft = [{ ...saved[0], name: 'Typed name' }]
    expect(reconcileDraft(draft, saved, structuredClone(saved))).toBe(draft)
    const remote = [{ ...saved[0], name: 'Remote cafe' }]
    expect(reconcileDraft(structuredClone(saved), saved, remote)).toBe(remote)
  })

  it('does not erase newer typing when the previous submission finishes saving', () => {
    expect(reconcileDraft('27', '1', '23')).toBe('27')
    expect(reconcileDraft('1', '1', '23')).toBe('23')
  })
})
