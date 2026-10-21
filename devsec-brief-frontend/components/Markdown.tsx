"use client";

import React from "react";

// Minimal zero-dependency markdown renderer:
// headings, bold, italic, inline code, fenced code, lists,
// blockquote, links, tables (basic), paragraphs, hr.
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  // links, bold, italic, inline code
  const re =
    /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyPrefix}-${k++}`;
    if (tok.startsWith("`")) {
      out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    } else if (tok.startsWith("**")) {
      out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("*") || tok.startsWith("_")) {
      out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    } else if (tok.startsWith("[")) {
      const lm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok);
      if (lm) {
        out.push(
          <a key={key} href={lm[2]} target="_blank" rel="noreferrer">
            {lm[1]}
          </a>
        );
      } else {
        out.push(tok);
      }
    } else {
      out.push(tok);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function Markdown({ text }: { text: string }) {
  // LLMs sometimes emit a stray asterisk after a bold label ("**Type:***")
  // and start a bullet list right after a label without a blank line. Normalize
  // both so the minimal renderer doesn't print markdown punctuation literally.
  const normalizedLines = text
    .replace(/(\*\*[^*\n]+\*\*)\*/g, "$1")
    .split("\n")
    .map((line) => {
      const boldNumber = /^\*\*(\d+[.)])\s+(.*?)\*\*\s*$/.exec(line);
      return boldNumber
        ? `${boldNumber[1]} **${boldNumber[2]}**`
        : line;
    });
  const normalized = normalizedLines
    .map((line, i) => {
      const startsList = /^\s*[-*+]\s+/.test(line);
      const prevIsList = /^\s*(?:\d+[.)]|[-*+])\s+/.test(
        normalizedLines[i - 1] ?? ""
      );
      return startsList && i > 0 && !prevIsList ? `\n${line}` : line;
    })
    .join("\n");
  const blocks = normalized.split(/\n{2,}/);
  const elements: React.ReactNode[] = [];
  let i = 0;

  for (const raw of blocks) {
    const block = raw.trimEnd();
    if (!block.trim()) continue;
    const key = `b-${i++}`;

    // fenced code block
    if (block.startsWith("```")) {
      const lines = block.split("\n");
      lines.shift();
      if (lines.length > 0 && lines[lines.length - 1].trim() === "```")
        lines.pop();
      elements.push(
        <pre key={key}>
          <code>{lines.join("\n")}</code>
        </pre>
      );
      continue;
    }
    // headings
    const h = /^(#{1,4})\s+(.*)$/.exec(block.trim());
    if (h) {
      const level = h[1].length;
      const content = renderInline(h[2], key);
      if (level === 1) elements.push(<h1 key={key}>{content}</h1>);
      else if (level === 2) elements.push(<h2 key={key}>{content}</h2>);
      else if (level === 3) elements.push(<h3 key={key}>{content}</h3>);
      else elements.push(<h4 key={key}>{content}</h4>);
      continue;
    }
    // hr
    if (/^(-{3,}|\*{3,})$/.test(block.trim())) {
      elements.push(<hr key={key} />);
      continue;
    }
    // blockquote
    if (block.trim().split("\n").every((l) => l.trim().startsWith(">"))) {
      const inner = block
        .trim()
        .split("\n")
        .map((l) => l.trim().replace(/^>\s?/, ""))
        .join("\n");
      elements.push(
        <blockquote key={key}>{renderInline(inner, key)}</blockquote>
      );
      continue;
    }
    // table (basic GFM)
    const tlines = block.trim().split("\n");
    if (
      tlines.length >= 2 &&
      tlines[0].includes("|") &&
      /^\|?[\s:|-]+\|?[\s:|.-]*$/.test(tlines[1])
    ) {
      const head = tlines[0]
        .split("|")
        .map((c) => c.trim())
        .filter(Boolean);
      const rows = tlines.slice(2).map((r) =>
        r
          .split("|")
          .map((c) => c.trim())
          .filter(Boolean)
      );
      elements.push(
        <table key={key}>
          <thead>
            <tr>
              {head.map((c, ci) => (
                <th key={ci}>{renderInline(c, `${key}-h${ci}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri}>
                {r.map((c, ci) => (
                  <td key={ci}>{renderInline(c, `${key}-r${ri}c${ci}`)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
      continue;
    }
    // lists (including indented sub-bullets and wrapped item text)
    const ll = block.trim().split("\n");
    const firstMarker = /^(\s*)([-*+]|\d+[.)])\s+/.exec(ll[0]);
    if (firstMarker) {
      const ordered = /^\d/.test(firstMarker[2]);
      const baseIndent = firstMarker[1].length;
      const start = ordered ? Number.parseInt(firstMarker[2], 10) : undefined;
      const items: { text: string; sub: string[]; cont: string[] }[] = [];
      let current: (typeof items)[number] | null = null;

      for (const line of ll) {
        if (!line.trim()) continue;
        const indent = (line.match(/^\s*/)?.[0].length ?? 0);
        const marker = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line);
        if (marker) {
          const markerOrdered = /^\d/.test(marker[2]);
          const isTopLevel =
            !current ||
            (markerOrdered === ordered && indent <= baseIndent);
          if (isTopLevel) {
            current = { text: marker[3], sub: [], cont: [] };
            items.push(current);
          } else if (current) {
            current.sub.push(marker[3]);
          }
        } else if (current) {
          current.cont.push(line.trim());
        }
      }

      if (items.length > 0) {
        const list = items.map((item, li) => (
          <li key={li}>
            {renderInline(item.text, `${key}-li${li}`)}
            {item.cont.map((line, ci) => (
              <React.Fragment key={ci}>
                <br />
                {renderInline(line, `${key}-li${li}-c${ci}`)}
              </React.Fragment>
            ))}
            {item.sub.length > 0 && (
              <ul>
                {item.sub.map((sub, si) => (
                  <li key={si}>
                    {renderInline(sub, `${key}-li${li}-s${si}`)}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ));

        elements.push(
          ordered ? (
            <ol key={key} start={start && start !== 1 ? start : undefined}>
              {list}
            </ol>
          ) : (
            <ul key={key}>{list}</ul>
          )
        );
        continue;
      }
    }
    // paragraph (preserve single newlines)
    const lines = block.split("\n");
    elements.push(
      <p key={key}>
        {lines.map((l, li) => (
          <React.Fragment key={li}>
            {li > 0 && <br />}
            {renderInline(l, `${key}-l${li}`)}
          </React.Fragment>
        ))}
      </p>
    );
  }

  return <div className="md-body">{elements}</div>;
}
