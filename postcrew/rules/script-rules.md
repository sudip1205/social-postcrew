# Script rules

This file is the ONLY source of rules for planning and writing videos. The agents read it on every run; nothing in their code adds rules
of its own. Change a rule here and the next plan or script follows it. Each rule says when and why the owner asked for it.

The file has three parts. Plans get "Plan rules" and "YouTube tags". Scripts get "Script rules" and "YouTube tags".

<!-- part: plan -->
# Plan rules

## P1. No code unless asked (owner, 2026-11-22)
The owner wants visual explanatory videos. Unless the owner's topic or request names a programming language or asks for code, a plan never
mentions or uses a programming language (Python, Java, ...), code, a simulation, a demo, an implementation or running anything. The title,
angle, context, example and takeaway explain what the thing is and how it works with pictures, step by step. Ignore "in Python" in trending
videos and in already-published titles.

## P2. Technical depth (owner, 2026-11-26: "I want the script to cover more technical details")
Every plan's angle, example and takeaway name the real mechanism, the real terms and the numbers the video will teach (the steps inside,
the parts by name, one limit or trade-off), not only the big idea. A takeaway like "understands why X matters" is too shallow; write what
the viewer will be able to explain step by step.

## P3. What a Short is
A vertical explainer of 50 to 90 seconds about ONE thing: what it is and how it works. Hook with a real problem in one breath, name and
define the term with its picture, show the mechanism, the common mistake, then a specific question for the comments. Never interview
advice.

## P4. What a long video is
A 16:9 visual class by a calm, caring professor for students: what ONE system or idea is and how it works, from the problem it solves to
every part of it. Begin with the student's problem, build the picture step by step (a growing diagram, one request or value moving
through it), explain what, why and how for every part, show what breaks and the fix, check in with the class, finish with a short recap.
No code, except an algorithm problem. Never interview advice.
<!-- end -->

<!-- part: script -->
# Script rules

## S1. Opening and retention (owner, 2026-11-17: "My video retention is bad")
1. Beat 1 is a CATCH LINE of at most 14 words: a moment the viewer has seen or felt themselves (or a surprising number, or a mistake they
   make) plus a question or surprise they now want answered. It must make sense to someone who has never heard the topic's name. Never
   start with the topic's name, a definition, "In this video", "Today" or "Have you ever wondered".
   Good: "You hit Back and the last page comes right back. How does your browser remember?"
   Bad: "Your browser's Back button just worked. A plain linked list could not do that." (a claim nobody asked about)
2. Beat 2 connects: talk to the viewer ("you", "your"), why it matters to them and where they will meet it, and open a loop (what they
   will know by the end) that stays open until near the end.
3. Then build up: the problem shown happening, the obvious first attempt and why it fails, then the idea, one step per beat. Re-hook
   every 15-20 s with a turn ("But here's the problem...", "Now watch what happens when...", "This is the part most people get wrong").
   Never three plain explaining beats in a row.
4. Pay off: answer the hook's question explicitly, calling back to its words. End with the takeaway and an easy comment question (a
   choice of two).
5. Write 3 different catch lines of different kinds and put them in script.json as "hook_options" (the chosen one first). Read beat 1 as
   a stranger scrolling past: would you stop, and would you understand it? If not, rewrite it.

## S2. Technical depth (owner, 2026-11-26: "Script is not covering technical details of the topic")
The viewer is a developer or CS student: teach the real mechanism, not only the idea. Every script must
1. name the real parts and terms the topic uses (e.g. SYN, ACK, sequence number, TTL, kube-proxy, iptables rule, ClusterIP, B-tree page,
   quorum) and define each one in a few words the first time it is said, with its picture on screen;
2. walk through what actually happens inside, step by step in the right order, each step a beat;
3. give concrete numbers where the topic has them (sizes, ports, timeouts, latencies, counts, Big-O, defaults) and keep them correct;
4. show at least one real limit, cost, failure case or trade-off, and when to pick the alternative.
An analogy may open a beat but never replaces the mechanism. Spend the words on technical content: no filler beats (no "stay for the
catch", no "every app you trust works this way", no recap of what was just said). Facts must be accurate; when unsure, leave a detail out
rather than guess. Technical does not mean code (S3).

## S3. No code unless asked (owner, 2026-11-22)
Unless the owner's plan or instructions explicitly ask for code or name a language, the video shows NO code, names no programming
language, and runs no simulation or program: explain what the thing is and how it works with pictures, tables and a little math. Ignore
"Python" in old titles and examples. An algorithm problem the owner asked for may have one trace and one short code scene.

## S4. Length and shape (owner, 2026-11-15)
- A Short runs 50 to 90 seconds; aim for 65-75 s: 12-15 beats, 130-155 words (the code gives the exact word budget for the format).
- One or two sentences per beat, 8-18 words.
- ONE idea explained properly: what it is, why it matters, how it works, a worked example.
- One concrete running example carried through the whole video.
- Do not write the like / comment / share / subscribe outro: the channel's recorded outro is added after the last beat.

## S5. Narration punctuation (owner, 2026-11-21)
Never put a colon (:) in anything the voice reads (beats' "say", scene text): the voice runs straight through it. Use a full stop or a
semicolon: "Worst case: 100 drops" -> "Worst case. 100 drops."; "Strategy one: walk up" -> "Strategy one. Walk up." Clock times and ratios
are written in words ("ten thirty", "two to one").

## S6. Pictures (every animated look)
- Draw the real thing for the topic (servers, packets, queues, people, phones), big: the hero objects fill 60-75% of the frame width. Not
  generic props. Most beats show an object; no beat is an empty frame.
- Colours come from the video's theme (script.json "variant", themes/<variant>.js): the background with THEME.backdrop when the theme has
  one, otherwise the theme's light paper; every surface from THEME and objects.js. Never your own dark hex colours (owner, 2026-11-25:
  "trying to create in pastel look but it is generating in black").
- Copy the owner's own Shorts: episodes 2026-11-22-active-active-explained-two-live-servers-zero-id,
  2026-11-18-build-a-music-playlist-singly-doubly-and-circula and 2026-11-24-kubernetes-explained-follow-one-request-through (read their
  explainer.js), and the published Shorts in styles/iso-pastel/examples/channel/.

## S7. Labels (owner, 2026-11-22: texts were blocking each other while big parts of the screen stayed empty)
EVERY object that has a name (server, load balancer, database, queue, cache, person, phone...) has it printed ON itself:
nameOn(ctx, P, [x, y, z, w, d, h], 'Server 1', {face: 'side'|'front'|'top'|'round'}) right after drawing it, on a face the viewer sees,
the object big enough for 26 px text; an inset plate in the face's perspective, no arrow, it never floats. Only states and values (down,
100% load, a counter) float, with label(ctx, P(x, y, z), text, {k, dot, bg, col, sub, fs}), the point ON the object: the shell puts the
label in free space and draws an arrow to the object, and the label keeps that place for its whole life; so never draw a later card where
a label sits. Never place two chips, pills or cards on the same spot, never a chip on the header or the captions, never a card over a
chip; use the empty floor, sky and margins. The storyboard check fails when texts overlap.

## S8. The camera (owner, 2026-11-26: "my previous isometric videos ... have camera movement in one direction and smooth transition")
One world, framed wide so every object of the section stays fully on screen; the camera moves slowly in ONE direction through the whole
video (a steady drift or push along the world), and each section eases smoothly into the next. One fixed angle. Never cut, never jump
back and forth between zones, never zoom so close that objects leave the frame.

## S9. Check before done
Run the storyboard check, fix every problem it lists, then look at the storyboard and fix every panel that is empty, cramped, unreadable,
off-screen or not clearly about its line. Repeat until both are clean.
<!-- end -->

<!-- part: tags -->
# YouTube tags (owner, 2026-11-21: tags decide who the video reaches)
Write 15-25 tags, most important first, all about THIS video's topic:
1. the exact topic as people search it ("egg drop problem", "how wifi works");
2. its other names, abbreviations and spellings ("2 eggs 100 floors", "egg dropping puzzle");
3. long-tail questions and phrases viewers type ("egg drop puzzle explained", "minimum drops 2 eggs");
4. the wider field ("dynamic programming", "algorithms", "computer science");
5. the audience's goal ("coding interview question", "learn algorithms") and the format ("animated explanation", "shorts").
Use the tags the top videos use where they fit. Lower case, no "#", no channel name, no tags about other topics, no single generic words
alone ("video", "tech", "learn"), each at most 30 characters, all together under 480 characters.
<!-- end -->
