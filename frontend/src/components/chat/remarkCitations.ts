import type { Parent, Root, RootContent, Text } from 'mdast';

interface CitationReference extends Parent {
  type: 'citationReference';
  children: Text[];
  data: { hName: 'cite'; hProperties: { 'data-source-id': string } };
}

declare module 'mdast' {
  interface PhrasingContentMap { citationReference: CitationReference }
  interface RootContentMap { citationReference: CitationReference }
}

// Transform parsed text only, not HTML, code, image alt text, or links. Formatting
// and source resolution remain separate; no string-to-HTML substitutions.
export function remarkCitations(sourceIds: ReadonlySet<string>) {
  return function plugin() {
    return function transform(tree: Root) {
      function walk(parent: Parent) {
        const children: RootContent[] = [];
        for (const child of parent.children) {
          if (child.type === 'text') {
            let offset = 0;
            for (const match of child.value.matchAll(/\[(S[1-9]\d*)\]/g)) {
              if (!sourceIds.has(match[1])) continue;
              if (match.index > offset) children.push({ type: 'text', value: child.value.slice(offset, match.index) });
              children.push({ type: 'citationReference', children: [{ type: 'text', value: match[0] }],
                data: { hName: 'cite', hProperties: { 'data-source-id': match[1] } } });
              offset = match.index + match[0].length;
            }
            if (offset < child.value.length) children.push({ type: 'text', value: child.value.slice(offset) });
          } else {
            if ('children' in child && !['link', 'linkReference', 'image', 'imageReference', 'citationReference'].includes(child.type)) {
              walk(child);
            }
            children.push(child);
          }
        }
        parent.children = children;
      }
      walk(tree);
    };
  };
}
