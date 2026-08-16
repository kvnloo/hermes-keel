import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Hermes Keel',
  description: 'A staged governance specification for mechanically verifiable Hermes Agent execution.',
  base: '/hermes-keel/',
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ['meta', { name: 'theme-color', content: '#1f6f5f' }],
  ],
  themeConfig: {
    nav: [
      { text: 'Guide', link: '/getting-started' },
      { text: 'Architecture', link: '/architecture' },
      { text: 'Evidence', link: '/level-0-evidence' },
      { text: 'Resources', link: '/resources' },
    ],
    sidebar: [
      {
        text: 'Hermes Keel',
        items: [
          { text: 'Overview', link: '/' },
          { text: 'Getting Started', link: '/getting-started' },
          { text: 'Architecture', link: '/architecture' },
          { text: 'Invariants and Levels', link: '/invariants-and-levels' },
          { text: 'Level 0 Evidence', link: '/level-0-evidence' },
          { text: 'Resources', link: '/resources' },
        ],
      },
    ],
    socialLinks: [
      { icon: 'github', link: 'https://github.com/kvnloo/hermes-keel' },
    ],
    editLink: {
      pattern: 'https://github.com/kvnloo/hermes-keel/edit/main/docs/:path',
      text: 'Edit this page on GitHub',
    },
    search: {
      provider: 'local',
    },
    footer: {
      message: 'Hermes Keel is currently limited to Level 0.',
      copyright: 'Released under the MIT License.',
    },
  },
})
