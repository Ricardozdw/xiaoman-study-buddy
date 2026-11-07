// 规则 9：来自学习大纲资料的回答要标明没有出处。
// 问答接口把文件名放在 GET /api/qa/lectures 的 title 上；文件名以「AI 学习大纲」开头即是大纲资料。

export const OUTLINE_FILENAME_PREFIX = "AI 学习大纲";
export const OUTLINE_BADGE = "通用知识，没有出处";

export function isOutlineFilename(name: string | null | undefined): boolean {
  return typeof name === "string" && name.startsWith(OUTLINE_FILENAME_PREFIX);
}

export function outlineLectureIds(lectures: { id: string; title?: string }[]): Set<string> {
  return new Set(lectures.filter((item) => isOutlineFilename(item.title)).map((item) => item.id));
}

export function answerUsesOutlineSource(
  input: { references?: { lecture_id?: string }[]; handoffIntent?: string; lectureId?: string },
  lectures: { id: string; title?: string }[],
): boolean {
  const ids = outlineLectureIds(lectures);
  if ((input.references || []).some((ref) => typeof ref.lecture_id === "string" && ids.has(ref.lecture_id))) return true;
  return input.handoffIntent === "quiz" && typeof input.lectureId === "string" && ids.has(input.lectureId);
}
