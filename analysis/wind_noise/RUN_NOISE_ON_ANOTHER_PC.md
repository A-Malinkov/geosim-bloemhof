# Task: run the high-resolution noise baseline on this PC

For an AI coding agent working in a clone of this repo, on a machine with
more memory than the one that wrote this (Windows is expected; Linux/macOS
work the same with the obvious path changes). Read `CLAUDE.md` first.

## Goal

Run `analysis/wind_noise/noise.py` once, for the **baseline**, and commit the
two files it writes:

- `data/processed/noise_baseline.json`
- `docs/fig_noise_baseline.png`

Nothing else should change. The code and parameters are final; this is a
compute job, not a development task.

## Why it is being run here

The run uses a dense receiver grid (triangles ≤ 100 m², 2 m output grid).
On the original laptop (16 GB RAM, ~4 GB free) the NoiseModelling JVM
segfaulted twice, 12–18 s into propagation — `SIGSEGV`, `SEGV_ACCERR`, at an
address inside the Java heap, in a different JIT-compiled method each time.
A third attempt with `JAVA_OPTS=-XX:+UseSerialGC -Xmx4g` got past that point
and was still running after 4 minutes when it was stopped, so the serial
garbage collector is the setting to use.

## Before you start: ask the user (Stefan) for anything that installs or downloads

Check each of these. If one is missing, **tell the user and ask before
installing or downloading anything**.

1. **Git is up to date** — `git pull`. `git log --oneline -1` must show a
   commit that contains this file. Commit or stash local work first.
2. **Python environment** — CLAUDE.md: it lives outside the repo, at
   `%USERPROFILE%\.venvs\geosim-rotterdam`. If missing:
   ```
   py -m venv %USERPROFILE%\.venvs\geosim-rotterdam
   %USERPROFILE%\.venvs\geosim-rotterdam\Scripts\pip install -r requirements.txt
   ```
3. **Java ≥ 11** — `java -version`. If missing, the user installs a JDK/JRE
   17 or newer (e.g. Eclipse Temurin from adoptium.net).
4. **NoiseModelling 6.0.0**, unpacked so that this file exists:
   `%USERPROFILE%\tools\NoiseModelling_6.0.0\bin\ScriptRunner.bat`
   Source: `NoiseModelling_6.0.0.zip` (155.7 MB) from
   <https://github.com/Universite-Gustave-Eiffel/NoiseModelling/releases/tag/v6.0.0>.
   Use the **zip**, not the `.exe` installer. Elsewhere is fine if you set
   `NOISEMODELLING_HOME` to the unpacked folder.
5. **Not inside a OneDrive-synced folder** — a sync client rewriting files
   under `.git` while git runs causes "incorrect old value provided" errors,
   and H2 database files being synced mid-run is worse. If the clone is under
   a synced Desktop/Documents, tell the user.

## Run

From the project root, in `cmd`:

```
set JAVA_OPTS=-XX:+UseSerialGC -Xmx8g
set NOISE_THREADS=8
%USERPROFILE%\.venvs\geosim-rotterdam\Scripts\python analysis\wind_noise\noise.py
```

- `-Xmx8g` assumes ≥ 16 GB free RAM; use about half the free RAM.
- `NOISE_THREADS` defaults to `min(8, cores)`. More threads is faster but
  each holds its own propagation buffers; raise it only if RAM allows.
- Expect a few minutes of fetching (Overpass, 3DBAG) on the first run, then
  NoiseModelling. The previous, 4× sparser run took ~9 min on 16 threads;
  this one will take longer — tens of minutes is normal. Run it in the
  background and check the log rather than waiting on a foreground timeout.
- The full NoiseModelling log goes to `cache\noise\baseline\noisemodelling.log`
  (`cache/` is gitignored). Progress lines look like
  `Begin processing of cell 2/4`.

**Check the exit code.** Do not pipe the run through `findstr`/`tail` without
preserving it: a crashed JVM once looked like success that way.

### If the JVM crashes again

The symptom is `A fatal error has been detected by the Java Runtime
Environment` and an `hs_err_pid*.log` in the NoiseModelling folder. Tell the
user, then try in this order, one change at a time:

1. `set NOISE_THREADS=4`
2. A different Java build/version, if the user agrees to install one.

Do **not** lower the resolution parameters (`MAX_TRIANGLE_M2`, `GRID_M` in
`noise.py`) without asking — getting that resolution is the point of the run.

## Verify before committing

The script prints a summary. Check it against the previous, coarser run
(5 m grid, default receivers), which gave:

| | previous |
|---|---|
| receiver Lden range | 32.0 – 82.8 dB |
| mean (open ground) | 55.5 dB |
| p95 | 75.7 dB |
| ≥ 53 dB | 63 % |
| ≥ 70 dB | 11 % |

The new run should be close — within ~2 dB on mean and p95, a few points on
the shares. Finer sampling of quiet squares may pull the mean down slightly.
Red flags that mean **do not commit**:

- a minimum around **−92 dB**, or many receivers far below 30 dB — that is
  the "no sound path" floor; it means over-roof diffraction was lost;
- a maximum above ~90 dB — speeds were not capped at the OSM `maxspeed`;
- `noise_baseline.json` not rewritten (check its timestamp), or its
  `method.grid_m` is not `2.0`.

Then open `docs\fig_noise_baseline.png`: Strevelsweg (the road along the
south edge of the outlined design site) should be the loudest band, the
courtyards inside the blocks the quietest, with no large empty holes inside
the outlined area.

Finally the app (CLAUDE.md, "Running and testing"): serve the project root,
hard-reload (Ctrl+Shift+R), tick **Analysis → Road-traffic noise, Lden**,
and confirm the overlay lines up with the streets and the console has no
errors.

## Deliver

Commit **only** these two files, then push:

```
git add data/processed/noise_baseline.json docs/fig_noise_baseline.png
git commit -m "Noise baseline at 2 m with dense receivers (run on Stefan's PC)"
git push
```

Put the printed summary (mean, p95, both shares, receiver count, runtime,
thread count and `JAVA_OPTS`) in the commit body so it is on record. Do not
commit `cache/`, `hs_err_pid*.log`, core dumps, or any change to code.
