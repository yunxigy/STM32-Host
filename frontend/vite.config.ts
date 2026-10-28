import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  base: '/stm32/',
  envDir: '..',
  server: {
    proxy: {
      '/stm32/api': {
        target: 'http://127.0.0.1:8007',
        changeOrigin: true,
        ws: true,
        rewrite: path => path.replace(/^\/stm32\/api/, ''),
      },
    },
  },
  test: { environment: 'jsdom' },
});
