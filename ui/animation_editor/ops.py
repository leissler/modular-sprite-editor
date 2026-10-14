"""Animation editor operations that need no wx: timing, playback preview, step and animation edits.

Units: an animation step holds its frame for ``duration_frames`` *ticks*; ``Animation.fps`` is ticks per
second. A hold below 1 is treated as 1 tick, exactly like the exporters do.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from contextlib import contextmanager
from typing import Iterator

import playback
from models import AFrame, Animation, EventType, Project, StepEvent, generate_id
from playback import DEFAULT_TICK_RATE, hold, tick_rate

# The Animations tab plays and describes animations exactly like the runtime (playback.py).
Player = playback.Player
can_finish = playback.can_finish
loop_start = playback.loop_start

# (label, playback_type). Labels say what the game does; "backward" repeats like the SGDK runtime.
PLAYBACK_MODES: List[Tuple[str, str]] = [
    ("Loop", "loop"),
    ("Play once", "forward"),
    ("Ping-pong", "ping_pong"),
    ("Loop backwards", "backward"),
]
REPEATING_MODES = ("loop", "ping_pong", "backward")

_new_tick_rate = DEFAULT_TICK_RATE  # animations made from scratch (Preferences ▸ New animations)


def set_new_tick_rate(rate: int) -> None:
    global _new_tick_rate
    _new_tick_rate = max(1, min(60, int(rate)))


def new_tick_rate() -> int:
    return _new_tick_rate


# ---------------------------------------------------------------------------- timing
# hold, tick_rate, loop_start, can_finish and the Player live in playback.py, shared with Timeline objects.
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


# Hold ▸ Spread: hold patterns for several steps, in units of the shortest hold among them.
SPREADS: List[Tuple[str, str]] = [
    ("1-1-2-2", "pairs"),
    ("1-2", "one_two"),
    ("2-1", "two_one"),
    ("Slow start", "slow_start"),
    ("Slow end", "slow_end"),
    ("Slow start and end", "slow_both"),
]
_PATTERNS = {"pairs": (1, 1, 2, 2), "one_two": (1, 2), "two_one": (2, 1)}


def spread_holds(kind: str, count: int, unit: int = 1) -> List[int]:
    """Holds for ``count`` steps in a row: a repeating pattern, or holds that shrink from 3 units to 1 (slow start),
    grow (slow end) or both, the way a motion leaves or reaches a pose."""
    unit = max(1, int(unit))
    if kind in _PATTERNS:
        pattern = _PATTERNS[kind]
        return [unit * pattern[i % len(pattern)] for i in range(count)]
    holds = []
    for i in range(count):
        x = i / (count - 1) if count > 1 else 0.0
        far = {"slow_start": 1.0 - x, "slow_end": x}.get(kind, abs(2.0 * x - 1.0))  # 1 where it is slowest
        holds.append(unit * (1 + int(2.0 * far * far + 0.5)))
    return holds


def spread(anim: Animation, indices: Iterable[int], kind: str) -> List[int]:
    """Give the steps the holds of a spread (in step order); returns the steps changed."""
    steps = sorted(set(_valid(anim, indices)))
    if not steps:
        return []
    unit = min(hold(anim.aframes[i]) for i in steps)
    for i, ticks in zip(steps, spread_holds(kind, len(steps), unit)):
        anim.aframes[i].duration_frames = ticks
    return steps


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
        fps=tick_rate(after) if after else _new_tick_rate,
    )
    index = project.animations.index(after) + 1 if after in project.animations else len(project.animations)
    project.animations.insert(index, anim)
    return anim


def shared_name(names: Sequence[str]) -> str:
    """What the names share, without a trailing number or separator: run_01, run_02 → run ("" if nothing)."""
    names = [name.strip() for name in names if name and name.strip()]
    if not names:
        return ""
    prefix = names[0]
    for name in names[1:]:
        while not name.startswith(prefix):
            prefix = prefix[:-1]
    return prefix.rstrip("0123456789").rstrip(" _-.#(").strip()


def animation_from_frames(project: Project, frame_ids: Sequence[str], name: str = "",
                          after_id: Optional[str] = None) -> Animation:
    """A new animation that shows these frames in this order, one tick each, named after what their names share."""
    frames = [frame for frame in (project.get_frame(fid) for fid in frame_ids) if frame is not None]
    anim = new_animation(project, after_id, name or shared_name([f.name for f in frames]) or "New Animation")
    anim.aframes = [new_step(frame.id) for frame in frames]
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


def change_tick_rate(anim: Animation, rate: int, keep_timing: bool) -> bool:
    """Set the tick rate. With ``keep_timing`` every hold is scaled so its step lasts as long as before, rounded to
    whole ticks; False when rounding changed a step's length."""
    old, rate = tick_rate(anim), max(1, int(rate))
    exact = True
    if keep_timing and rate != old:
        for af in anim.aframes:
            scaled = hold(af) * rate / float(old)
            ticks = max(1, int(scaled + 0.5))
            exact = exact and abs(ticks - scaled) < 1e-9
            af.duration_frames = ticks
    anim.fps = rate
    return exact


def change_animations(project: Project, ids: Iterable[str], rate: Optional[int] = None, keep_timing: bool = True,
                      playback_type: Optional[str] = None, loop_count: Optional[int] = None,
                      group: Optional[str] = None) -> Tuple[int, List[str]]:
    """Change several animations at once (the settings given, the others stay); returns how many there were and the
    names of those whose timing had to be rounded."""
    rounded: List[str] = []
    anims = [a for a in (project.get_animation(i) for i in ids) if a is not None]
    for anim in anims:
        if rate is not None and not change_tick_rate(anim, rate, keep_timing):
            rounded.append(anim.name)
        if playback_type is not None:
            anim.playback_type = playback_type
        if loop_count is not None:
            anim.loop_count = max(0, int(loop_count))
        if group is not None:
            anim.group = group.strip()
    return len(anims), rounded


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

