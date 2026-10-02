// dsh-origin-thesis — DSH bundle entry artifact
// ============================================
// A *Python* MCP plugin: the real server is thesis_mcp_server.py, launched by
// DSH through the mcp-origin-thesis loader entry (cordis.patch.yml →
// @deepseek-ai/dsh-mcp-client, stdio).
//
// The server deliberately implements the MCP stdio JSON-RPC loop itself (same
// approach as dsh-origin-plugin's origin_mcp_server.py `_sync_stdio_server`),
// so it needs no `mcp` package and runs on python 3.9 or 3.10. It is launched
// with an interpreter that has originpro available (originpro ships wheels up
// to python 3.9 only).
//
// This module carries a no-op `apply` so the cordis loader creates a fiber for
// the bundle itself; the real capability is the cordis.patch.yml insert.

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const pkg = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf8'),
)

const pluginRoot = path.dirname(fileURLToPath(import.meta.url))

/** Static descriptor of this DSH bundle (kept in sync with package.json). */
export const plugin = {
  name: pkg.name,
  version: pkg.version,
  kind: 'python-mcp-bundle',
  server: 'thesis_mcp_server.py',
  loader: 'mcp-origin-thesis (@deepseek-ai/dsh-mcp-client, stdio)',
  layout: '12 MCP tools · thesis/composite style profiles · styles.json driven',
  requires: {
    os: 'win32',
    origin: 'OriginLab Origin 2018+ installed locally (COM automation)',
    python: 'interpreter with originpro + numpy + Pillow (originpro: py<=3.9)',
  },
  note: 'Ships the plotting scripts in-package; override DSH_THESIS_BATCH_DIR ' +
    'to use your own origin-batch-style checkout. Styles live in styles.json.',
  root: pluginRoot,
}

export function describe() {
  return plugin
}

/** Cordis plugin entry. Must return undefined: cordis treats apply()'s return
 *  value as an effect, and returning a plain object throws
 *  `TypeError: Invalid effect` (crashing DSH startup — same pitfall documented
 *  in dsh-origin-plugin/index.js). */
export default {
  ...plugin,
  apply() {
    return void 0
  },
}
