import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// O front fala com o servidor Python (porta 8000) por proxy, então a chave nunca passa pelo navegador
const API = process.env.ESTUDIO_API ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': API, '/files': API, '/saida': API, '/briefings': API },
  },
})
