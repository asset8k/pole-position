import { describe, expect, it } from 'vitest';
import { developmentProxy } from '../../config/proxy';

describe('development proxy', () => {
  it('forwards /api to local FastAPI without stripping its prefix', () => {
    expect(developmentProxy()).toEqual({
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    });
    expect(developmentProxy()['/api']).not.toHaveProperty('rewrite');
  });

  it('supports a configured development backend origin', () => {
    expect(developmentProxy('http://localhost:9000/')['/api'].target).toBe('http://localhost:9000');
  });

  it.each(['ftp://example.test', 'http://user:pass@localhost:8000', 'http://localhost:8000/api',
    'http://localhost:8000?secret=1', 'http://localhost:8000#fragment'])
    ('rejects unsafe or misleading proxy targets: %s', (target) => {
      expect(() => developmentProxy(target)).toThrow(TypeError);
    });
});
