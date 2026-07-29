import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import './styles/main.css'

async function bootstrap() {
  if (window.__TAURI_INTERNALS__) {
    const { invoke } = await import('@tauri-apps/api/core')
    const [apiBase, apiToken] = await Promise.all([
      invoke('backend_url'),
      invoke('backend_token')
    ])
    window.__APC_DESKTOP_API_BASE__ = apiBase
    window.__APC_DESKTOP_API_TOKEN__ = apiToken
  }

  createApp(App).use(router).mount('#app')
}

bootstrap()
