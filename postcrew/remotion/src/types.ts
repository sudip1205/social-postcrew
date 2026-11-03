export type Caption = {text: string; start: number; end: number};
export type Svg = {body: string; w: number; h: number; color: boolean};   // an icon or clipart: the inner markup of an SVG (render/iconlib.py)
export type Box = {label: string; icon: string; t: number; svg?: Svg | null; state?: "" | "ok" | "busy" | "down"; count?: number | null};
export type Edge = {from: number; to: number; label: string; t: number; n?: number; drop?: boolean};
export type Step = {
  t: number; pointers: {name: string; at: number}[]; active: number[]; out: number[]; found: number[]; note: string; memo: string[];
};
export type Scene = {
  layout: "title" | "statement" | "points" | "code" | "diagram" | "flow" | "trace" | "stat" | "versus";
  title: string; items: string[]; code: string; language: string; seconds: number; captions: Caption[];
  nodes?: Box[]; edges?: Edge[]; cells?: string[]; steps?: Step[]; cues?: number[]; closing?: boolean; key?: number; clip?: Svg; engine?: string; versus?: Versus; answers?: {name: string; answer: string}[]; buttons?: {label: string; kind: string; svg?: Svg | null}[];
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
/** One side of a quiz round (postcrew/quiz.py tile_props): the screen only draws what it is given. */
export type VTile = {
  kind: "trace" | "link" | "curve" | "bars"; sub: string; counter: string; tone?: "good" | "bad" | "";
  cells?: string[]; step_s?: number; steps?: {active: number[]; found: number[]; out: number[]; note: string}[];
  src?: string; dst?: string; ms?: number; fail?: boolean; period?: number;
  label?: string; points?: number[][]; ymax?: number;
  unit?: string; bars?: {label: string; value: number; frac: number}[];
};
export type Versus = {
  round: number; rounds: number; a: VTile; b: VTile; winner: "A" | "B"; badge: string; caption: string;
  reveal_at: number; count_at: number[]; demo_s: number; start_s: number;
};
