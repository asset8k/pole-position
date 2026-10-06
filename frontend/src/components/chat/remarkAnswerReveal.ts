import type { Parent, Root, RootContent, Text } from 'mdast';

interface RevealWord extends Parent {
  type: 'revealWord';
  children: Text[];
  data: { hName: 'span'; hProperties: { className: string[] } };
}

declare module 'mdast' {
  interface PhrasingContentMap { revealWord: RevealWord }
  interface RootContentMap { revealWord: RevealWord }
}

// Parse the FULL Markdown first, then reveal parsed words. Never parse an
// unfinished Markdown prefix: emphasis, tables and citation labels stay valid.
export function remarkAnswerReveal(visibleCharacters: number) {
  return function plugin() {
    return function transform(tree: Root) {
      let remaining = visibleCharacters;
      function walk(parent: Parent) {
        const children: RootContent[] = [];
        for (const child of parent.children) {
          if (child.type === 'text') {
            for (const match of child.value.matchAll(/\S+\s*|\s+/gu)) {
              remaining -= match[0].length;
              if (remaining >= 0) children.push({ type: 'revealWord', children: [{ type: 'text', value: match[0] }],
                data: { hName: 'span', hProperties: { className: ['answer-reveal-word'] } } });
            }
          } else if (child.type === 'citationReference') {
            remaining -= child.children[0].value.length;
            if (remaining >= 0) children.push(child);
          } else if ('children' in child) {
            walk(child);
            if (child.children.length) children.push(child);
          } else {
            // Non-prose blocks are atomic; no broken code fences, HTML, images
            // or partial Unicode glyphs. React Markdown's safety rules still apply.
            const size = 'value' in child ? String(child.value).length
              : child.type === 'image' ? (child.alt ?? '').length : 1;
            remaining -= size;
            if (remaining >= 0) children.push(child);
          }
        }
        parent.children = children;
      }
      walk(tree);
    };
  };
}
