"""Averaging methods and the momentum check, written to run 'as of' any day using only polls
published by then (no hindsight). Used live (tracker.momentum, tracker.average) and in the
replay test (tracker.replay).

A poll here is a dict: {poll_id, firm, end (date), published (date), n (int|None), shares{party: pct}}.
"""
import csv
import datetime as dt
import math

import numpy as np

PARTIES = ["LAB", "CON", "REF", "LD", "GRN"]


# ---------------------------------------------------------------- loading

def _d(s):
    return dt.date.fromisoformat(s[:10]) if s else None


def load_tracker(outputs, include_all=False):
    """Polls from the tracker's outputs, with the average's inclusion rules applied."""
    from .average import inputs  # same rules as the published average
    polls = {r["poll_id"]: r for r in csv.DictReader((outputs / "polls.csv").open())}
    out = []
    for p in inputs():
        if p["excluded"] and not include_all:
            continue
        meta = polls[p["poll_id"]]
        pub = _d(meta.get("published_date"))
        # publication dates: upload/post date where we have it; never before fieldwork end,
        # and if missing or implausibly late (re-uploads), assume end + 2 days
        if not pub or pub < p["end"] or (pub - p["end"]).days > 14:
            pub = p["end"] + dt.timedelta(days=2)
        # and never later than the day we first downloaded it (so never in the future)
        seen = _d(meta.get("scraped_at"))
        if seen and seen >= p["end"]:
            pub = min(pub, seen)
        n = meta.get("sample_size_vi_unweighted") or meta.get("sample_size_total")
        out.append({"poll_id": p["poll_id"], "firm": p["pollster_id"], "end": p["end"], "published": pub,
                    "n": int(float(n)) if n else None, "shares": p["shares"]})
    return sorted(out, key=lambda p: (p["published"], p["firm"]))


def load_testset(path):
    out = []
    for r in csv.DictReader(path.open()):
        sh = {k: float(r[k] or 0) for k in ("CON", "LAB", "LD", "SNP", "GRN", "REF", "PC", "OTH")}
        tot = sum(sh.values()) or 100
        out.append({"poll_id": r["poll_id"], "firm": r["pollster_id"], "end": _d(r["fieldwork_end"]),
                    "published": _d(r["published_assumed"]), "n": int(r["sample_size"]) if r["sample_size"] else None,
                    "shares": {k: v / tot * 100 for k, v in sh.items()}})
    return sorted(out, key=lambda p: (p["published"], p["firm"]))


# ---------------------------------------------------------------- method A: windowed firm average

def window_average(polls, day, window=28, half_poll=7.0, half_firm=14.0, min_firms=3):
    """The v0.1 published average, restricted to polls published by `day`."""
    firms = {}
    for p in polls:
        if p["published"] > day:
            continue
        age = (day - p["end"]).days
        if 0 <= age < window:
            firms.setdefault(p["firm"], []).append((age, p))
    if len(firms) < min_firms:
        return None
    est, wsum = {k: 0.0 for k in PARTIES}, 0.0
    for lst in firms.values():
        pw = [(0.5 ** (a / half_poll), p) for a, p in lst]
        tw = sum(w for w, _ in pw)
        fw = 0.5 ** (min(a for a, _ in lst) / half_firm)
        for k in PARTIES:
            est[k] += fw * sum(w * p["shares"].get(k, 0) for w, p in pw) / tw
        wsum += fw
    return {k: v / wsum for k, v in est.items()}


# ---------------------------------------------------------------- method C: Kalman filter

class Kalman:
    """Forward-only Kalman filter, one party at a time.

    State: true level L (random walk, daily variance q) plus one house effect per firm
    (random walk with small daily variance qh, prior N(0, sd_h^2)). A poll from firm f measures
    L + h_f with noise variance = sampling variance (design effect 2) + tau^2 non-sampling noise.
    A firm's house effect is learned from its own polls relative to the others, so a new poll
    moves L mostly by how far it departs from that firm's own recent level - the within-firm
    change idea - and many firms moving together move L quickly.
    """

    def __init__(self, party, q=0.04, qh=0.002, sd_h=2.5, tau=1.0, deff=2.0, l0=None, sd_l0=10.0):
        self.party, self.q, self.qh, self.sd_h, self.tau, self.deff = party, q, qh, sd_h, tau, deff
        self.firms = []
        self.x = np.array([l0 if l0 is not None else 25.0])
        self.P = np.array([[sd_l0 ** 2]])
        self.day = None

    def _add_firm(self, f):
        self.firms.append(f)
        n = len(self.x)
        self.x = np.append(self.x, 0.0)
        P = np.zeros((n + 1, n + 1))
        P[:n, :n] = self.P
        P[n, n] = self.sd_h ** 2
        self.P = P

    def predict_to(self, day, q_scale=1.0):
        if self.day is not None and day > self.day:
            k = (day - self.day).days
            self.P[0, 0] += self.q * q_scale * k
            for i in range(1, len(self.x)):
                self.P[i, i] += self.qh * k
        self.day = day

    def update(self, poll, tau=None):
        f = poll["firm"]
        if f not in self.firms:
            self._add_firm(f)
        i = self.firms.index(f) + 1
        y = poll["shares"].get(self.party, 0.0)
        p = min(max(y / 100, 0.01), 0.99)
        n = poll["n"] or 1500
        R = p * (1 - p) / (n / self.deff) * 1e4 + (self.tau if tau is None else tau) ** 2
        H = np.zeros(len(self.x))
        H[0], H[i] = 1.0, 1.0
        S = H @ self.P @ H + R
        K = self.P @ H / S
        resid = y - H @ self.x
        self.x = self.x + K * resid
        self.P = self.P - np.outer(K, H @ self.P)
        return resid, S

    @property
    def level(self):
        return float(self.x[0])

    @property
    def sd(self):
        return float(math.sqrt(self.P[0, 0]))

    def house(self):
        return {f: float(self.x[i + 1]) for i, f in enumerate(self.firms)}


def run_kalman(polls, start, end, party, adaptive=False, **kw):
    """Daily filtered level (as of each day, polls published up to and including that day)."""
    first = [p for p in polls if p["published"] <= start + dt.timedelta(days=30)]
    l0 = float(np.mean([p["shares"].get(party, 0) for p in first])) if first else None
    kf = Kalman(party, l0=l0, **kw)
    by_day = {}
    for p in polls:
        by_day.setdefault(p["published"], []).append(p)
    out, d = {}, min(p["published"] for p in polls)
    mom = {}
    while d <= end:
        scale = 1.0
        if adaptive:
            m = momentum(polls, d - dt.timedelta(days=1), parties=[party]).get(party)
            if m and m["flag"]:
                scale = 6.0  # opinion is visibly moving: let the level move faster
        kf.predict_to(d, q_scale=scale)
        for p in by_day.get(d, []):
            kf.update(p)
        if d >= start:
            out[d] = (kf.level, kf.sd)
        d += dt.timedelta(days=1)
    return out, kf


# ---------------------------------------------------------------- v0.3: smoother, firm noise, adaptive speed

def kalman_run(polls, start, end, party, q=0.15, q_fast=None, flags=None, firm_noise=False,
               smooth=False, noise_window=15, noise_min=5, **kw):
    """One pass of the filter over every day from the first publication to `end`.

    - q: daily variance of true opinion. With `flags` (day -> party -> bool, from
      momentum_flags) and `q_fast`, the filter uses q_fast on days the momentum check is on:
      slow and steady normally, fast when firms are visibly moving together.
    - firm_noise: learn each firm's own scatter from its last `noise_window` pre-update
      residuals (only past polls), scaling its non-sampling noise by observed/expected
      (clipped 0.5-4x), so a noisy firm moves the line less.
    - smooth: also return a Rauch-Tung-Striebel smoothed series (history revised with later
      polls; the last day equals the filtered value).
    Returns dict(filtered={day: (level, sd)}, smoothed={day: (level, sd)} or None,
                 resid=[(day, firm, resid, n_prior_polls_from_firm)], kf=filter)."""
    firms = sorted({p["firm"] for p in polls})
    first = [p for p in polls if p["published"] <= start + dt.timedelta(days=30)]
    l0 = float(np.mean([p["shares"].get(party, 0) for p in first])) if first else None
    kf = Kalman(party, q=q, l0=l0, **kw)
    for f in firms:
        kf._add_firm(f)
    by_day = {}
    for p in polls:
        by_day.setdefault(p["published"], []).append(p)
    hist = {f: [] for f in firms}  # (resid^2, S) per firm
    counts = {f: 0 for f in firms}
    filtered, resids, store = {}, [], []
    d = min(p["published"] for p in polls)
    while d <= end:
        fast = bool(q_fast and flags and flags.get(d, {}).get(party))
        kf.q = q_fast if fast else q
        kf.predict_to(d)
        xp, Pp = kf.x.copy(), kf.P.copy()
        for p in by_day.get(d, []):
            tau = None
            if firm_noise and len(hist[p["firm"]]) >= noise_min:
                h = hist[p["firm"]][-noise_window:]
                ratio = sum(r for r, _ in h) / sum(s_ for _, s_ in h)
                tau = kf.tau * math.sqrt(min(4.0, max(0.5, ratio)))
            resid, S = kf.update(p, tau=tau)
            if d >= start:
                resids.append((d, p["firm"], resid, counts[p["firm"]]))
            hist[p["firm"]].append((resid ** 2, S))
            counts[p["firm"]] += 1
        if smooth:
            store.append((d, xp, Pp, kf.x.copy(), kf.P.copy()))
        if d >= start:
            filtered[d] = (kf.level, kf.sd)
        d += dt.timedelta(days=1)
    smoothed = None
    if smooth:
        xs, Ps = store[-1][3], store[-1][4]
        smoothed = {store[-1][0]: (float(xs[0]), float(math.sqrt(Ps[0, 0])))}
        for t in range(len(store) - 2, -1, -1):
            day, _, _, xf, Pf = store[t]
            _, xp1, Pp1, _, _ = store[t + 1]
            C = np.linalg.solve(Pp1, Pf.T).T  # Pf @ inv(Pp1); transition is the identity
            xs = xf + C @ (xs - xp1)
            Ps = Pf + C @ (Ps - Pp1) @ C.T
            if day >= start:
                smoothed[day] = (float(xs[0]), float(math.sqrt(max(Ps[0, 0], 0.0))))
    return {"filtered": filtered, "smoothed": smoothed, "resid": resids, "kf": kf}


def momentum_flags(polls, start, end, on_p=0.05, off_p=0.2, min_move=1.0, off_move=0.5, **kw):
    """Momentum flag with hysteresis, as known on each day (uses polls published the day before).

    Switches on when the momentum check fires (p < on_p, mean change >= min_move, >= 4 polls);
    stays on until the evidence has clearly gone (p > off_p or mean change < off_move or a
    reversal of direction). Returns {day: {party: direction (+1/-1) or 0}}."""
    state = {k: 0 for k in PARTIES}
    out, d = {}, start
    while d <= end:
        m = momentum(polls, d - dt.timedelta(days=1), p_cut=on_p, min_move=min_move, **kw)
        for k in PARTIES:
            x = m[k]
            sign = 1 if x["mean_change"] > 0 else -1
            if state[k] == 0 and x["flag"]:
                state[k] = sign
            elif state[k] != 0 and (x["p"] > off_p or abs(x["mean_change"]) < off_move or sign != state[k]):
                state[k] = 0
        out[d] = dict(state)
        d += dt.timedelta(days=1)
    return out


def jumpiness(series):
    """Mean absolute day-to-day change, and direction reversals per 100 days (moves < 0.05pt ignored)."""
    days = sorted(series)
    v = [series[d][0] if isinstance(series[d], tuple) else series[d] for d in days]
    ch = [b - a for a, b in zip(v, v[1:])]
    mv = [c for c in ch if abs(c) >= 0.05]
    rev = sum(1 for a, b in zip(mv, mv[1:]) if (a > 0) != (b > 0))
    return (sum(abs(c) for c in ch) / len(ch) if ch else 0.0, rev / len(days) * 100 if days else 0.0)


# ---------------------------------------------------------------- momentum check

def momentum(polls, day, lookback=7, max_gap=60, parties=PARTIES, min_polls=4, p_cut=0.05, min_move=1.0):
    """Are firms moving against their own previous polls?

    For every poll published in the `lookback` days to `day`, compare it with the same firm's
    previous poll (published within `max_gap` days before). Per party: how many went up/down,
    the mean change, and a two-sided sign test. House effects cancel because each comparison
    is within one firm. Flag when p < p_cut and the mean change is at least `min_move` points."""
    recent = [p for p in polls if day - dt.timedelta(days=lookback) < p["published"] <= day]
    by_firm = {}
    for p in polls:
        if p["published"] <= day:
            by_firm.setdefault(p["firm"], []).append(p)
    pairs = []
    for p in recent:
        prev = [q for q in by_firm[p["firm"]] if q["published"] < p["published"]
                and (p["published"] - q["published"]).days <= max_gap]
        if prev:
            pairs.append((p, max(prev, key=lambda q: (q["published"], q["end"]))))
    out = {}
    for k in parties:
        ds = [p["shares"].get(k, 0) - q["shares"].get(k, 0) for p, q in pairs]
        up, down = sum(x > 0.5 for x in ds), sum(x < -0.5 for x in ds)
        n = up + down
        pval = _sign_p(up, n) if n else 1.0
        mean = sum(ds) / len(ds) if ds else 0.0
        out[k] = {"n_polls": len(ds), "up": up, "down": down, "same": len(ds) - n, "mean_change": mean,
                  "p": pval, "flag": len(ds) >= min_polls and pval < p_cut and abs(mean) >= min_move,
                  "firms": sorted({p["firm"] for p, _ in pairs})}
    return out


def _sign_p(k, n):
    """Two-sided exact sign test: probability of a split at least this lopsided if up/down are 50:50."""
    lo = min(k, n - k)
    tail = sum(math.comb(n, i) for i in range(lo + 1)) / 2 ** n
    return min(1.0, 2 * tail)
