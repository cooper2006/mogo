const svg = (paths: string) => `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`

export const shortcutIconCatalog = [
  { label: 'Document', value: 'document', svg: svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M8 13h8"/><path d="M8 17h6"/>') },
  { label: 'Newspaper', value: 'newspaper', svg: svg('<path d="M4 5h13a3 3 0 0 1 3 3v11H6a2 2 0 0 1-2-2Z"/><path d="M8 9h7M8 13h8M8 17h5"/>') },
  { label: 'Easel', value: 'easel', svg: svg('<rect x="4" y="3" width="16" height="10" rx="2"/><path d="M12 13v8M8 21h8M8 17l-3 4M16 17l3 4"/>') },
  { label: 'Search', value: 'search', svg: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>') },
  { label: 'Grid', value: 'grid', svg: svg('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>') },
  { label: 'Create', value: 'create', svg: svg('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>') },
  { label: 'Globe', value: 'globe', svg: svg('<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 0 20"/><path d="M12 2a15.3 15.3 0 0 0 0 20"/>') },
  { label: 'Earth', value: 'earth', svg: svg('<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 0 20M12 2a15.3 15.3 0 0 0 0 20"/>') },
  { label: 'Library', value: 'library', svg: svg('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5Z"/><path d="M8 6h8M8 10h7"/>') },
  { label: 'Briefcase', value: 'briefcase', svg: svg('<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18"/>') },
  { label: 'People', value: 'people', svg: svg('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>') },
  { label: 'QA', value: 'qa', svg: svg('<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4M12 17h.01"/>') },
  { label: 'Analytics', value: 'analytics', svg: svg('<path d="M4 19V5M4 19h16M8 15l3-4 3 2 5-7M18 6h2v2"/>') },
  { label: 'Albums', value: 'albums', svg: svg('<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M7 3h10M8 9h8M8 13h5"/>') },
  { label: 'Image', value: 'image', svg: svg('<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>') },
  { label: 'Language', value: 'language', svg: svg('<path d="M4 5h8M8 3v2M10 5c-.7 3.5-2.6 6-6 8M5 9c1.2 1.6 2.8 2.8 5 4M14 21l4-10 4 10M16 17h4"/>') },
  { label: 'Settings', value: 'settings', svg: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6V21h-4v-1a1.7 1.7 0 0 0-1-.6 1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1H3v-4h1a1.7 1.7 0 0 0 .6-1 1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6V3h4v1a1.7 1.7 0 0 0 1 .6 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.18.37.39.7.6 1h1v4h-1a1.7 1.7 0 0 0-.6 1Z"/>') },
  { label: 'Build', value: 'build', svg: svg('<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 0 0 5.4-5.4l-3 3-3-3 3-3Z"/>') },
  { label: 'Server', value: 'server', svg: svg('<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/>') },
  { label: 'Cart', value: 'cart', svg: svg('<circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/><path d="M2 3h3l3 12h10l2-8H7"/>') },
  { label: 'Shield', value: 'shield', svg: svg('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-5"/>') },
  { label: 'Stats', value: 'stats', svg: svg('<path d="M4 19V5M4 19h16"/><rect x="7" y="11" width="3" height="5"/><rect x="12" y="8" width="3" height="8"/><rect x="17" y="5" width="3" height="11"/>') },
]

export const shortcutIconOptions = shortcutIconCatalog.map(({ label, value }) => ({ label, value }))
