"""Animation playback exactly like the Mega Drive runtime (``ms_anim_player_tick`` in modsprite.c), wx-free.

One set of rules wherever an animation plays: the Animations tab steps a ``Player`` tick by tick; Timeline objects,
and through them the exporters, ask what shows some time after an animation started (``animation_at``), which
follows the same rules without stepping through every tick. ``tests/test_runtime_player.py`` compares the Player
with the C runtime, ``tests/test_playback.py`` the shortcut with the Player.

Units: a step holds its frame for ``duration_frames`` ticks (below 1 counts as 1); ``Animation.fps`` is ticks per
second. The runtime itself counts video frames: the SGDK export turns each hold into whole frames at 60 a second
(``console_frames``), which a ``Player`` with ``hold_of=console_hold(anim)`` steps through like the game.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:  # models imports this module
    from models import AFrame, Animation

DEFAULT_TICK_RATE = 10
VIDEO_RATE = 60  # video frames a second the export converts holds to (a 50 Hz console shows them more slowly)
PLAYBACKS = ("forward", "backward", "loop", "ping_pong")  # Animation.playback_type

# Timeline object modes (TimelineObject.playback_mode): play the animation as animated, or override how it plays.
AS_ANIMATED = "as_animated"
OBJECT_MODES = (AS_ANIMATED, "loop", "once", "ping_pong", "backward")


def hold(af: "AFrame") -> int:
    return max(1, int(af.duration_frames))


def tick_rate(anim: "Animation") -> int:
    return int(anim.fps) if int(anim.fps) > 0 else DEFAULT_TICK_RATE


def console_frames(anim: "Animation", af: "AFrame") -> int:
    """Video frames a step shows in the game: its hold at the animation's tick rate, rounded to whole frames (the SGDK
    export's conversion). Tick rates that divide 60 convert exactly; others make some steps a little longer or
    shorter."""
    return max(1, int(round(hold(af) * VIDEO_RATE / float(tick_rate(anim)))))


def console_hold(anim: "Animation") -> Callable[["AFrame"], int]:
    """``Player(anim, hold_of=console_hold(anim))`` advances one video frame per call, as the runtime does."""
    return lambda af: console_frames(anim, af)


def converts_exactly(anim: "Animation") -> bool:
    """Whether every hold is a whole number of video frames (the game shows the timing the editor counts)."""
    rate = tick_rate(anim)
    return all(abs(hold(af) * VIDEO_RATE / float(rate) - console_frames(anim, af)) < 1e-9 for af in anim.aframes)


def playback_of(anim: "Animation") -> str:
    """The animation's playback type as the runtime reads it ("once" is the exporter's other name for forward)."""
    kind = str(anim.playback_type or "loop").strip().lower()
    return "forward" if kind == "once" else kind if kind in PLAYBACKS else "loop"


def loop_start(anim: "Animation") -> int:
    """Step that later loop passes start at (0 = the whole animation loops)."""
    if playback_of(anim) != "loop" or not anim.aframes:
        return 0
    return max(0, min(int(anim.loop_start or 0), len(anim.aframes) - 1))


def can_finish(anim: "Animation") -> bool:
    """Whether playback ever ends (so a follow-up animation can start)."""
    return playback_of(anim) == "forward" or int(anim.loop_count or 0) > 0


# ---------------------------------------------------------------------------- tick by tick
class Player:
    """Advances an animation tick by tick the way the SGDK runtime (modsprite.c) does.

    ``loop_count`` (> 0) stops repeating modes after that many cycles, like the data intends; the
    editor's Repeat toggle restarts a finished preview from the beginning.
    """

    def __init__(self, anim: "Animation", repeat: bool = True, hold_of: Optional[Callable[["AFrame"], int]] = None):
        self.anim = anim
        self.repeat = repeat
        self.hold_of = hold_of or hold  # what one advance() counts: ticks, or the game's video frames (console_hold)
        self.step = 0
        self.ticks_left = 1
        self.direction = 1
        self.cycles = 0
        self.finished = False
        self.step_started = False  # True on the tick a step starts: its events fire (like the runtime's)

    def start(self, from_step: Optional[int] = None) -> None:
        count = len(self.anim.aframes)
        self.cycles = 0
        self.finished = False
        if count == 0:
            self.step = 0
            return
        backward = playback_of(self.anim) == "backward"
        if from_step is None:
            from_step = count - 1 if backward else 0
        self.direction = -1 if backward else 1
        self._enter(max(0, min(int(from_step), count - 1)))

    def _enter(self, step: int) -> None:
        self.step = step
        self.ticks_left = self.hold_of(self.anim.aframes[step])
        self.step_started = True

    def position(self) -> int:
        """Tick on the strip that is showing now (with a console ``hold_of``: the tick the game's frame falls in)."""
        if not self.anim.aframes:
            return 0
        step = min(self.step, len(self.anim.aframes) - 1)  # steps may have been deleted while it plays
        af = self.anim.aframes[step]
        start = sum(hold(a) for a in self.anim.aframes[:step])
        length = self.hold_of(af)
        shown = max(0, min(length - 1, length - max(1, self.ticks_left)))
        return start + shown * hold(af) // length

    def _cycle_done(self) -> bool:
        """Count a finished cycle; True when the animation should stop."""
        self.cycles += 1
        limit = int(self.anim.loop_count or 0)
        return limit > 0 and self.cycles >= limit

    def advance(self) -> bool:
        """One tick. Returns False once playback has stopped."""
        count = len(self.anim.aframes)
        self.step_started = False
        if count == 0 or self.finished:
            return False
        if self.ticks_left > 1:
            self.ticks_left -= 1
            return True
        mode = playback_of(self.anim)
        if mode == "forward":
            if self.step + 1 >= count:
                return self._finish()
            self._enter(self.step + 1)
        elif mode == "backward":
            if self.step == 0:
                if self._cycle_done():
                    return self._finish()
                self._enter(count - 1)
            else:
                self._enter(self.step - 1)
        elif mode == "ping_pong":
            if count <= 1:
                self._enter(0)
            elif self.direction >= 0:
                if self.step + 1 >= count:
                    self.direction = -1
                    self._enter(self.step - 1)
                else:
                    self._enter(self.step + 1)
            else:
                if self.step == 0:
                    if self._cycle_done():
                        return self._finish()
                    self.direction = 1
                    self._enter(1)
                else:
                    self._enter(self.step - 1)
        else:  # loop: later passes start at loop_start (the intro before it plays once)
            if self.step + 1 >= count:
                if self._cycle_done():
                    return self._finish()
                self._enter(loop_start(self.anim))
            else:
                self._enter(self.step + 1)
        return True

    def _finish(self) -> bool:
        if self.repeat:
            self.start()
            return True
        self.finished = True
        return False


# ---------------------------------------------------------------------------- at a moment
@dataclass(frozen=True)
class Rules:
    """How an animation plays: its own settings, or a Timeline object's override of them."""

    playback: str  # one of PLAYBACKS
    loop_count: int = 0  # passes before a repeating playback ends (0: never)
    loop_start: int = 0  # loop: later passes start at this step
    follow_up: bool = True  # an animation that ends continues with its follow-up


def own_rules(anim: "Animation") -> Rules:
    return Rules(playback_of(anim), max(0, int(anim.loop_count or 0)), loop_start(anim), True)


def object_rules(anim: "Animation", mode: str) -> Rules:
    """A Timeline object's mode: "as_animated" plays the animation's own settings; the others override them and
    play the one animation forever (Play once holds its last step), as scenes did before format 5."""
    if mode == "once":
        return Rules("forward", follow_up=False)
    if mode in ("ping_pong", "backward"):
        return Rules(mode, follow_up=False)
    if mode == "loop":  # later passes start at "loop from", whatever the animation's own playback
        start = max(0, min(int(anim.loop_start or 0), len(anim.aframes) - 1)) if anim.aframes else 0
        return Rules("loop", loop_start=start, follow_up=False)
    return own_rules(anim)


def _covering(holds: Sequence[int], tick: int) -> int:
    """Index of the hold that covers ``tick``, counted from the first hold's start."""
    for index, length in enumerate(holds):
        if tick < length:
            return index
        tick -= length
    return len(holds) - 1


def step_after(anim: "Animation", ticks: int, rules: Rules) -> Tuple[int, Optional[int]]:
    """(step that shows ``ticks`` ticks after the animation started, tick at which it ended or None while it plays).

    Exactly what ``ticks`` calls of ``Player.advance`` leave behind, without making them; an animation without steps
    gives (0, None).
    """
    holds = [hold(af) for af in anim.aframes]
    count = len(holds)
    if count == 0:
        return 0, None
    ticks = max(0, int(ticks))
    total = sum(holds)
    limit = max(0, int(rules.loop_count))
    if rules.playback == "forward":
        return (count - 1, total) if ticks >= total else (_covering(holds, ticks), None)
    if rules.playback == "backward":
        end = limit * total if limit else None
        if end is not None and ticks >= end:
            return 0, end
        return count - 1 - _covering(holds[::-1], ticks % total), None
    if rules.playback == "ping_pong":
        if count == 1:
            return 0, None  # nothing to turn at: the runtime never counts a pass
        back = list(range(count - 2, -1, -1))
        first, later = list(range(count)) + back, list(range(1, count)) + back
        first_ticks = sum(holds[i] for i in first)
        later_ticks = sum(holds[i] for i in later)
        end = first_ticks + (limit - 1) * later_ticks if limit else None
        if end is not None and ticks >= end:
            return 0, end
        steps, tick = (first, ticks) if ticks < first_ticks else (later, (ticks - first_ticks) % later_ticks)
        return steps[_covering([holds[i] for i in steps], tick)], None
    # loop: the first pass plays every step, later passes start at loop_start
    start = max(0, min(int(rules.loop_start), count - 1))
    cycle = total - sum(holds[:start])
    end = total + (limit - 1) * cycle if limit else None
    if end is not None and ticks >= end:
        return count - 1, end
    if ticks < total:
        return _covering(holds, ticks), None
    return start + _covering(holds[start:], (ticks - total) % cycle), None


def ticks_in(seconds: float, rate: int) -> int:
    """Whole ticks that have passed after ``seconds`` at ``rate`` ticks per second."""
    return int(math.floor(round(float(seconds) * float(rate), 6)))  # 0.3 s at 10 ticks/s is tick 3, not 2.999…


def animation_at(
    anim: "Animation",
    seconds: float,
    rules: Rules,
    find: Callable[[str], Optional["Animation"]],
) -> Tuple["Animation", int]:
    """The animation and step that show ``seconds`` after ``anim`` started playing by ``rules``. An animation that
    ends continues with its follow-up (looked up with ``find``) when the rules allow it, at the follow-up's own tick
    rate; before the start (negative time) the first step shows."""
    remaining = max(0.0, float(seconds))
    started: Dict[str, float] = {}  # animation id -> time left when the chain last started it
    while True:
        rate = tick_rate(anim)
        step, ended = step_after(anim, ticks_in(remaining, rate), rules)
        if ended is None or not rules.follow_up or not anim.next_animation_id:
            return anim, step
        follow = find(anim.next_animation_id)
        if follow is None or not follow.aframes:
            return anim, step
        remaining -= ended / rate
        if follow.id in started:
            # The chain came back round: every round takes as long as the last one, so skip the whole rounds.
            period = started[follow.id] - remaining
            if period > 0:
                remaining -= math.floor(round(remaining / period, 9)) * period
            started.clear()
        started[follow.id] = remaining
        anim, rules = follow, own_rules(follow)


def steps_shown(anim: "Animation", ticks: int, rules: Optional[Rules] = None) -> List[int]:
    """The step on each tick from 0 to ``ticks`` - 1 (for tests and previews of one animation)."""
    rules = rules or own_rules(anim)
    return [step_after(anim, tick, rules)[0] for tick in range(max(0, int(ticks)))]
