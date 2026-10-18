import { useState } from 'react'
import { ApiError } from '../api/client'
import type { OwnerInsights } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Icon, type IconName } from '../components/Icon'
import { Badge, Banner, Card, EmptyState, ErrorBanner, PageHead, Skeleton } from '../components/ui'
import { useFilters } from '../lib/filters'
import { formatDateTime } from '../lib/format'
import { IMPACT, INSIGHT_KIND } from '../lib/labels'
import { periodLabel } from '../lib/period'

const RULES_MODEL = 'chargegrid-regras'
const KIND_ICON: Record<string, IconName> = { pricing: 'wallet', operations: 'gauge', marketing: 'users' }

function insightError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'ai_rate_limited' || error.status === 429) return 'Você atingiu o limite de análises por agora. Tente novamente mais tarde.'
    if (error.code === 'ai_unavailable' || error.code === 'ai_timeout' || error.code === 'timeout')
      return 'O assistente de IA está indisponível no momento. Seus indicadores continuam disponíveis na Visão geral.'
    return error.message
  }
  return 'Não foi possível gerar os insights agora.'
}

export default function Insights() {
  const { ep } = useAuth()
  const { query, period, stationId, stations } = useFilters()
  const [result, setResult] = useState<OwnerInsights | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const station = stations.find((s) => s.id === stationId)
  const scope = `${periodLabel(period)} · ${station ? station.name : 'Todas as estações'}`
  const [analyzed, setAnalyzed] = useState<string | null>(null)

  const generate = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await ep.insights(query)
      setResult(response)
      setAnalyzed(scope)
    } catch (err) {
      setError(insightError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <PageHead
        title="Insights IA"
        sub="Recomendações de preço, operação e marketing a partir dos seus indicadores"
        actions={
          <button type="button" className="btn btn-primary" onClick={generate} disabled={loading}>
            <Icon name="sparkles" size={17} /> {loading ? 'Analisando…' : result ? 'Gerar novamente' : 'Gerar insights'}
          </button>
        }
      />
      <div className="stack">
        <Banner tone="info" title={`Análise de ${scope}`}>
          A IA lê apenas indicadores agregados (receita, energia, ocupação, picos e alertas) — nenhum dado pessoal de motoristas. As sugestões podem conter erros; revise antes de aplicar.
        </Banner>
        {error ? <ErrorBanner error={error} title="Insights indisponíveis" onRetry={generate} /> : null}
        {loading ? (
          <Card>
            <div className="stack">
              <Skeleton height={22} width="70%" />
              <Skeleton height={16} width="95%" />
              <Skeleton height={16} width="88%" />
              <Skeleton height={90} radius={14} />
              <Skeleton height={90} radius={14} />
            </div>
          </Card>
        ) : null}
        {!loading && !result && !error ? (
          <Card>
            <EmptyState
              icon="sparkles"
              title="Pronto para analisar sua operação"
              action={
                <button type="button" className="btn btn-primary btn-lg" onClick={generate} style={{ marginTop: 8, minWidth: 240 }}>
                  <Icon name="sparkles" size={18} /> Gerar insights
                </button>
              }
            >
              Escolha o período e a estação no topo e gere um resumo com recomendações práticas.
            </EmptyState>
          </Card>
        ) : null}
        {!loading && result ? (
          <>
            <Card
              title="Resumo"
              sub={`${analyzed ?? scope} · gerado em ${formatDateTime(result.generated_at)}`}
              action={result.model === RULES_MODEL ? <Badge tone="amber">Regras automáticas</Badge> : <Badge tone="green">IA</Badge>}
            >
              <p className="summary-text">{result.summary}</p>
              {result.model === RULES_MODEL ? (
                <p className="dim" style={{ margin: '12px 0 0', fontSize: 12.5 }}>
                  O modelo de IA não respondeu; as recomendações abaixo foram calculadas por regras a partir dos mesmos indicadores.
                </p>
              ) : null}
            </Card>
            <Card title="Recomendações" sub={`${result.recommendations.length} sugestão(ões)`}>
              {result.recommendations.length ? (
                <div className="stack" style={{ gap: 12 }}>
                  {result.recommendations.map((rec, index) => {
                    const impact = IMPACT[rec.impact] ?? IMPACT.medium
                    return (
                      <article className="insight" key={`${rec.title}-${index}`}>
                        <span className="tile white">
                          <Icon name={KIND_ICON[rec.kind] ?? 'trendUp'} size={21} />
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 4 }}>
                            <h4 style={{ margin: 0 }}>{rec.title}</h4>
                            <Badge tone={impact.tone}>{impact.label}</Badge>
                            <Badge tone="gray" plain>
                              {INSIGHT_KIND[rec.kind] ?? rec.kind}
                            </Badge>
                          </div>
                          <p>{rec.detail}</p>
                        </div>
                      </article>
                    )
                  })}
                </div>
              ) : (
                <EmptyState icon="check" title="Sem recomendações agora">
                  Não encontramos ajustes relevantes para este período.
                </EmptyState>
              )}
            </Card>
          </>
        ) : null}
      </div>
    </>
  )
}
