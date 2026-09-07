import { Marked } from "marked";

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const md = new Marked({
  gfm: true,
  breaks: true,
  async: false,
  renderer: {
    // Raw HTML from the model is shown as text rather than injected into the DOM.
    html(token) {
      return escapeHtml(token.text);
    },
    link({ href, title, text }) {
      const t = title ? ` title="${escapeHtml(title)}"` : "";
      const safe = /^(https?:|mailto:)/i.test(href) ? href : "#";
      return `<a href="${escapeHtml(safe)}"${t} target="_blank" rel="noopener noreferrer">${text}</a>`;
    },
  },
});

/** Renders markdown to HTML. Result is meant for v-html inside a `.md` container. */
export function renderMarkdown(text: string): string {
  if (!text) return "";
  try {
    return md.parse(text) as string;
  } catch {
    return `<p>${escapeHtml(text)}</p>`;
  }
}
