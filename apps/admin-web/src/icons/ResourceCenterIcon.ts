import { defineComponent, h } from 'vue';

export const ResourceCenterIcon = defineComponent({
  name: 'ResourceCenterIcon',
  setup() {
    return () =>
      h(
        'svg',
        {
          xmlns: 'http://www.w3.org/2000/svg',
          viewBox: '0 0 24 24',
          fill: 'none',
        },
        [
          h('path', {
            d: 'M3 7a2 2 0 0 1 2-2h5.5a1.5 1.5 0 0 1 1.118.494l2.5 2.75A1.5 1.5 0 0 0 14.5 9H19a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-1.5a1.5 1.5 0 0 1-1.118-.494l-2.5-2.75A1.5 1.5 0 0 0 11.5 13H7a2 2 0 0 1-2-2V7z',
            fill: 'currentColor',
            opacity: '0.35',
          }),
          h('path', {
            d: 'M5 6.5a.5.5 0 0 1 .5-.5h5.5a.5.5 0 0 1 .376.173l2.5 2.75a.5.5 0 0 0 .376.177H19a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-1.5a.5.5 0 0 1-.376-.173l-2.5-2.75a.5.5 0 0 0-.376-.177H7a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1zm0 4.5v3.5a.5.5 0 0 0 .5.5h4.5a.5.5 0 0 0 .376-.173l2.5-2.75a.5.5 0 0 1 .376-.177H18v-2h-1.5a.5.5 0 0 1-.376-.173l-2.5-2.75A.5.5 0 0 0 13.248 7H7.5a.5.5 0 0 0-.5.5v3z',
            fill: 'currentColor',
          }),
          h('circle', {
            cx: '8.5',
            cy: '10.5',
            r: '1.25',
            fill: 'currentColor',
            opacity: '0.5',
          }),
          h('circle', {
            cx: '13.5',
            cy: '10.5',
            r: '1.25',
            fill: 'currentColor',
            opacity: '0.5',
          }),
          h('circle', {
            cx: '16.5',
            cy: '15.5',
            r: '1.25',
            fill: 'currentColor',
            opacity: '0.5',
          }),
        ],
      );
  },
});