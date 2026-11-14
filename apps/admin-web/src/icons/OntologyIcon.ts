import { defineComponent, h } from 'vue';

export const OntologyIcon = defineComponent({
  name: 'OntologyIcon',
  setup: () => () => h('svg', {
    viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true',
  }, [
    // 中心节点 + 三个环绕节点，表达「本体（实体/关系图谱）」。
    h('circle', { cx: '12', cy: '12', r: '3' }),
    h('circle', { cx: '5', cy: '6', r: '2' }),
    h('circle', { cx: '19', cy: '6', r: '2' }),
    h('circle', { cx: '12', cy: '20', r: '2' }),
    h('path', { d: 'M6.6 7.4 10 10.4' }),
    h('path', { d: 'M17.4 7.4 14 10.4' }),
    h('path', { d: 'M12 15v3' }),
  ]),
});
