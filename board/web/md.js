/* 轻量 Markdown 渲染器：无外部依赖，先转义 HTML 再格式化，防止注入。 */
(function (global) {
  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function mdInline(text) {
    // 先保护行内代码，避免其中的 ** 等符号被误格式化
    const codes = [];
    text = String(text).replace(/`([^`\n]+)`/g, (_m, code) => {
      codes.push(esc(code));
      return `\u0000C${codes.length - 1}\u0000`;
    });
    text = esc(text);
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    text = text.replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      (_m, label, url) => `<a href="${esc(url)}" target="_blank" rel="noopener">${label}</a>`
    );
    text = text.replace(/\u0000C(\d+)\u0000/g, (_m, index) => `<code>${codes[Number(index)]}</code>`);
    return text;
  }

  function mdRender(src) {
    const lines = String(src || "").split(/\r?\n/);
    const out = [];
    let listType = null; // "ul" | "ol"
    let paragraph = [];
    let inCode = false;
    let codeBuffer = [];

    const flushParagraph = () => {
      if (paragraph.length) {
        out.push(`<p>${mdInline(paragraph.join(" "))}</p>`);
        paragraph = [];
      }
    };
    const flushList = () => {
      if (listType) {
        out.push(`</${listType}>`);
        listType = null;
      }
    };

    for (const raw of lines) {
      const line = raw.trimEnd();
      if (line.trim().startsWith("```")) {
        if (inCode) {
          out.push(`<pre class="md-code">${esc(codeBuffer.join("\n"))}</pre>`);
          codeBuffer = [];
          inCode = false;
        } else {
          flushParagraph();
          flushList();
          inCode = true;
        }
        continue;
      }
      if (inCode) {
        codeBuffer.push(line);
        continue;
      }
      const trimmed = line.trim();
      if (!trimmed) {
        flushParagraph();
        flushList();
        continue;
      }
      const heading = trimmed.match(/^(#{1,4})\s+(.*)$/);
      if (heading) {
        flushParagraph();
        flushList();
        const level = heading[1].length;
        out.push(`<h4 class="md-h md-h${level}">${mdInline(heading[2])}</h4>`);
        continue;
      }
      if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
        flushParagraph();
        flushList();
        out.push('<hr class="md-hr">');
        continue;
      }
      const bullet = trimmed.match(/^[-*+]\s+(.*)$/);
      if (bullet) {
        flushParagraph();
        if (listType !== "ul") {
          flushList();
          listType = "ul";
          out.push('<ul class="md-list">');
        }
        out.push(`<li>${mdInline(bullet[1])}</li>`);
        continue;
      }
      const ordered = trimmed.match(/^(\d+)[.)]\s+(.*)$/);
      if (ordered) {
        flushParagraph();
        if (listType !== "ol") {
          flushList();
          listType = "ol";
          out.push('<ol class="md-list">');
        }
        out.push(`<li>${mdInline(ordered[2])}</li>`);
        continue;
      }
      if (trimmed.startsWith("> ")) {
        flushParagraph();
        flushList();
        out.push(`<blockquote class="md-quote">${mdInline(trimmed.slice(2))}</blockquote>`);
        continue;
      }
      paragraph.push(trimmed);
    }

    if (inCode) out.push(`<pre class="md-code">${esc(codeBuffer.join("\n"))}</pre>`);
    flushParagraph();
    flushList();
    return out.join("");
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { mdRender, mdInline };
  }
  global.mdRender = mdRender;
})(typeof window !== "undefined" ? window : globalThis);
