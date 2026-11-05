

THIS IS AN ALGORITHM VIDEO: THE APP RUNS THE CODE AND DRAWS WHAT REALLY HAPPENED.
Every walk-through of the data (the example worked by hand, the brute force traced, the better way traced, the mistake failing) is a "run"
scene. Do NOT write "trace", "grid" or "codeviz" steps by hand in this video: the app refuses them. You write the code, the app runs it.

A "run" scene:
- "code": a complete, runnable Python function for ONE approach (brute force, the better way, the buggy version for the mistake), short and
  clear. Mark exactly ONE line with the comment "# step": the line whose end is one step worth showing (the line that updates the answer or
  the counter, inside the loop). Every time that line finishes, the app records a step: the array, the pointers, the variables and the
  calculation that changed them, worked out from the real values ("current = max(4, -2 + 4) = 4").
- "run": {"call": the call on the example, exactly, e.g. "max_subarray([-2, 1, -3, 4, -1])"; "kind": "array" (a list or string drawn as
  cells) or "grid" (a list of rows); "array": the variable drawn as cells; "pointers": integer variables drawn as arrows under their cell;
  "window": two integer variables whose cells are lit (first, last) or []; "show": up to 4 variables shown as big tiles (the counter, the
  running sum, the best so far); "steps": which recorded steps this scene shows, "1-5"}.
- "narration": EXACTLY ONE SENTENCE PER STEP, in order, each at least 5 words, saying what is looked at, the calculation and the result
  ("Day four: the larger of four alone, or minus two plus four, is four."). Never two steps in one sentence. Never a step without its sentence.
- A scene shows at most 12 steps; continue in the next run scene with the same code and call ("steps": "6-9"). Use a SMALL example so every
  step can be shown (five to eight values): the viewer must see every step, slowly.
- You do not know the steps yet when you write the first draft: write your best guess. The app runs your code and, if the narration does not
  match, sends you the REAL list of steps (each with its values and calculation): then narrate exactly those.

Also show the code itself in "code" scenes (one file per approach, named after it: brute.py, kadane.py), and the time you give each approach
is the loop nesting of its code (a loop in a loop is n squared). Every approach you name gets its code and its run.

ORDER: the problem on its example, then the simplest way run step by step and why it is slow, then the idea that fixes it, then the better
way run step by step, then its code and complexity, then the mistake run and failing, then the recap. Name the algorithm when you reach it,
not before.
