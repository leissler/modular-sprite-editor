"""View ▸ Play at 50 Hz (PAL): the video frame rate every preview plays at.

The runtime counts video frames (the SGDK export turns each hold into frames at 60 a second, ``playback.console_frames``),
so on a 50 Hz console (PAL) animations, scenes and colour cycles all play at 5/6 of the speed. Kept in the preferences;
a console without a 50 Hz version (``consoles.Console.refresh_rates``) always plays at its own rate.
"""

from __future__ import annotations

from typing import Any, Optional

import consoles
from ui.preferences import config


class RefreshRate:
    KEY = "View/PlayAt50Hz"

    def __init__(self) -> None:
        self._pal: Optional[bool] = None

    @property
    def pal(self) -> bool:
        if self._pal is None:
            store = config()
            if store is None:  # no wx.App yet: the default, read again later
                return False
            self._pal = bool(store.ReadBool(self.KEY, False))
        return self._pal

    def set(self, pal: bool) -> None:
        self._pal = bool(pal)
        store = config()
        if store is not None:
            store.WriteBool(self.KEY, self._pal)

    def hz(self, project: Any) -> int:
        """Video frames a second the previews of ``project`` play at."""
        rates = consoles.console_by_key(getattr(project, "console", None)).refresh_rates
        return min(rates) if self.pal else rates[0]

    def speed(self, project: Any) -> float:
        """The previews' speed against the 60 frames a second the export counts with."""
        return self.hz(project) / 60.0


REFRESH = RefreshRate()
