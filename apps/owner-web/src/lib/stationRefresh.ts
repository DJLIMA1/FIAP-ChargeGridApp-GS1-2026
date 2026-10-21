import type { Station } from '../api/types'

export const STATION_POLL_MS = 2000

/** A single station request at a time. A mutation invalidates every older response. */
export class StationRefresh {
  private timer: ReturnType<typeof setTimeout> | undefined
  private controller: AbortController | null = null
  private running = false
  private stopped = false
  private revision = 0
  private failures = 0

  constructor(
    private readonly load: (signal: AbortSignal) => Promise<Station>,
    private readonly apply: (station: Station) => void,
    private readonly fail: (error: unknown) => void,
    private readonly visible = () => typeof document === 'undefined' || document.visibilityState === 'visible',
  ) {}

  private schedule() {
    clearTimeout(this.timer)
    if (!this.stopped && this.visible()) this.timer = setTimeout(() => void this.refresh(), Math.min(60_000, STATION_POLL_MS * 2 ** this.failures))
  }

  async refresh() {
    if (this.stopped || this.running) return
    clearTimeout(this.timer)
    if (!this.visible()) return
    this.running = true
    const revision = this.revision
    const controller = new AbortController()
    this.controller = controller
    try {
      const next = await this.load(controller.signal)
      if (this.stopped || controller.signal.aborted || revision !== this.revision || !this.visible()) return
      this.failures = 0
      this.apply(next)
    } catch (error) {
      if (this.stopped || controller.signal.aborted || revision !== this.revision) return
      this.failures = Math.min(this.failures + 1, 5)
      this.fail(error)
    } finally {
      this.running = false
      this.schedule()
    }
  }

  accept(station: Station) {
    this.revision++
    this.controller?.abort()
    this.failures = 0
    if (!this.stopped) this.apply(station)
    this.schedule()
  }

  pause() {
    this.revision++
    clearTimeout(this.timer)
    this.controller?.abort()
  }

  stop() {
    this.stopped = true
    this.revision++
    clearTimeout(this.timer)
    this.controller?.abort()
  }
}
