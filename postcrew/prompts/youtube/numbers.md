

WORKED NUMBERS ARE RUN, NOT TYPED: WHEN THE VIDEO WORKS OUT A CALCULATION ON ITS EXAMPLE, THE APP RUNS IT AND DRAWS EVERY STEP.
Any calculation the voice works out on the example (multiplying, a power, wrapping around a clock / mod, a remainder, a sum, a hash, a
checksum) is a "run" scene, never a diagram arrow, a trace step or a stat with the answer written by hand ("2^5 = 32 = 6" on an arrow,
"216 mod 13 = 8" in one jump). A viewer must never have to pause to work out how a number came from the one before: every operation
is its own step, drawn and said.

A "run" scene:
- "code": a few lines of runnable Python that do the calculation the way you explain it, one operation per line, short and clear. Keep
  the results in a list that grows (the row of cells on screen), e.g. "powers = [1]" then "powers.append(x)". Mark exactly ONE line with
  the comment "# step": the line whose end is one step worth showing. Every time it finishes, the app records a step: the list, the
  variables and the calculation that changed them, from the real values ("x = 16 * 2 = 32", "x = 32 mod 13 = 6").
  To show a wrap, do it as its own line (x = x % p) or by subtracting the clock size (while x >= p: x = x - p), so the wrap is a step.
- "run": {"call": the call on the example, exactly, e.g. "public_number(2, 5, 13)"; "kind": "array"; "array": the growing list drawn as
  cells; "pointers": []; "window": []; "show": up to 4 variables shown as big tiles (the running value, the secret, the clock size);
  "steps": which recorded steps this scene shows, "1-5"}.
- "narration": EXACTLY ONE SENTENCE PER STEP, in order, each at least 5 words, saying the operation and the result ("Two times sixteen is
  thirty two, which is past thirteen."; "Thirty two wraps around the clock twice, leaving six."). Never two steps in one sentence.
- At most 12 steps a scene; continue in the next run scene with the same code and call ("steps": "6-9"). Use small numbers so every step fits.
- You do not know the steps yet when you write the first draft: write your best guess. The app runs your code and, if the narration does
  not match, sends you the REAL list of steps: then narrate exactly those.
The idea, the story and the pictures around it stay diagrams and flows; only the arithmetic is run. Show the code itself only if the
video is about code: a run scene draws the working, not the code.
