import type { ReactNode, SVGProps } from 'react';

type IconName = 'plus' | 'menu' | 'close' | 'arrow-up' | 'arrow-out' | 'info' | 'tyre' | 'bolt' | 'coins' | 'history' | 'refresh' | 'edit' | 'trash';

const paths: Record<IconName, ReactNode> = {
  plus: <path d="M12 5v14M5 12h14" />,
  history: <><path d="M3 11a9 9 0 1 1 3 8M3 5v6h6" /><path d="M12 7v5l3 2" /></>,
  refresh: <><path d="M20 8a8 8 0 0 0-14-3L3 8m0-5v5h5M4 16a8 8 0 0 0 14 3l3-3m0 5v-5h-5" /></>,
  edit: <><path d="m15 4 5 5M4 20l5-1L20 8a3.5 3.5 0 0 0-5-5L4 14z" /></>,
  trash: <><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5m4-5v5" /></>,
  menu: <path d="M4 8h16M4 16h16" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  'arrow-up': <path d="M12 19V5m-6 6 6-6 6 6" />,
  'arrow-out': <path d="M6 18 18 6M7 6h11v11" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v.1" /></>,
  tyre: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4" /><path d="m6 6 3 3m6 6 3 3M6 18l3-3m6-6 3-3" /></>,
  bolt: <path d="m13 2-9 12h7l-1 8 10-13h-7z" />,
  coins: <><ellipse cx="9" cy="6" rx="6" ry="3" /><path d="M3 6v5c0 4 12 4 12 0V6M3 11v5c0 4 12 4 12 0m3-8c4 0 4 5 0 5m0 0c4 0 4 5 0 5" /></>,
};

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return (
    <svg {...props} viewBox="0 0 24 24" width="20" height="20" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false">
      {paths[name]}
    </svg>
  );
}
