"""Duration-normalized trajectory assumption penalty; no PhysiCell calls."""
import numpy as np

THRESHOLD = 1.25 / np.sqrt(3.)

def summarize_trace(trace, duration, threshold=THRESHOLD, scale=.05):
    if not np.isfinite(trace).all() or scale <= 0:
        raise ValueError('Nonfinite trajectory or invalid penalty scale')
    time = trace[:, 0]
    spacing = trace[:, 2] / (2 * trace[:, 1])
    # Append the exact episode horizon, interpolating only the final partial interval.
    keep = time < duration
    t = np.r_[time[keep], duration]
    q = np.r_[spacing[keep], np.interp(duration, time, spacing)]
    violation = np.maximum(0., threshold-q)
    penalty = float(np.trapz((violation/scale)**2, t)/duration) if duration > 0 else float((violation[-1]/scale)**2)
    fraction = float(np.trapz((violation > 0).astype(float), t)/duration) if duration > 0 else float(violation[-1] > 0)
    return dict(penalty=penalty, violation_fraction=fraction, min_relative_spacing=float(q.min()),
                max_violation=float(violation.max()), duration_days=float(duration))
