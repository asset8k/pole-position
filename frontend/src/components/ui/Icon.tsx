import type { ReactNode, SVGProps } from 'react';

type IconName = 'plus' | 'menu' | 'close' | 'arrow-up' | 'arrow-out' | 'info' | 'tyre' | 'bolt' | 'coins';

const paths: Record<IconName, ReactNode> = {
  plus: <path d="M12 5v14M5 12h14" />,
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
