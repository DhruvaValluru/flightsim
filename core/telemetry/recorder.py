"""Read-only telemetry recording.

The observer tier (§2.1). A recorder samples :class:`AircraftState` and stores
columns. It holds no reference that would let it write back to the FDM, and
:class:`AircraftState` is frozen, so a recorder cannot influence the trajectory
it is recording. The previous build's ``fs_kinematics.py`` sat in exactly this
position and rewrote the trajectory on its way past.

Every quantity recorded is read from JSBSim. Nothing here is differentiated,
smoothed, or reconstructed -- in particular ``load_factor`` comes from the
accelerometer, which is the §1.3 fix.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..fdm.state import AircraftState

#: Sampled for every run. Names match :class:`AircraftState` attributes or
#: properties; the recorder resolves either.
DEFAULT_CHANNELS = (
    "t",
    "altitude_m",
    "agl_m",
    "cas_kt",
    "tas_kt",
    "mach",
    "climb_rate_mps",
    "pitch_deg",
    "roll_deg",
    "heading_deg",
    "alpha_deg",
    "beta_deg",
    "n_z",
    "pitch_rate_dps",
    "roll_rate_dps",
    "track_deg",
    "crab_deg",
    "wind_speed_mps",
    "weight_kg",
    # -- the aero block (Phase 8 panel): the FDM's own aerodynamic state.
    # qbar and the six force components are direct JSBSim outputs (lift and
    # drag come from the FDM's wind-axis resolution, not a transform here);
    # gamma is the state's flight-path property. Recorded, NOT graded: the
    # Gate 5 comparison channel set does not grow (frozen by test).
    "qbar_pa",
    "f_aero_x_n",
    "f_aero_y_n",
    "f_aero_z_n",
    "drag_n",
    "side_force_n",
    "lift_n",
    "flight_path_angle_deg",
    "wind_north_mps",
    "wind_east_mps",
    "wind_down_mps",
    "v_north_mps",
    "v_east_mps",
    "v_down_mps",
    # -- the atmosphere block (gap P1): what the FDM's atmosphere delivered
    # at the sample -- density and pressure altitude by JSBSim's own
    # inversion, humidity, vapour pressure, temperature and pressure.
    # Recorded, NOT graded: the Gate 5 comparison set is unchanged.
    "density_altitude_m",
    "pressure_altitude_m",
    "rh_pct",
    "vapour_pressure_pa",
    "temperature_k",
    "pressure_hpa",
    # -- the gust and wind-profile channels (P6): the gust channel as JSBSim
    # holds it (the stack's summed gust, read back), the equivalent roll
    # rate the derived airframe received (0 on a stock one), the base
    # wind's horizontal speed (the profile's speed at the altitude). The
    # profile's layer index and dV/dz are not JSBSim's: the runner records
    # them through Recorder ``extra`` from the stack (STACK_CHANNELS in
    # core/environment/stack.py). Recorded, NOT graded: the Gate 5
    # comparison set is unchanged.
    "gust_north_mps",
    "gust_east_mps",
    "gust_down_mps",
    "gust_p_equivalent_rad_s",
    "wind_profile_speed_mps",
)


class Recorder:
    """Samples state into columns at a fixed interval.

    Parameters
    ----------
    fdm:
        The instance to observe. Used only for reads.
    interval_s:
        Sampling period. Independent of the integration rate: the FDM always
        steps at its fixed dt, and sampling never changes what is integrated.
    channels:
        State attributes to record.
    extra:
        Additional named callables taking the FDM and returning a float, for
        quantities that are not on the state snapshot -- control-surface
        positions, for example.
    """

    def __init__(
        self,
        fdm,
        interval_s: float = 0.1,
        channels=DEFAULT_CHANNELS,
        extra: Optional[Dict[str, Callable[[Any], float]]] = None,
    ) -> None:
        self._fdm = fdm
        self.interval_s = float(interval_s)
        self.channels = tuple(channels)
        self._extra = dict(extra or {})
        self.columns: Dict[str, List[float]] = {
            name: [] for name in (*self.channels, *self._extra)
        }
        #: Annotations: (time, label). Marks events so a chart can show when a
        #: control input or condition change was applied.
        self.events: List[Dict[str, Any]] = []
        #: Columns added AFTER the run by an observer (the limits
        #: monitor's 0/1 flags): derived from the recorded columns, never
        #: read from JSBSim, named here so a reader can tell them apart.
        self.derived: List[str] = []
        self._next_sample = 0.0

    # -- recording -----------------------------------------------------

    def sample(self, force: bool = False) -> bool:
        """Record one row if the sampling interval has elapsed."""
        t = self._fdm.sim_time
        if not force and t < self._next_sample:
            return False
        state = self._fdm.state()
        for name in self.channels:
            self.columns[name].append(_read(state, name))
        for name, fn in self._extra.items():
            self.columns[name].append(float(fn(self._fdm)))
        self._next_sample = t + self.interval_s
        return True

    def mark(self, label: str) -> None:
        """Annotate the current time with an event label."""
        self.events.append({"t": self._fdm.sim_time, "label": label})

    def run_for(self, seconds: float) -> None:
        """Step the FDM for ``seconds``, sampling as it goes."""
        steps = int(round(seconds * self._fdm.rate_hz))
        for _ in range(steps):
            self._fdm.step()
            self.sample()

    def annotate(self, name: str, values) -> None:
        """Add a DERIVED column after the run, one value per sample.

        For observers that grade the recording (core.telemetry.limits):
        the column rides beside the recorded ones so every per-frame
        consumer sees it, and ``derived`` names it as not-from-JSBSim.
        Refuses a name that would shadow a recorded channel and a
        length that does not match the run -- a flag column shorter
        than the telemetry would label the wrong frames.
        """
        if name in self.columns:
            raise ValueError(f"{name!r} is already a column; an annotation "
                             f"never overwrites a recorded channel")
        values = list(values)
        if len(values) != len(self):
            raise ValueError(f"annotation {name!r} has {len(values)} values for "
                             f"{len(self)} samples")
        self.columns[name] = values
        self.derived.append(name)

    # -- output --------------------------------------------------------

    def __len__(self) -> int:
        return len(self.columns[self.channels[0]])

    def series(self, name: str) -> List[float]:
        return self.columns[name]

    def span(self, name: str):
        col = self.columns[name]
        return (min(col), max(col)) if col else (math.nan, math.nan)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provenance": self._fdm.provenance(),
            "interval_s": self.interval_s,
            "samples": len(self),
            "events": self.events,
            "derived": list(self.derived),
            "columns": self.columns,
        }

    def write_json(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")
        return path


def _read(state: AircraftState, name: str) -> float:
    try:
        return float(getattr(state, name))
    except AttributeError as exc:
        raise AttributeError(
            f"{name!r} is not a channel on AircraftState. Available: "
            f"{sorted(f for f in dir(state) if not f.startswith('_'))}"
        ) from exc
