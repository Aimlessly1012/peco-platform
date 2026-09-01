import { defineConfig } from 'umi';

export default defineConfig({
  routes: [
    {
      path: '/',
      component: '@/layouts/index',
      routes: [
        { path: '/home', component: '@/pages/home' },
        { path: '/admin/users', component: '@/pages/admin/users' },
        { path: '/admin/roles', component: '@/pages/admin/roles' },
      ],
    },
  ],
});
