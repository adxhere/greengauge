import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development, /api calls go to the analytics service on port 8000.
// In Docker, nginx does the same job (see nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: { '/api': process.env.API_URL || 'http://localhost:8000' },
  },
});
