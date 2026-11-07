import React from "react";
import {interpolate} from "remotion";
import {FONT, MONO, useT, useTheme} from "./theme";
import type {GraphStep, GraphViz, Scene} from "./types";

/** A real graph: the nodes and edges as they are (placed by postcrew/graphviz.py), walked as the voice speaks: the node being worked on,
 *  the ones done, the ones waiting (queue or stack), the edges followed and a value under a node. */
export const Graph: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const th = useTheme(), {t} = useT();
  const g = s.graph as GraphViz;
  const steps = g.steps ?? [];
  const k = steps.reduce((acc, st, i) => (st.t <= t ? i : acc), -1);
  const cur: GraphStep | undefined = k >= 0 ? steps[k] : undefined;
  const since = cur ? t - cur.t : 0;
  // a Short stacks the layers top to bottom; a long (wide) video lays them out left to right
  const W = short ? 920 : 1500, H = short ? 1080 : 600;
  const along = short ? H : W, across = short ? W : H;
  // the node size: as big as fits, but never so big that the edges between layers vanish under the circles
  const layers = new Set(g.nodes.map((n) => n.y)).size, widest = Math.max(...Array.from(new Set(g.nodes.map((n) => n.y))).map((y) => g.nodes.filter((n) => n.y === y).length));
  const R = Math.round(Math.max(30, Math.min(short ? 66 : 56, (along / Math.max(2, layers)) * 0.22, (across / Math.max(2, widest)) * 0.26)));
  const pad = R + 40;
  const at = new Map(g.nodes.map((n) => [n.name, short ? {x: pad + n.x * (W - 2 * pad), y: pad + n.y * (H - 2 * pad)}
                                                         : {x: pad + n.y * (W - 2 * pad), y: pad + n.x * (H - 2 * pad)}]));
  const appear = interpolate(t, [0, 0.5], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const pulse = interpolate(since, [0, 0.45], [0.8, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const inSet = (xs: string[] | undefined, n: string) => !!xs?.includes(n);
  const lit = new Set(cur?.edges ?? []);
  const weighted = g.edges.some((e) => e.w !== null && e.w !== undefined);

  const edges = g.edges.map((e, i) => {
    const a = at.get(e.a)!, b = at.get(e.b)!;
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.max(1, Math.hypot(dx, dy));
    const ux = dx / len, uy = dy / len;
    // stop at the node's rim (and leave room for the arrow head on a directed edge)
    const x1 = a.x + ux * R, y1 = a.y + uy * R, x2 = b.x - ux * (R + (g.directed ? 10 : 0)), y2 = b.y - uy * (R + (g.directed ? 10 : 0));
    const on = lit.has(i);
    const colour = on ? th.accent : th.rule;
    return (
      <g key={`e${i}`}>
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={colour} strokeWidth={on ? 9 : 5} strokeLinecap="round"
          markerEnd={g.directed ? `url(#${on ? "arrowOn" : "arrow"})` : undefined} />
        {weighted && e.w !== null && (
          <g>
            <rect x={(a.x + b.x) / 2 - 24} y={(a.y + b.y) / 2 - 21} width={48} height={42} rx={10} fill={th.bg} stroke={colour} strokeWidth={on ? 4 : 2} />
            <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 + 10} textAnchor="middle" fontFamily={MONO} fontWeight={700} fontSize={28}
              fill={on ? th.accent : th.muted}>{e.w}</text>
          </g>
        )}
      </g>
    );
  });

  const nodes = g.nodes.map((n) => {
    const p = at.get(n.name)!;
    const current = inSet(cur?.current, n.name), found = inSet(cur?.found, n.name), visited = inSet(cur?.visited, n.name);
    const frontier = inSet(cur?.frontier, n.name), out = inSet(cur?.out, n.name);
    const fill = found ? th.positive : current ? th.accent : visited ? th.accentSoft : th.surface;
    const stroke = found ? th.positive : current ? th.accent : frontier ? th.accent : visited ? th.accent : th.rule;
    const text = found || current ? "#fff" : th.text;
    const label = cur?.labels?.[n.name];
    const grow = current || found ? pulse : 1;
    return (
      <g key={n.name} opacity={out ? 0.3 : 1} transform={`translate(${p.x} ${p.y}) scale(${grow})`}>
        <circle r={R} fill={fill} stroke={stroke} strokeWidth={current || found || frontier ? 7 : 4} strokeDasharray={frontier && !visited && !current ? "14 9" : undefined} />
        <text y={Math.round(R * 0.32)} textAnchor="middle" fontFamily={MONO} fontWeight={700} fontSize={Math.round(R * 0.85)} fill={text}>{n.name}</text>
        {label !== undefined && (
          <g transform={`translate(${Math.round(R * 0.95)} ${-Math.round(R * 0.95)})`}>
            <rect x={-Math.max(30, label.length * 11 + 14)} y={-24} width={Math.max(60, label.length * 22 + 28)} height={44} rx={12} fill={th.highlight} />
            <text y={9} textAnchor="middle" fontFamily={MONO} fontWeight={700} fontSize={28} fill="#fff">{label}</text>
          </g>
        )}
      </g>
    );
  });

  const marker = (id: string, colour: string) => (
    <marker id={id} viewBox="0 0 10 10" refX={5} refY={5} markerWidth={4} markerHeight={4} orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill={colour} />
    </marker>
  );
  const legend: [string, React.CSSProperties][] = [
    ["now", {background: th.accent}], ["done", {background: th.accentSoft, border: `3px solid ${th.accent}`}],
    ["waiting", {border: `3px dashed ${th.accent}`}], ["answer", {background: th.positive}],
  ];
  return (
    <div style={{flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: short ? 30 : 14, paddingTop: short ? 20 : 0}}>
      {g.title && <div style={{fontFamily: FONT, fontSize: short ? 58 : 46, fontWeight: 700, letterSpacing: -1, color: th.text, textAlign: "center"}}>{g.title}</div>}
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{opacity: appear, overflow: "visible"}}>
        <defs>{marker("arrow", th.rule)}{marker("arrowOn", th.accent)}</defs>
        {edges}
        {nodes}
      </svg>
      {(cur?.frontier ?? []).length > 0 && (
        <div style={{display: "flex", alignItems: "center", gap: 14, fontFamily: MONO, fontSize: short ? 34 : 28, fontWeight: 700, color: th.text}}>
          <span style={{color: th.muted}}>waiting:</span>
          {cur!.frontier.map((n, i) => <span key={i} style={{padding: "4px 16px", borderRadius: 10, border: `3px dashed ${th.accent}`}}>{n}</span>)}
        </div>
      )}
      {cur?.note && <div style={{fontFamily: FONT, fontSize: short ? 54 : 40, fontWeight: 600, letterSpacing: -0.8, color: th.text, textAlign: "center",
        opacity: interpolate(since, [0, 0.3], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>{cur.note}</div>}
      <div style={{display: "flex", gap: 30, fontFamily: MONO, fontSize: short ? 28 : 24, color: th.muted}}>
        {legend.map(([name, st]) => <span key={name} style={{display: "inline-flex", alignItems: "center", gap: 10}}>
          <span style={{width: 24, height: 24, borderRadius: 12, boxSizing: "border-box", ...st}} />{name}</span>)}
      </div>
    </div>
  );
};
