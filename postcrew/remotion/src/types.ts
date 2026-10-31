export type Caption = {text: string; start: number; end: number};
export type Box = {label: string; icon: string; t: number};
export type Edge = {from: number; to: number; label: string; t: number};
export type Step = {
  t: number; pointers: {name: string; at: number}[]; active: number[]; out: number[]; found: number[]; note: string; memo: string[];
};
export type Scene = {
  layout: "title" | "statement" | "points" | "code" | "diagram" | "flow" | "trace";
  title: string; items: string[]; code: string; language: string; seconds: number; captions: Caption[];
  nodes?: Box[]; edges?: Edge[]; cells?: string[]; steps?: Step[]; cues?: number[]; closing?: boolean; key?: number;
};
/** The colours of a look: defined in postcrew/render/looks.py and sent with every render. */
export type Theme = {
  name: string; bg: string; surface: string; text: string; muted: string; rule: string; accent: string; accentSoft: string; highlight: string; positive: string;
};
export type VideoProps = {format: "short" | "long"; width: number; height: number; fps: number; theme: Theme; scenes: Scene[]};
export type Illustration =
  | {kind: "diagram"; nodes: string[]; focus: number}
  | {kind: "trace"; cells: string[]; found: number[]}
  | {kind: "code"; lines: string[]};
export type ThumbProps = {text: string; title: string; theme: Theme; illustration?: Illustration | null};
