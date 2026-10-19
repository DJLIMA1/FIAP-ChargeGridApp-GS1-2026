// Garante que o modo demonstração (src/mock) não foi para o build de produção.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const FORBIDDEN = ['mock-access', 'mock-refresh', 'installMock', 'mock_login', 'Modo demonstração', 'João Silva', 'VERAO10', 'Villa Lobos', 'chargegrid.mock', 'senhafraca', 'naoconfirmado']
const root = fileURLToPath(new URL('../dist/', import.meta.url))

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

const files = walk(root).filter((file) => /\.(js|css|html|json|map)$/.test(file))
const hits = []
for (const file of files) {
  const text = readFileSync(file, 'utf8')
  for (const needle of FORBIDDEN) if (text.includes(needle)) hits.push(`${file.replace(root, 'dist/')}: "${needle}"`)
}
if (hits.length) {
  console.error('Código de demonstração encontrado no build de produção:\n' + hits.join('\n'))
  process.exit(1)
}
console.log(`OK: ${files.length} arquivos verificados, nenhum vestígio do modo demonstração.`)
