import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { NoteItem } from "../../api/types";
import type { Lecture } from "../qa/types";
import { formatPages, readNote, readPages, type Citation, type MaterialNote, type MaterialPage } from "./api";

/** Owns materials state; the shared shell only supplies navigation and layout. */
export function useMaterialsWorkspace(explicitLectureId: string, baseCurrentLectureId: string, sessionReady: boolean, selectLecture: (id: string) => void) {
  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [lectures, setLectures] = useState<Lecture[] | null>(null);
  const [currentLectureId, setCurrentLectureId] = useState("");
  const lectureId = explicitLectureId || baseCurrentLectureId || currentLectureId;
  const [listError, setListError] = useState("");
  const [note, setNote] = useState<MaterialNote | null>(null);
  const [requested, setRequested] = useState<{ id: string; lectureId: string } | null>(null);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");
  const [citation, setCitation] = useState<Citation | null>(null);
  const [originalText, setOriginalText] = useState("");
  const [openingOriginal, setOpeningOriginal] = useState(false);
  const [originalError, setOriginalError] = useState("");
  const request = useRef<AbortController | null>(null);
  const originalRequest = useRef<AbortController | null>(null);
  const listVersion = useRef(0);

  const refresh = useCallback(async () => {
    const version = ++listVersion.current;
    const [result, courses] = await Promise.all([
      api<{ items: NoteItem[] }>("/api/notes"),
      api<{ items: Lecture[]; current_lecture_id: string }>("/api/qa/lectures"),
    ]);
    if (version !== listVersion.current) return;
    if (result.source === "api") {
      setNotes(result.envelope.mock === false ? result.envelope.data.items.filter(item => (item as NoteItem & { mock?: boolean }).mock === false) : []);
      setListError("");
    } else setListError("资料列表暂时没能读取，请稍后重试。");
    if (courses.source === "api") {
      setLectures(courses.envelope.data.items);
      setCurrentLectureId(courses.envelope.data.current_lecture_id);
    }
  }, []);

  useEffect(() => {
    if (sessionReady) void refresh();
    return () => { listVersion.current += 1; };
  }, [sessionReady, refresh]);

  useEffect(() => {
    setNote(null); setError(""); setOpening(false);
    setCitation(null); setOriginalText(""); setOriginalError(""); setOpeningOriginal(false);
    originalRequest.current?.abort();
  }, [lectureId]);

  useEffect(() => {
    if (!requested || requested.lectureId !== lectureId) return;
    const controller = new AbortController(); request.current = controller;
    setOpening(true); setError("");
    void readNote(requested.id, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (result.lecture_id !== requested.lectureId) throw new Error("笔记与所选讲次不一致，请重新打开。");
      setNote(result);
    }).catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "笔记打开失败，请重试。");
    }).finally(() => { if (!controller.signal.aborted) setOpening(false); });
    return () => controller.abort();
  }, [requested, lectureId]);

  useEffect(() => () => { request.current?.abort(); originalRequest.current?.abort(); }, []);

  function cancelNoteRequest() {
    request.current?.abort(); setRequested(null); setOpening(false); setError("");
  }
  function openStored(item: NoteItem) {
    cancelNoteRequest(); originalRequest.current?.abort();
    setNote(null); setCitation(null); setOriginalError(""); setOpeningOriginal(false);
    selectLecture(item.lecture_id); setRequested({ id: item.id, lectureId: item.lecture_id });
    setOpening(true);
  }
  function showNote(value: MaterialNote | null) { cancelNoteRequest(); setNote(value); }
  function showOriginal(pages: MaterialPage[]) {
    cancelNoteRequest(); originalRequest.current?.abort();
    setCitation(null); setOriginalError(""); setOpeningOriginal(false); setOriginalText(formatPages(pages));
  }
  async function openCitation(value: Citation) {
    if (!note || note.lecture_id !== lectureId) return;
    originalRequest.current?.abort();
    const controller = new AbortController(); originalRequest.current = controller;
    setCitation(value); setOriginalText(""); setOpeningOriginal(true); setOriginalError("");
    try {
      const result = await readPages(note.lecture_id, controller.signal, note.content.file_id);
      if (controller.signal.aborted) return;
      const page = result.pages.find(item => item.page === value.page && item.mock === false);
      if (!page) throw new Error("没有找到这条出处对应的原文页，请重新打开笔记后重试。");
      setOriginalText(formatPages([page]));
    } catch (reason) {
      if (!controller.signal.aborted) setOriginalError(reason instanceof Error ? reason.message : "读取出处失败，请重试。");
    } finally { if (!controller.signal.aborted) setOpeningOriginal(false); }
  }
  function clearOriginal() {
    originalRequest.current?.abort(); setCitation(null); setOriginalText(""); setOriginalError(""); setOpeningOriginal(false);
  }
  return { lectureId, notes, lectures, currentLectureId, listError, note, opening, error, citation, originalText, openingOriginal, originalError,
    refresh, openStored, showNote, showOriginal, openCitation, clearOriginal, cancelNoteRequest };
}
