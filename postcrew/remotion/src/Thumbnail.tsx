import React from "react";
import {AbsoluteFill} from "remotion";
import {C, FONT} from "./theme";
import type {ThumbProps} from "./types";

export const Thumbnail: React.FC<ThumbProps> = ({text, title}) => (
  <AbsoluteFill style={{background: `radial-gradient(circle at 20% 10%, #2a2160 0%, ${C.bg} 60%)`, fontFamily: FONT, padding: 80, justifyContent: "center"}}>
    <div style={{color: C.text, fontSize: 124, fontWeight: 800, lineHeight: 1.04, margin: "24px 0", textWrap: "balance" as never}}>{text}</div>
    <div style={{color: C.muted, fontSize: 38}}>{title}</div>
  </AbsoluteFill>
);
