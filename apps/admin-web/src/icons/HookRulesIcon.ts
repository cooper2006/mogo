import { defineComponent, h } from 'vue';

export const HookRulesIcon = defineComponent({
  name: 'HookRulesIcon',
  setup() {
    return () => h('svg', {
      xmlns: 'http://www.w3.org/2000/svg', viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
      'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    }, [
      h('path', { d: 'M9 12h6' }),
      h('path', { d: 'M12 9v6' }),
      h('path', { d: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z' }),
      h('path', { d: 'm5 5 14 14' }),
    ]);
  },
});
