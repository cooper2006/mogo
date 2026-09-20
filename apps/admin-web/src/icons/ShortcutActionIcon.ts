import { defineComponent, h, type PropType } from 'vue'

type ActionKind = 'add' | 'save'

// Ionicons-style outline icons (the same xicons family used elsewhere in MOVO).
export const ShortcutActionIcon = defineComponent({
  name: 'ShortcutActionIcon',
  props: {
    kind: { type: String as PropType<ActionKind>, required: true },
  },
  setup(props) {
    return () => h('svg', {
      viewBox: '0 0 24 24',
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': '2',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      'aria-hidden': 'true',
    }, props.kind === 'add'
      ? [h('path', { d: 'M12 5v14M5 12h14' })]
      : [
          h('path', { d: 'M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7Z' }),
          h('path', { d: 'M17 3v4H7V3M7 21v-8h10v8' }),
        ])
  },
})
