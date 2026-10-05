import type { HTMLAttributes } from 'react';

type GlassSurfaceProps = HTMLAttributes<HTMLDivElement> & {
  tone?: 'clear' | 'smoked' | 'reading';
};

export function GlassSurface({ tone = 'clear', className = '', ...props }: GlassSurfaceProps) {
  return <div {...props} className={`glass glass--${tone} ${className}`.trim()} />;
}
