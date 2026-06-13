"""Avoidle — the survival word game where guessing right means losing.

Guess words round after round WITHOUT ever guessing the hidden word.
Every guess must respect all clues revealed so far, which slowly forces
you toward the answer. Survive to win.
"""

# four components, bumped right-to-left: the LAST digit increments with
# every iteration; earlier digits move only for genuinely larger steps
__version__ = "1.5.2.4"
__author__ = "Eugen Dimant"
__homepage__ = "https://eugendimant.github.io"
