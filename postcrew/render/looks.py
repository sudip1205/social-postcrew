"""The look of a video: the colours every scene is drawn with. This is the one place to define it.

Both engines (Remotion and HyperFrames) get these values in the props file, so the opening card, the diagrams and the thumbnail
always match. `video.look` in Settings chooses one: "auto" (the default) draws a vertical video on the white page and a wide one on
the black page; "paper" or "ink" force one. The rules the scenes follow (type, spacing, motion) are in postcrew/remotion/STYLE.md.

  paper (white page)   headings and text #424242
      accent #279CF5 blue    structure and what is active: rules, arrows, the active box, pointers, numbers, code keywords
      highlight #FA7900 orange   the one key word of a headline, and the last word of the closing card
      positive #068200 green    what was found or went right
  ink (black page)     headings and text #C7C7C7
      accent #24C1FF cyan    structure and what is active (same job as the blue on white)
      highlight #FA7900 orange   the key word, the last word of the closing card, and what was found (there is no green on black)

A colour that is not in these lists does not belong in a video.
"""

LOOKS = {
    "paper": {
        "bg": "#F5F2EB", "surface": "#FBFAF6", "text": "#424242", "muted": "#6F6B62", "rule": "#D8D2C4",
        "accent": "#279CF5", "accentSoft": "rgba(39, 156, 245, 0.12)", "highlight": "#FA7900", "positive": "#068200",
    },
    "ink": {
        "bg": "#0D0D0D", "surface": "#161615", "text": "#C7C7C7", "muted": "#8C8C8C", "rule": "#2B2A27",
        "accent": "#24C1FF", "accentSoft": "rgba(36, 193, 255, 0.16)", "highlight": "#FA7900", "positive": "#FA7900",
    },
}
CHOICES = ("auto",) + tuple(LOOKS)
DEFAULT = "auto"


def resolve(name, fmt="short"):
    """The look to use: a vertical video (short) is paper, a wide one (long), ink, unless a look is chosen."""
    if name in LOOKS:
        return name
    return "paper" if fmt == "short" else "ink"


def theme(name=None, fmt="short"):
    """The colours of a look (chosen by the format when the name is auto or unknown), with its name."""
    name = resolve(name, fmt)
    return dict(LOOKS[name], name=name)
