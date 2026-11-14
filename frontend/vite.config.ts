import { defineConfig, type Plugin } from 'vitest/config'
import react from '@vitejs/plugin-react'
import http from 'node:http'

function snakeToCamel(str: string): string {
  return str.replace(/_([a-z0-9])/g, (_, letter) => letter.toUpperCase())
}

function camelToSnake(str: string): string {
  return str.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
}

function transformKeys(data: unknown, fn: (k: string) => string): unknown {
  if (Array.isArray(data)) return data.map((item) => transformKeys(item, fn))
  if (data !== null && typeof data === 'object') {
    const res: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
      const transformedKey = fn(k)
      res[transformedKey] = transformKeys(v, fn)
      if (transformedKey !== k) {
        res[k] = res[transformedKey]
      }
    }
    return res
  }
  return data
}

function backendAdapterPlugin(): Plugin {
  return {
    name: 'backend-adapter-proxy',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url || !req.url.startsWith('/api')) {
          return next()
        }

        const urlObj = new URL(req.url, 'http://localhost:5173')
        const shiftKey = urlObj.searchParams.get('shiftKey')
        if (shiftKey && !urlObj.searchParams.has('shift_key')) {
          urlObj.searchParams.set('shift_key', shiftKey)
        }

        const chunks: Buffer[] = []
        req.on('data', (chunk) => chunks.push(chunk))
        req.on('end', () => {
          let reqBodyBuffer = Buffer.concat(chunks)
          const contentType = req.headers['content-type'] || ''
          if (contentType.includes('application/json') && reqBodyBuffer.length > 0) {
            try {
              const parsed = JSON.parse(reqBodyBuffer.toString('utf-8'))
              const transformed = transformKeys(parsed, camelToSnake)
              reqBodyBuffer = Buffer.from(JSON.stringify(transformed), 'utf-8')
            } catch {
              // keep unchanged
            }
          }

          const headers = { ...req.headers }
          headers.host = '127.0.0.1:8000'
          if (reqBodyBuffer.length > 0) {
            headers['content-length'] = String(reqBodyBuffer.length)
          } else {
            delete headers['content-length']
          }

          const targetUrl = new URL(urlObj.pathname + urlObj.search, 'http://127.0.0.1:8000')
          const proxyReq = http.request(
            targetUrl,
            {
              method: req.method,
              headers,
            },
            (proxyRes) => {
              const resChunks: Buffer[] = []
              proxyRes.on('data', (c) => resChunks.push(c))
              proxyRes.on('end', () => {
                let resBody = Buffer.concat(resChunks)
                const resContentType = proxyRes.headers['content-type'] || ''
                if (
                  (resContentType.includes('application/json') ||
                    resContentType.includes('application/problem+json')) &&
                  resBody.length > 0
                ) {
                  try {
                    const parsed = JSON.parse(resBody.toString('utf-8'))
                    const transformed = transformKeys(parsed, snakeToCamel)
                    resBody = Buffer.from(JSON.stringify(transformed), 'utf-8')
                  } catch {
                    // keep unchanged
                  }
                }

                const responseHeaders = { ...proxyRes.headers }
                responseHeaders['content-length'] = String(resBody.length)
                res.writeHead(proxyRes.statusCode || 200, responseHeaders)
                res.end(resBody)
              })
            }
          )

          proxyReq.on('error', (err) => {
            res.writeHead(502, { 'Content-Type': 'application/problem+json' })
            res.end(
              JSON.stringify({
                type: 'about:blank',
                title: 'Bad Gateway',
                status: 502,
                detail: `Backend server unreachable on http://127.0.0.1:8000 (${err.message})`,
              })
            )
          })

          if (reqBodyBuffer.length > 0) {
            proxyReq.write(reqBodyBuffer)
          }
          proxyReq.end()
        })
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), backendAdapterPlugin()],
  server: {
    port: 5173,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
