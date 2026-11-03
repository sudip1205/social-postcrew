import React from "react";
import {useTheme} from "./theme";

export const KEYWORDS = /\b(def|return|if|else|elif|for|while|in|not|and|or|import|from|class|const|let|var|function|new|true|false|True|False|None|null|async|await|break|continue|try|except|catch|finally|raise|throw|with|as|yield|switch|case|default|select|where|insert|into|values|create|table|upstream|server|location|proxy_pass|listen)\b/;
const TOKEN = new RegExp(`(#.*$|//.*$|--.*$)|("[^"]*"|'[^']*')|\\b(\\d+(?:\\.\\d+)?)\\b|${KEYWORDS.source}`, "g");
export const EXT: Record<string, string> = {python: "py", javascript: "js", typescript: "ts", java: "java", go: "go", sql: "sql", bash: "sh", shell: "sh", nginx: "conf", yaml: "yml", json: "json", rust: "rs", c: "c", cpp: "cpp"};
/** One line of code with its colours: comments muted, strings in the positive colour, numbers highlighted, keywords in the accent. */
export const Colored: React.FC<{line: string}> = ({line}) => {
  const th = useTheme(), out: React.ReactNode[] = [];
  let last = 0, m: RegExpExecArray | null;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(line))) {
    if (m.index > last) out.push(line.slice(last, m.index));
    const col = m[1] ? th.muted : m[2] ? th.positive : m[3] ? th.highlight : th.accent;
    out.push(<span key={m.index} style={{color: col, fontWeight: m[1] || m[2] || m[3] ? 400 : 700, fontStyle: m[1] ? "italic" : "normal"}}>{m[0]}</span>);
    last = m.index + m[0].length;
    if (m[0].length === 0) TOKEN.lastIndex++;
  }
  if (last < line.length) out.push(line.slice(last));
  return <>{out}</>;
};
