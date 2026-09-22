"""Bounded worker queue: acquisition stays lightweight; analysis and disk IO are off-UI."""
import queue
import threading
import time
import os
from .session import now
from .evidence import EvidenceStore, append_record
from .camera_monitor import CameraMonitor
from .network_monitor import NetworkMonitor
from .reports import generate_report
from .audio_recorder import Recorder
from .event_detector import Detector
from .session import Session
from .spectrum import measure


class InvestigationWorker(threading.Thread):
    def __init__(self, root, metadata, config):
        super().__init__(daemon=True, name='investigation-audio')
        self.root, self.metadata, self.config = root, metadata, config
        self.commands = queue.Queue(maxsize=128)
        self.stopping = threading.Event()
        self.snapshot = {'state': 'INACTIVE', 'detail': 'Creating session…'}
        self.failure = None
        self.session = None
        self.latest_metrics = None
        self.started_at = time.monotonic()
        self.ended_at = None
        self.camera_pending = False
        self.environment_calibration = None
        self.network_state = {"state": "INACTIVE"}
        self.camera_metrics = None

    def submit(self, kind, value=None):
        try:
            self.commands.put_nowait((kind, value))
            return True
        except queue.Full:
            self.failure = 'Processing queue overflow; capture stopped. Evidence may contain a gap.'
            self.stopping.set()
            return False

    def run(self):
        recorder = None
        detector = None
        buffer = bytearray()
        camera = None
        network = NetworkMonitor()
        network_enabled = False
        next_network = 0
        continuous_file = None
        state, detail = 'INACTIVE', 'Session open. Start microphone to monitor.'
        try:
            self.session = Session(self.root, self.metadata, self.config)
            detector = Detector(self.session, self.config)
            camera = CameraMonitor(self.session, self.config.get("camera_threshold", 4), self.config.get("timelapse_seconds", 0))
            store = EvidenceStore(self.session.directory)
            self.snapshot = dict(state=state, detail=detail, directory=str(self.session.directory))
            while not self.stopping.is_set() or not self.commands.empty():
                if network_enabled and time.monotonic() >= next_network:
                    self.network_state = network.observe()
                    append_record(self.session.directory / 'network_observations.jsonl', self.network_state)
                    self.session.data['sensors']['wifi'] = self.network_state['state'] + ' — ' + self.network_state.get('detail', '')
                    if self.network_state.get('count_change') or self.network_state.get('appeared') or self.network_state.get('disappeared'):
                        self.session.event('Network', 'Network environment cache changed.', measurements=self.network_state)
                    self.session.save()
                    next_network = time.monotonic() + 15
                    self.snapshot = {**self.snapshot, 'network': self.network_state}
                if self.environment_calibration and time.monotonic() >= self.environment_calibration['deadline']:
                    baseline = dict(self.environment_calibration)
                    baseline.pop('deadline')
                    baseline['completed_at'] = now()
                    baseline['network'] = dict(self.network_state)
                    baseline['system_load_average'] = list(os.getloadavg()) if hasattr(os, 'getloadavg') else None
                    baseline['measurement_note'] = 'Frame brightness and differences are derived, not lux. Load average is OS system activity, not an environmental sensor. Wi-Fi is cached, freshness unknown.'
                    self.session.data['environment_baseline'] = baseline
                    self.session.save()
                    self.environment_calibration = None
                    self.snapshot = {**self.snapshot, 'environment_calibrating': False, 'environment_baseline': baseline}
                try:
                    kind, value = self.commands.get(timeout=0.1)
                except queue.Empty:
                    continue
                if kind == 'audio':
                    if detector.origin is None:
                        detector.origin = self.session.timestamp(-len(value[0]) / (2 * self.config["rate"]), value[1])
                        self.session.data["sensors"]["microphone"] = "ACTIVE"
                        self.session.save()
                    buffer.extend(value[0])
                    if self.config['continuous'] and recorder is None and buffer:
                        filename = 'continuous-0001.wav'
                        continuous_file = filename
                        recorder = Recorder(self.session.directory / filename, self.config['rate'])
                        self.session.data['continuous_recordings'].append(filename)
                        self.session.save()
                    while len(buffer) >= 8192:
                        pcm = bytes(buffer[:8192])
                        del buffer[:8192]
                        metrics = measure(pcm, self.config['rate'], self.config['band'])
                        if self.config['continuous']:
                            if recorder is None or recorder.frames >= self.config['rate'] * 1800:
                                if recorder:
                                    recorder.close()
                                    store.register(continuous_file, parameters={'capture': 'Continuous audio'})
                                filename = f'continuous-{len(self.session.data["continuous_recordings"]) + 1:04d}.wav'
                                continuous_file = filename
                                recorder = Recorder(self.session.directory / filename, self.config['rate'])
                                self.session.data['continuous_recordings'].append(filename)
                                self.session.save()
                            recorder.write(pcm)
                        detector.feed(pcm, metrics)
                        self.latest_metrics = metrics
                    state, detail = 'ACTIVE', 'Built-in microphone monitoring'
                elif kind == 'calibrate':
                    detector.calibrate(value)
                    self.environment_calibration = dict(started_at=now(), duration_seconds=value, deadline=time.monotonic() + value, camera_samples=[])
                    self.session.data['baseline'] = None
                    self.session.save()
                elif kind == 'marker':
                    self.session.event('Manual', value['observation'] or 'Manual event marker.',
                                       timestamp=value['timestamp'], investigator_notes=value['notes'])
                elif kind == 'camera':
                    try:
                        self.camera_metrics = camera.feed(*value)
                        if self.environment_calibration:
                            self.environment_calibration['camera_samples'].append(dict(timestamp=value[1], **self.camera_metrics))
                    finally:
                        self.camera_pending = False
                elif kind == 'camera_stop':
                    camera.finish()
                    camera.previous = None
                elif kind == 'network':
                    network_enabled = bool(value)
                    next_network = 0
                elif kind == 'sensor':
                    self.session.data['sensors'][value[0]] = value[1]
                    self.session.save()
                elif kind == 'experiment':
                    self.session.event('Experiment', 'Investigator-defined experiment interval started.',
                                       timestamp=value['timestamp'], label=value['label'], trial=value['trial'])
                elif kind == 'playback':
                    self.session.event('System', 'Local playback initiated; may affect microphone measurements.', **value)
                elif kind == 'camera_device':
                    self.session.data['camera_device'] = value
                    self.session.save()
                elif kind == 'device':
                    self.session.data['equipment'] = value
                    self.session.save()
                self.snapshot = dict(state=state, detail=detail, metrics=self.latest_metrics,
                                     baseline=detector.baseline, calibrating=detector.calibration is not None,
                                     calibration_seconds=(detector.calibration['frames'] / self.config['rate'] if detector.calibration else 0),
                                     count=self.session.count, directory=str(self.session.directory),
                                     recording=recorder is not None, network=self.network_state, camera=self.camera_metrics,
                                     environment_calibrating=self.environment_calibration is not None)
            if self.failure:
                self.session.event('System', self.failure)
        except Exception as exc:
            self.failure = f'{type(exc).__name__}: {exc}'
        finally:
            # Finalize each resource independently, even if another file cannot be written.
            if recorder:
                try:
                    if buffer:
                        recorder.write(bytes(buffer[:len(buffer) // 2 * 2]))
                except Exception as exc:
                    self.failure = self.failure or f'Final audio write failed: {exc}'
                finally:
                    try:
                        recorder.close()
                        if self.session and continuous_file:
                            store.register(continuous_file, parameters={'capture': 'Continuous audio'})
                    except Exception as exc:
                        self.failure = self.failure or f'WAV finalization failed: {exc}'
            if detector:
                try:
                    if detector.pending and buffer:
                        detector.pending["writer"].write(bytes(buffer[:len(buffer) // 2 * 2]))
                except Exception as exc:
                    self.failure = self.failure or f'Event tail write failed: {exc}'
                finally:
                    try:
                        detector.finish(truncated=True)
                    except Exception as exc:
                        self.failure = self.failure or f'Event finalization failed: {exc}'
            if camera:
                try:
                    camera.finish()
                except Exception as exc:
                    self.failure = self.failure or f"Camera finalization failed: {exc}"
            if self.session:
                try:
                    self.session.data['error'] = self.failure
                    self.session.close()
                    store.register('session.json', 'metadata')
                    for journal in ('events.jsonl', 'network_observations.jsonl'):
                        if (self.session.directory / journal).exists():
                            store.register(journal, 'metadata')
                    generate_report(self.session.directory)
                except Exception as exc:
                    self.failure = self.failure or f'Session finalization failed: {exc}'
            self.ended_at = time.monotonic()
            self.snapshot = {**self.snapshot, 'state': 'ERROR' if self.failure else 'INACTIVE',
                             'detail': self.failure or 'Session saved.', 'recording': False,
                             'calibrating': False}
