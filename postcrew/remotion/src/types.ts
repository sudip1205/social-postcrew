export type Caption = {text: string; start: number; end: number};
export type Box = {label: string; icon: string; t: number};
export type Edge = {from: number; to: number; label: string; t: number};
export type Step = {
  t: number; pointers: {name: string; at: number}[]; active: number[]; out: number[]; found: number[]; note: string; memo: string[];
};
export type Scene = {
  layout: "title" | "statement" | "points" | "code" | "diagram" | "flow" | "trace";
  title: string; items: string[]; code: string; language: string; seconds: number; captions: Caption[];
  nodes?: Box[]; edges?: Edge[]; cells?: string[]; steps?: Step[]; cues?: number[];
};
export type VideoProps = {
  format: "short" | "long"; width: number; height: number; fps: number; scenes: Scene[];
};
export type ThumbProps = {text: string; title: string};
