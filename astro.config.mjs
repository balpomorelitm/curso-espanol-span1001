import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  integrations: [tailwind()],
  srcDir: 'src',
  // IMPORTANTE: Configuración para GitHub Pages
  site: 'https://balpomorelitm.github.io', // Tu usuario
  base: '/curso-espanol-span1001',         // El nombre de tu repositorio
});
