import { defineComponent, h } from 'vue'

// Tabler chevron-down style icon, also available through xicons.
export const ShortcutGroupToggleIcon = defineComponent({
  name: 'ShortcutGroupToggleIcon',
  setup() {
    return () => h('svg', {
      xmlns: 'http://www.w3.org/2000/svg',
      viewBox: '0 0 24 24',
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': '2',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      'aria-hidden': 'true',
    }, [h('path', { d: 'm6 9 6 6 6-6' })])
  },
})
