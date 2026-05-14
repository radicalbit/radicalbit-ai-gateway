import { defineConfig, loadEnv } from 'vite';
import path from 'path';
import react from '@vitejs/plugin-react';
import svgr from 'vite-plugin-svgr';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd());
  const backendUrl = env.VITE_GATEWAY_ORIGIN || 'http://localhost:9000';

  return {
    plugins: [react(), svgr({ include: '**/*.svg' })],
    server: {
      port: 5173,
      proxy: {
        '/auth': {
          target: backendUrl,
        },
        '/public': {
          target: backendUrl,
        },
      },
    },
    optimizeDeps: {
      force: true,
      include: ['@radicalbit/radicalbit-design-system'],
    },
    resolve: {
      alias: {
        '@Api': path.resolve(__dirname, 'src/api/'),
        '@Components': path.resolve(__dirname, 'src/components/'),
        '@Container': path.resolve(__dirname, 'src/container/'),
        '@Helpers': path.resolve(__dirname, 'src/helpers/'),
        '@Hooks': path.resolve(__dirname, 'src/hooks/'),
        '@Img': path.resolve(__dirname, 'src/resources/images/'),
        '@Modals': path.resolve(__dirname, 'src/components/modals'),
        '@Src': path.resolve(__dirname, 'src/'),
        '@State': path.resolve(__dirname, 'src/store/state'),
        '@Store': path.resolve(__dirname, 'src/store/'),
        '@Styles': path.resolve(__dirname, 'src/styles/'),
      },
    },
  };
});
