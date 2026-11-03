export type Caption = {text: string; start: number; end: number};
export type Svg = {body: string; w: number; h: number; color: boolean};   // an icon or clipart: the inner markup of an SVG (render/iconlib.py)
export type Box = {label: string; icon: string; t: number; svg?: Svg | null; state?: "" | "ok" | "busy" | "down"; count?: number | null};
export type Edge = {from: number; to: number; label: string; t: number; n?: number; drop?: boolean};
export type Step = {
  t: number; pointers: {name: string; at: number}[]; active: number[]; out: number[]; found: number[]; note: string; memo: string[];
};
export type Scene = {
  layout: "title" | "statement" | "points" | "code" | "diagram" | "flow" | "trace" | "stat" | "codeviz" | "paths";
  title: string; items: string[]; code: string; language: string; seconds: number; captions: Caption[];
  nodes?: Box[]; edges?: Edge[]; cells?: string[]; steps?: Step[]; cues?: number[]; closing?: boolean; key?: number; clip?: Svg; viz?: Viz; paths?: PathsViz; buttons?: {label: string; kind: string; svg?: Svg | null}[];
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
/** The picture under the code (postcrew/codeviz.py props): a recursion tree growing call by call, or a table filling cell by cell. */
export type VizEvent = {t: number; kind: "call" | "base" | "hit" | "return"; node: number; line: number; value: number | null};
export type VizNode = {label: string; parent: number; dup: boolean; hit: boolean; value: number | null; x: number; y: number; depth: number};
export type VizCell = {label: string; arg: number; value: number; from: number[]; t: number; line: number};
export type Viz = {kind: "calls" | "table"; title: string; nodes?: VizNode[]; events?: VizEvent[]; leaves?: number; levels?: number; memo?: boolean; calls?: number; cells?: VizCell[]; combine?: string; plus?: number};
/** A staircase and every way up it (postcrew/pathviz.py props). */
export type PathsViz = {kind: "stairs"; title: string; n: number; moves: number[]; per: number; paths: {hops: number[]; label: string; t: number}[]};
