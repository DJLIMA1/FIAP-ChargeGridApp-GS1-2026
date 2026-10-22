// Painel mock for the pitch recordings: the normal owner-web config without HMR or file watching, so
// edits made elsewhere in the repo never reload the page (a reload = skeleton flash) in the middle of a take.
//   npx --prefix apps/owner-web vite --config tools/pitch_videos/vite.pitch.config.ts apps/owner-web --port 5181
import base from '../../apps/owner-web/vite.config'

export default (env: { mode: string; command: 'build' | 'serve' }) => {
  const config = (base as unknown as (env: unknown) => Record<string, any>)(env)
  return { ...config, server: { ...config.server, hmr: false, watch: null } }
}
