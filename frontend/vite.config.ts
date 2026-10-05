import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';
import { developmentProxy } from './config/proxy';

export default defineConfig(({ mode }) => {
  // Read only the frontend's server-side proxy setting, never the backend .env.
  const env = loadEnv(mode, process.cwd(), 'API_PROXY_');
  return {
    plugins: [react()],
    server: { proxy: developmentProxy(env.API_PROXY_TARGET) },
  };
});
