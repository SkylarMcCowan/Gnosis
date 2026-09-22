# Paranormal Investigation Lab — Phase 1

Open **Investigation Lab** in the Gnosis navigation rail. Measure first. Interpret later.
The pane never classifies evidence as paranormal, speech, entities, or EVP.
No external hardware, online service, location lookup, or model inference is used.

## Workflow

1. Enter investigation name, investigator, manually supplied location/weather and environmental notes.
2. Choose WAV PCM 16-bit mono at 48 kHz or 44.1 kHz, optional continuous recording,
   baseline duration, threshold above baseline RMS, pre/post buffers, and a frequency band.
3. Create a session, then press **Start microphone**. Only identifiable built-in Mac microphone
   device names are selected; the system default is never silently substituted.
4. Press **CALIBRATE BASELINE**. Detection starts only after the configured amount of audio
   has been captured. Recalibration replaces the baseline and ends any pending event.
5. Use **MARK EVENT** at any time during a session, including without microphone access.
6. Review the timestamped timeline and event metadata. End the session to finalize WAV headers
   and metadata. Closing Gnosis also waits asynchronously for evidence to finish saving.

Session folders live under the configured Gnosis data directory in `investigations/`.
`session.json` stores configuration and metadata; `events.jsonl` is an append-only event journal.
Each event clip is an exclusively created original WAV. Continuous recordings rotate every
30 minutes to remain below classic WAV size limits. Nothing edits original samples.
Audio event IDs are assigned when the clip finishes, while the timeline is ordered by onset.
A session can also consist entirely of manual markers. Interpretations and hypotheses are
separate empty fields reserved for the later evidence-review phase; manual notes are stored separately.

## Measurements and limitations

PCM samples are direct digital microphone input. RMS, peak, Hann-windowed FFT, dominant
frequency, band energy, spectrum history and baseline statistics are derived calculations.
All levels use **dBFS**, with a display floor of −120 dBFS; they are not calibrated dB SPL.
A 4096-sample analysis window gives approximately 11.7 Hz resolution at 48 kHz.
Baseline RMS is computed from mean sample power, not averaged decibels. Baseline spectra
average spectral power. A deviation means window RMS exceeds the baseline by the chosen
threshold; it does not imply a voice or explain the source of a sound.

The built-in microphone is not a calibrated infrasound instrument. Its response and macOS
input processing can affect low-frequency observations. The selectable band is a derived
FFT band measurement, not a new environmental sensor. Playback, speech, TTS, fans and
other application sounds can contaminate the baseline and should be noted by the investigator.

Pre-buffers contain up to the configured duration actually captured before onset. Post-buffers
end on the first complete analysis window at or after the chosen duration below threshold.
Sustained events split at 60 seconds; clips interrupted by stop, recalibration, or that cap
are marked `truncated`. Event durations cover threshold-exceeding windows including gaps
shorter than the post-buffer. Time resolution is one analysis window. UTC timestamps use
first-buffer receipt minus its duration followed by sample counts; hardware/OS latency is
not measured. These are not precision synchronized hardware timestamps.

Live plots refresh at up to 10 Hz. The spectrogram is a bounded recent **display** history,
not a saved full-resolution spectrogram; captured WAVs retain audio for future analysis.
Background processing uses a bounded queue and fails visibly on overflow rather than hiding
missing samples. Device errors end capture. Disk errors appear as ERROR; incomplete files
may remain for recovery. Normal shutdown finalizes files; power loss cannot guarantee recovery.

## macOS API verification and permissions

Verified against the official Qt documentation on 2026-09-20:

- [Qt on macOS / arm64 support](https://doc.qt.io/qt-6.8/macos.html)
- [QAudioSource: input devices, supported formats and capture errors](https://doc.qt.io/qt-6/qaudiosource.html)
- [Apple microphone usage declaration](https://developer.apple.com/documentation/bundleresources/information-property-list/nsmicrophoneusagedescription)
- [QMicrophonePermission](https://doc.qt.io/qt-6/qmicrophonepermission.html)
- [Qt application permissions](https://doc.qt.io/qt-6/permissions.html)

The implementation uses the QIODevice audio input API available in the existing PyQt6
requirement, not newer callback-only APIs. PyQt6.QtMultimedia and QMicrophonePermission
were import-checked locally. Actual M1 microphone recording still requires a user-run hardware
acceptance test; automated tests use explicit synthetic fixtures only, never simulated live sensors.

macOS requires `NSMicrophoneUsageDescription` in the GUI launcher's main application bundle
Info.plist before microphone permission can be requested. Packaged builds must include, e.g.:

```xml
<key>NSMicrophoneUsageDescription</key>
<string>Gnosis records microphone audio locally for investigator-controlled environmental measurements.</string>
```

A sandboxed app also needs the audio-input entitlement. Qt supports requesting permissions
from GUI applications. When running `./run_gui.sh`, the relevant host may be the Python GUI
launcher rather than Gnosis itself. This pane inspects the actual main bundle using public
CoreFoundation APIs and refuses to request access if the usage declaration is missing,
avoiding macOS privacy termination. It does not modify the Python installation or bypass TCC.
Launch using `./run_gui.sh` to use the project-local GUI bundle described below. If denied, enable the relevant host in
System Settings → Privacy & Security → Microphone, then retry. No permission is requested
when opening the pane, creating a session or making manual markers.

## Project-local microphone-capable launcher

`./run_gui.sh` now calls `scripts/macos_gui.py`. On macOS with framework Python (including
this project's current installation), it copies Python.app into the ignored `.gnosis-macos/`
cache, adds Gnosis's microphone usage description and app identity, and ad-hoc signs that
**copy** using macOS codesign. The Python installation remains untouched. The launcher
retains the project venv using CPython's `__PYVENV_LAUNCHER__` mechanism. It does not request
microphone permission; only the pane's explicit button does that. No camera, location or
Bluetooth usage permissions are added.

The local bundle/venv combination was verified in a subprocess: the actual main bundle
exposes the usage declaration and `sys.executable` remains the project venv. This is a local
development launcher, not a redistributable or notarized application. Other Python layouts
fall back to the original launch behavior with a diagnostic. Directly invoking
`python webagent_gui.py` may still lack the required declaration; prefer `./run_gui.sh`.

## Scope

Phase 1 implements sessions, microphone capture, optional continuous WAV recording,
waveform/FFT/live spectrogram, band measurements, baseline calibration, buffered audio events,
manual markers, and a filterable chronological timeline. A format unsupported by the actual
built-in device is shown as UNAVAILABLE, without fabricated measurements.

Camera and visual events, evidence playback/browser and blind review remain Phase 2.
Wi-Fi/Bluetooth observation and cross-sensor correlation remain Phase 3. Simulated sweep,
controlled experiments, reports and hashing/provenance remain Phase 4. Unimplemented sensors
are explicitly unavailable; this does not assert that macOS can never expose those APIs.
This version has no EMF, ambient-temperature, light, radio-frequency, or paranormal detector.
