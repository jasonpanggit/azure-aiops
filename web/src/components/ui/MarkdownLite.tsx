import { Fragment } from "react";

export interface MarkdownLiteProps {
  text: string;
}

interface InlineToken {
  type: "text" | "bold" | "italic" | "code";
  value: string;
}

/** Splits a single line into bold/italic/code-aware inline tokens. Deliberately
 * narrow: only `**bold**`, `*italic*`/`_italic_`, and `` `code` `` are
 * recognised, which covers what the Foundry agent actually emits without
 * pulling in a full markdown/remark dependency chain for one chat surface. */
function tokenizeInline(line: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  const pattern = /(\*\*(.+?)\*\*|`(.+?)`|\*(.+?)\*|_(.+?)_)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(line)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({ type: "text", value: line.slice(lastIndex, match.index) });
    }
    if (match[2] !== undefined) tokens.push({ type: "bold", value: match[2] });
    else if (match[3] !== undefined) tokens.push({ type: "code", value: match[3] });
    else if (match[4] !== undefined) tokens.push({ type: "italic", value: match[4] });
    else if (match[5] !== undefined) tokens.push({ type: "italic", value: match[5] });
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < line.length) tokens.push({ type: "text", value: line.slice(lastIndex) });
  return tokens;
}

function InlineText({ line }: { line: string }) {
  return (
    <>
      {tokenizeInline(line).map((token, index) => {
        switch (token.type) {
          case "bold":
            return <strong key={index}>{token.value}</strong>;
          case "italic":
            return <em key={index}>{token.value}</em>;
          case "code":
            return (
              <code className="markdown-lite-code" key={index}>
                {token.value}
              </code>
            );
          default:
            return <Fragment key={index}>{token.value}</Fragment>;
        }
      })}
    </>
  );
}

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "paragraph"; text: string };

/** Groups raw lines into block-level structures: fenced code, headings,
 * bullet/numbered lists, and paragraphs (blank-line separated). */
function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    if (line.trim().startsWith("```")) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      index += 1; // skip closing fence
      blocks.push({ kind: "code", text: codeLines.join("\n") });
      continue;
    }

    const headingMatch = /^(#{1,4})\s+(.*)$/.exec(line);
    if (headingMatch) {
      blocks.push({ kind: "heading", level: headingMatch[1].length, text: headingMatch[2].trim() });
      index += 1;
      continue;
    }

    const bulletMatch = /^\s*[-*]\s+(.*)$/.exec(line);
    const numberedMatch = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bulletMatch || numberedMatch) {
      const ordered = Boolean(numberedMatch);
      const items: string[] = [(bulletMatch ?? numberedMatch)![1]];
      index += 1;
      while (index < lines.length) {
        const next = lines[index];
        const nextBullet = /^\s*[-*]\s+(.*)$/.exec(next);
        const nextNumbered = /^\s*\d+[.)]\s+(.*)$/.exec(next);
        const candidate = ordered ? nextNumbered : nextBullet;
        if (!candidate) break;
        items.push(candidate[1]);
        index += 1;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }

    const paragraphLines: string[] = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() !== "" &&
      !/^\s*[-*]\s+/.test(lines[index]) &&
      !/^\s*\d+[.)]\s+/.test(lines[index]) &&
      !/^#{1,4}\s+/.test(lines[index]) &&
      !lines[index].trim().startsWith("```")
    ) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraphLines.join(" ") });
  }

  return blocks;
}

/**
 * Renders the Foundry agent's narration text as headings, bullet/numbered
 * lists, paragraphs, inline emphasis, and code blocks, instead of one
 * `white-space: pre-wrap` blob. Kept dependency-free (no remark/rehype
 * chain) since this is the one surface that needs it.
 */
export function MarkdownLite({ text }: MarkdownLiteProps) {
  const blocks = parseBlocks(text);
  if (blocks.length === 0) return null;

  return (
    <div className="markdown-lite">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "heading": {
            const Tag = (`h${Math.min(block.level + 3, 6)}` as unknown) as "h4" | "h5" | "h6";
            return (
              <Tag key={index} className="markdown-lite-heading">
                <InlineText line={block.text} />
              </Tag>
            );
          }
          case "list": {
            const ListTag = block.ordered ? "ol" : "ul";
            return (
              <ListTag key={index} className="markdown-lite-list">
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>
                    <InlineText line={item} />
                  </li>
                ))}
              </ListTag>
            );
          }
          case "code":
            return (
              <pre className="markdown-lite-pre" key={index}>
                <code>{block.text}</code>
              </pre>
            );
          default:
            return (
              <p className="markdown-lite-paragraph" key={index}>
                <InlineText line={block.text} />
              </p>
            );
        }
      })}
    </div>
  );
}
