import type { ReactNode } from 'react'
import type { AlertItem } from '../api/types'
import { SEVERITY } from '../lib/labels'
import { Icon } from './Icon'
import { Badge } from './ui'

const ALERT_ICON: Record<string, 'wifiOff' | 'alert' | 'plug' | 'info' | 'clock'> = {
  device_offline: 'wifiOff',
  device_fault: 'alert',
  no_device: 'plug',
  command_failed: 'alert',
  point_idle: 'clock',
}

export function AlertRow({ alert, action }: { alert: AlertItem; action?: ReactNode }) {
  const severity = SEVERITY[alert.severity] ?? SEVERITY.info
  const tile = alert.severity === 'critical' ? 'red' : alert.severity === 'warning' ? 'amber' : ''
  return (
    <div className="list-row">
      <span className={`tile ${tile}`} style={{ width: 40, height: 40 }}>
        <Icon name={ALERT_ICON[alert.kind] ?? 'info'} size={19} />
      </span>
      <div className="grow">
        <div className="title">{alert.title}</div>
        <div className="sub">{alert.detail}</div>
      </div>
      <Badge tone={severity.tone}>{severity.label}</Badge>
      {action}
    </div>
  )
}
