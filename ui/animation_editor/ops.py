"""Animation editor operations that need no wx: timing, playback preview, step and animation edits.

Units: an animation step holds its frame for ``duration_frames`` *ticks*; ``Animation.fps`` is ticks per
second. A hold below 1 is treated as 1 tick, exactly like the exporters do.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from contextlib import contextmanager
from typing import Iterator

from models import AFrame, Animation, EventType, Project, StepEvent, generate_id

# (label, playback_type). Labels say what the game does; "backward" repeats like the SGDK runtime.
PLAYBACK_MODES: List[Tuple[str, str]] = [
    ("Loop", "loop"),
    ("Play once", "forward"),
    ("Ping-pong", "ping_pong"),
    ("Loop backwards", "backward"),
]
REPEATING_MODES = ("loop", "ping_pong", "backward")
TICK_RATE_PRESETS = (10, 12, 15, 20, 24, 30, 50, 60)
DEFAULT_TICK_RATE = 10


# ---------------------------------------------------------------------------- timing
def hold(af: AFrame) -> int:
    return max(1, int(af.duration_frames))


def tick_rate(anim: Animation) -> int:
    return int(anim.fps) if int(anim.fps) > 0 else DEFAULT_TICK_RATE


def total_ticks(anim: Animation) -> int:
    return sum(hold(af) for af in anim.aframes)


def step_starts(anim: Animation) -> List[int]:
    starts: List[int] = []
    tick = 0
    for af in anim.aframes:
        starts.append(tick)
        tick += hold(af)
    return starts


def step_at_tick(anim: Animation, tick: int) -> int:
    """Index of the step shown at a tick (-1 without steps). Ticks past the end show the last step."""
    if not anim.aframes:
        return -1
    tick = max(0, int(tick))
    for index, start in enumerate(step_starts(anim)):
        if tick < start + hold(anim.aframes[index]):
            return index
    return len(anim.aframes) - 1


def seconds(anim: Animation, ticks: int) -> float:
    return float(ticks) / float(tick_rate(anim))


def describe_length(anim: Animation) -> str:
    steps = len(anim.aframes)
    ticks = total_ticks(anim)
    return f"{steps} step{'s' if steps != 1 else ''} · {ticks} tick{'s' if ticks != 1 else ''} · {seconds(anim, ticks):.2f} s"


def playback_label(playback_type: str) -> str:
    return next((label for label, key in PLAYBACK_MODES if key == playback_type), "Loop")


def loop_start(anim: Animation) -> int:
    """Step that later loop passes start at (0 = the whole animation loops)."""
    if anim.playback_type != "loop" or not anim.aframes:
        return 0
    return max(0, min(int(anim.loop_start or 0), len(anim.aframes) - 1))


def can_finish(anim: Animation) -> bool:
    """Whether playback ever ends (so a follow-up animation can start)."""
    return anim.playback_type == "forward" or int(anim.loop_count or 0) > 0


@contextmanager
def keep_loop_start(anim: Optional[Animation]) -> Iterator[None]:
    """Keep "loop from" on the same step while steps are inserted, moved or deleted."""
    anchor = anim.aframes[anim.loop_start] if anim and 0 < anim.loop_start < len(anim.aframes) else None
    old = anim.loop_start if anim else 0
    yield
    if not anim or not anim.loop_start:
        return
    if anchor is not None and any(af is anchor for af in anim.aframes):
        anim.loop_start = next(i for i, af in enumerate(anim.aframes) if af is anchor)
    else:
        anim.loop_start = max(0, min(old, len(anim.aframes) - 1))


# ---------------------------------------------------------------------------- playback preview
class Player:
    """Advances an animation tick by tick the way the SGDK runtime (modsprite.c) does.

    ``loop_count`` (> 0) stops repeating modes after that many cycles, like the data intends; the
    editor's Repeat toggle restarts a finished preview from the beginning.
    """

    def __init__(self, anim: Animation, repeat: bool = True):
        self.anim = anim
        self.repeat = repeat
        self.step = 0
        self.ticks_left = 1
        self.direction = 1
        self.cycles = 0
        self.finished = False

    def start(self, from_step: Optional[int] = None) -> None:
        count = len(self.anim.aframes)
        self.cycles = 0
        self.finished = False
        if count == 0:
            self.step = 0
            return
        if from_step is None:
            from_step = count - 1 if self.anim.playback_type == "backward" else 0
        self.direction = -1 if self.anim.playback_type == "backward" else 1
        self._enter(max(0, min(int(from_step), count - 1)))

    def _enter(self, step: int) -> None:
        self.step = step
        self.ticks_left = hold(self.anim.aframes[step])

    def position(self) -> int:
        """Tick on the strip that is showing now."""
        if not self.anim.aframes:
            return 0
        start = step_starts(self.anim)[self.step]
        return start + hold(self.anim.aframes[self.step]) - max(1, self.ticks_left)

    def _cycle_done(self) -> bool:
        """Count a finished cycle; True when the animation should stop."""
        self.cycles += 1
        limit = int(self.anim.loop_count or 0)
        return limit > 0 and self.cycles >= limit

    def advance(self) -> bool:
        """One tick. Returns False once playback has stopped."""
        count = len(self.anim.aframes)
        if count == 0 or self.finished:
            return False
        if self.ticks_left > 1:
            self.ticks_left -= 1
            return True
        mode = self.anim.playback_type
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


# ---------------------------------------------------------------------------- step edits
def new_step(frame_id: str, ticks: int = 1) -> AFrame:
    return AFrame(frame_id=frame_id, duration_frames=max(1, int(ticks)))


def _valid(anim: Animation, indices: Iterable[int]) -> List[int]:
    return sorted({i for i in indices if 0 <= i < len(anim.aframes)})


def insert_steps(anim: Animation, index: int, steps: Sequence[AFrame]) -> List[int]:
    index = max(0, min(int(index), len(anim.aframes)))
    for offset, step in enumerate(steps):
        anim.aframes.insert(index + offset, step)
    return list(range(index, index + len(steps)))


def delete_steps(anim: Animation, indices: Iterable[int]) -> int:
    doomed = _valid(anim, indices)
    for i in reversed(doomed):
        anim.aframes.pop(i)
    return len(doomed)


def move_steps(anim: Animation, indices: Iterable[int], insert_at: int) -> List[int]:
    """Move steps (kept in order) so they land before ``insert_at`` (an index in the current list)."""
    chosen = _valid(anim, indices)
    if not chosen:
        return []
    moving = [anim.aframes[i] for i in chosen]
    before = sum(1 for i in chosen if i < insert_at)
    for i in reversed(chosen):
        anim.aframes.pop(i)
    target = max(0, min(int(insert_at) - before, len(anim.aframes)))
    return insert_steps(anim, target, moving)


def copy_steps(anim: Animation, indices: Iterable[int]) -> List[Dict[str, Any]]:
    return [anim.aframes[i].to_dict() for i in _valid(anim, indices)]


def paste_steps(anim: Animation, index: int, data: Sequence[Dict[str, Any]]) -> List[int]:
    return insert_steps(anim, index, [AFrame.from_dict(dict(d)) for d in data])


def duplicate_steps(anim: Animation, indices: Iterable[int]) -> List[int]:
    chosen = _valid(anim, indices)
    if not chosen:
        return []
    return paste_steps(anim, chosen[-1] + 1, copy_steps(anim, chosen))


def set_hold(anim: Animation, indices: Iterable[int], ticks: int) -> None:
    for i in _valid(anim, indices):
        anim.aframes[i].duration_frames = max(1, int(ticks))


def change_hold(anim: Animation, indices: Iterable[int], delta: int) -> None:
    for i in _valid(anim, indices):
        anim.aframes[i].duration_frames = max(1, hold(anim.aframes[i]) + int(delta))


def toggle_flip(anim: Animation, indices: Iterable[int], axis: str) -> Optional[bool]:
    """Flip the steps' frames in place (about the step origin). All get the opposite of the first's state."""
    chosen = _valid(anim, indices)
    if not chosen:
        return None
    attr = "flip_x" if axis == "x" else "flip_y"
    value = not getattr(anim.aframes[chosen[0]], attr)
    for i in chosen:
        setattr(anim.aframes[i], attr, value)
    return value


def set_flip(anim: Animation, indices: Iterable[int], axis: str, value: bool) -> None:
    attr = "flip_x" if axis == "x" else "flip_y"
    for i in _valid(anim, indices):
        setattr(anim.aframes[i], attr, bool(value))


def rotate_steps(anim: Animation, indices: Iterable[int], degrees: int) -> None:
    for i in _valid(anim, indices):
        af = anim.aframes[i]
        af.rotation_degrees = float((int(round(af.rotation_degrees)) + int(degrees)) % 360)


def nudge(anim: Animation, indices: Iterable[int], dx: int, dy: int) -> None:
    for i in _valid(anim, indices):
        af = anim.aframes[i]
        af.offset = (int(af.offset[0]) + int(dx), int(af.offset[1]) + int(dy))


def reverse_steps(anim: Animation, indices: Iterable[int]) -> List[int]:
    """Reverse the order of the chosen steps in place (all steps when fewer than two are chosen)."""
    chosen = _valid(anim, indices)
    if len(chosen) < 2:
        chosen = list(range(len(anim.aframes)))
    steps = [anim.aframes[i] for i in chosen]
    for i, step in zip(chosen, reversed(steps)):
        anim.aframes[i] = step
    return chosen


def mirror_animation(anim: Animation, axis: str) -> None:
    """Mirror the whole animation: every step's image and its offset (the motion) flip together.

    Steps are drawn flip-then-rotate, so mirroring a step rotated by 90°/270° swaps which flip changes.
    """
    for af in anim.aframes:
        quarter_turn = int(round(af.rotation_degrees)) % 180 == 90
        if axis == "x":
            if quarter_turn:
                af.flip_y = not af.flip_y
            else:
                af.flip_x = not af.flip_x
            af.offset = (-int(af.offset[0]), int(af.offset[1]))
        else:
            if quarter_turn:
                af.flip_x = not af.flip_x
            else:
                af.flip_y = not af.flip_y
            af.offset = (int(af.offset[0]), -int(af.offset[1]))


def rotate_animation(anim: Animation, degrees: int) -> None:
    """Rotate the whole animation (images and motion) by a multiple of 90° clockwise (screen, y down)."""
    turns = (int(degrees) // 90) % 4
    if not turns:
        return
    for af in anim.aframes:
        af.rotation_degrees = float((int(round(af.rotation_degrees)) + 90 * turns) % 360)
        x, y = int(af.offset[0]), int(af.offset[1])
        for _ in range(turns):
            x, y = -y, x
        af.offset = (x, y)


# ---------------------------------------------------------------------------- animations
def unique_name(project: Project, base: str) -> str:
    used = {a.name for a in project.animations}
    candidate, suffix = base, 2
    while candidate in used:
        candidate = f"{base} {suffix}"
        suffix += 1
    return candidate


def new_animation(project: Project, after_id: Optional[str] = None, name: str = "New Animation") -> Animation:
    after = project.get_animation(after_id) if after_id else None
    anim = Animation(
        id=generate_id("anim"),
        name=unique_name(project, name),
        playback_type="loop",
        fps=tick_rate(after) if after else DEFAULT_TICK_RATE,
    )
    index = project.animations.index(after) + 1 if after in project.animations else len(project.animations)
    project.animations.insert(index, anim)
    return anim


def duplicate_animation(project: Project, anim: Animation) -> Animation:
    copy = anim.clone()
    copy.id = generate_id("anim")
    copy.name = unique_name(project, f"{anim.name} copy")
    project.animations.insert(project.animations.index(anim) + 1, copy)
    return copy


def move_animation(project: Project, anim_id: str, to_index: int) -> None:
    anim = project.get_animation(anim_id)
    if not anim:
        return
    project.animations.remove(anim)
    project.animations.insert(max(0, min(int(to_index), len(project.animations))), anim)


def scene_usage(project: Project, anim_id: str) -> int:
    """How many timeline objects show this animation (as their source or via a key's image swap)."""
    return sum(
        1
        for scene in project.timeline_scenes
        for obj in scene.objects
        if (obj.source_type == "animation" and obj.source_id == anim_id)
        or any(k.source_type == "animation" and k.source_id == anim_id for k in obj.keyframes)
    )


# ---------------------------------------------------------------------------- events
EVENT_COLOURS: List[Tuple[int, int, int]] = [
    (255, 110, 100), (110, 200, 255), (130, 220, 120), (255, 200, 80),
    (200, 140, 255), (255, 150, 210), (120, 230, 210), (220, 220, 120),
]


def event_type_by_name(project: Project, name: str) -> Optional[EventType]:
    key = name.strip().lower()
    return next((t for t in project.event_types if t.name.strip().lower() == key), None)


def ensure_event_type(project: Project, name: str) -> Optional[EventType]:
    """The event type with this name; typing a new name creates it (with the next marker colour)."""
    name = name.strip()
    if not name:
        return None
    found = event_type_by_name(project, name)
    if found:
        return found
    colour = EVENT_COLOURS[len(project.event_types) % len(EVENT_COLOURS)]
    created = EventType(id=generate_id("evt"), name=name, color=colour)
    project.event_types.append(created)
    return created


def add_event(anim: Animation, indices: Iterable[int], type_id: str, value: int = 0) -> int:
    """Add an event to the steps that do not have it yet. Returns how many steps changed."""
    changed = 0
    for i in _valid(anim, indices):
        events = anim.aframes[i].events
        if not any(e.type_id == type_id for e in events):
            events.append(StepEvent(type_id=type_id, value=int(value)))
            changed += 1
    return changed


def remove_event(anim: Animation, indices: Iterable[int], type_id: str) -> int:
    changed = 0
    for i in _valid(anim, indices):
        af = anim.aframes[i]
        kept = [e for e in af.events if e.type_id != type_id]
        changed += len(af.events) - len(kept)
        af.events = kept
    return changed


def set_event_value(anim: Animation, indices: Iterable[int], type_id: str, value: int) -> None:
    for i in _valid(anim, indices):
        for e in anim.aframes[i].events:
            if e.type_id == type_id:
                e.value = int(value)


def events_on(anim: Animation, indices: Iterable[int]) -> List[Tuple[str, int, int]]:
    """(type id, value of the first step that has it, how many of the steps have it), in first-seen order."""
    seen: Dict[str, List[int]] = {}
    for i in _valid(anim, indices):
        for e in anim.aframes[i].events:
            if e.type_id not in seen:
                seen[e.type_id] = [int(e.value), 0]
            seen[e.type_id][1] += 1
    return [(type_id, value, count) for type_id, (value, count) in seen.items()]


def event_usage(project: Project, type_id: str) -> int:
    return sum(1 for anim in project.animations for af in anim.aframes for e in af.events if e.type_id == type_id)


def delete_event_type(project: Project, type_id: str) -> int:
    """Remove an event type and every use of it. Returns how many step events were removed."""
    removed = 0
    for anim in project.animations:
        removed += remove_event(anim, range(len(anim.aframes)), type_id)
    project.event_types = [t for t in project.event_types if t.id != type_id]
    return removed


def follow_up_references(project: Project, anim_id: str) -> List[Animation]:
    """Animations that continue with this one."""
    return [a for a in project.animations if a.next_animation_id == anim_id]

