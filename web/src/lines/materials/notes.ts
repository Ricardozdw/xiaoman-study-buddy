import type { NoteContent } from "./api";

export function cloneNoteContent(content: NoteContent): NoteContent {
  return {
    ...content,
    summaries: content.summaries.map((item) => ({ ...item })),
    knowledge_points: content.knowledge_points.map((item) => ({ ...item })),
    terms: content.terms.map((item) => ({ ...item })),
    ...(content.points ? { points: [...content.points] } : {}),
  };
}

export function contentForSave(content: NoteContent): NoteContent {
  const copy = cloneNoteContent(content);
  copy.points = copy.summaries.map((item) => item.text);
  return copy;
}

export function noteDraftError(title: string, content: NoteContent): string | null {
  if (!title.trim()) return "请给笔记留一个标题。";
  if (title.trim().length > 160) return "笔记标题请控制在 160 字以内。";
  if (content.summaries.some((item) => !item.text.trim())) return "重点内容不能为空。";
  if (content.knowledge_points.some((item) => !item.name.trim() || !item.explanation.trim())) return "知识点名称和解释不能为空。";
  if (content.terms.some((item) => !item.term.trim() || !item.definition.trim())) return "术语和解释不能为空。";
  return null;
}

// 保留原文字节范围，允许 PDF 抽取中的换行和全角字符差异。
export function quoteParts(text: string, quote?: string): { before: string; match: string; after: string } {
  if (!quote) return { before: text, match: "", after: "" };
  const exact = text.indexOf(quote);
  if (exact >= 0) return { before: text.slice(0, exact), match: text.slice(exact, exact + quote.length), after: text.slice(exact + quote.length) };
  const needle = quote.normalize("NFKC").replace(/\s+/gu, "");
  if (!needle) return { before: text, match: "", after: "" };
  let normalized = "";
  const starts: number[] = [], ends: number[] = [];
  let offset = 0;
  for (const char of text) {
    for (const normalizedChar of char.normalize("NFKC")) {
      if (/\s/u.test(normalizedChar)) continue;
      normalized += normalizedChar;
      for (let unit = 0; unit < normalizedChar.length; unit++) { starts.push(offset); ends.push(offset + char.length); }
    }
    offset += char.length;
  }
  const index = normalized.indexOf(needle);
  if (index < 0) return { before: text, match: "", after: "" };
  const start = starts[index], end = ends[index + needle.length - 1];
  return { before: text.slice(0, start), match: text.slice(start, end), after: text.slice(end) };
}
