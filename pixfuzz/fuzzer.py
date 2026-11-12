"""Coverage-guided fuzzing loop for harlequin.decode_bytes.

Each candidate input runs in-process under a per-input wall-clock timeout
(SIGALRM) and a per-input address-space cap (RLIMIT_AS), while a settrace
tracer records real line/edge coverage of the harlequin package. Inputs
that hit new coverage join the corpus; inputs that time out, exhaust
memory, or raise anything that is not a clean HarlequinError are recorded
as crashes and deduplicated by a traceback fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import random
import resource
import shlex
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field

from .coverage import CoverageTracer, total_executable_lines
from .mutator import Mutator, load_dictionary

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harlequin  # noqa: E402
from harlequin.errors import HarlequinError  # noqa: E402

MAX_SAVED_SAMPLES_PER_FP = 8


class _Timeout(Exception):
    """Raised by the SIGALRM handler when an input exceeds its budget."""


def _alarm_handler(signum, frame):
    raise _Timeout()


@dataclass
class Outcome:
    kind: str  # "ok" | "reject" | "crash"
    crash_kind: str | None = None  # "timeout" | "memory" | "signal" | "exception"
    exception: str | None = None
    fingerprint: str | None = None
    wall: float = 0.0


@dataclass
class Crash:
    id: str
    fingerprint: str
    exception: str
    kind: str
    input: str
    replay: str


@dataclass
class WorkerResult:
    executions: int = 0
    elapsed: float = 0.0
    lines: set = field(default_factory=set)
    crashes: list = field(default_factory=list)  # list[Crash]


def _fingerprint_exception(exc: BaseException) -> str:
    tb = traceback.extract_tb(exc.__traceback__)
    frames = [
        (os.path.basename(f.filename), f.lineno)
        for f in tb
        if f"{os.sep}harlequin{os.sep}" in f.filename
    ]
    if not frames:
        frames = [(os.path.basename(f.filename), f.lineno) for f in tb[-3:]]
    if len(frames) > 8:
        # Recursive blowups: the outermost frames are the stable part.
        frames = frames[:8]
    raw = repr((type(exc).__name__, frames))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def run_one(data: bytes, timeout: float, rss_bytes: int, tracer: CoverageTracer) -> Outcome:
    """Decode one input with per-input time and memory limits."""
    old_soft, old_hard = resource.getrlimit(resource.RLIMIT_AS)
    new_soft = rss_bytes
    if old_hard >= 0:
        new_soft = min(new_soft, old_hard)
    limited = old_soft < 0 or old_soft > new_soft
    if limited:
        resource.setrlimit(resource.RLIMIT_AS, (new_soft, old_hard))
    start = time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, timeout)
    exc: BaseException | None = None
    try:
        tracer.run(lambda: harlequin.decode_bytes(data))
    except BaseException as e:  # noqa: BLE001 - classification happens below
        exc = e
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if limited:
            resource.setrlimit(resource.RLIMIT_AS, (old_soft, old_hard))
    wall = time.monotonic() - start

    if exc is None:
        if wall > timeout:
            return Outcome("crash", "timeout", "timeout (completed past budget)", "timeout", wall)
        return Outcome("ok", wall=wall)
    if isinstance(exc, _Timeout):
        return Outcome("crash", "timeout", "timeout", "timeout", wall)
    if isinstance(exc, HarlequinError):
        return Outcome("reject", wall=wall)
    if isinstance(exc, MemoryError):
        return Outcome("crash", "memory", "MemoryError", "mem:" + _fingerprint_exception(exc), wall)
    name = type(exc).__name__
    return Outcome("crash", "exception", name, _fingerprint_exception(exc), wall)


def _replay_command(input_path: str) -> str:
    return f"{shlex.quote(sys.executable)} -m harlequin decode {shlex.quote(input_path)} --out /tmp/pixfuzz-replay.ppm"


class FuzzWorker:
    def __init__(self, args, worker_id: int = 0) -> None:
        self.args = args
        self.worker_id = worker_id
        self.out_dir = os.path.abspath(args.out_dir)
        self.corpus_dir = os.path.join(self.out_dir, "corpus")
        self.crashes_dir = os.path.join(self.out_dir, "crashes")
        os.makedirs(self.corpus_dir, exist_ok=True)
        os.makedirs(self.crashes_dir, exist_ok=True)
        self.rng = random.Random((time.time_ns() ^ (os.getpid() << 16) ^ worker_id) & 0xFFFFFFFFFFFFFFFF)
        tokens = load_dictionary(args.dict_path) if args.dict_path else []
        self.mutator = Mutator(self.rng, tokens)
        self.tracer = CoverageTracer()
        self.rss_bytes = args.rss_mb * 1024 * 1024
        self.global_lines: set = set()
        self.global_edges: set = set()
        self.corpus: list[bytes] = []
        self.favored: list[bytes] = []
        self.crashes: dict[str, Crash] = {}
        self.samples_per_fp: dict[str, int] = {}
        self.executions = 0
        self._known_corpus_files: set[str] = set()

    def _save_corpus(self, data: bytes) -> None:
        digest = hashlib.sha1(data).hexdigest()[:12]
        name = f"id_{self.worker_id}_{digest}.hqln"
        path = os.path.join(self.corpus_dir, name)
        if name not in self._known_corpus_files and not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
        self._known_corpus_files.add(name)

    def _record_crash(self, data: bytes, outcome: Outcome) -> None:
        fp = outcome.fingerprint or "unknown"
        count = self.samples_per_fp.get(fp, 0)
        if count >= MAX_SAVED_SAMPLES_PER_FP:
            return
        digest = hashlib.sha1(data).hexdigest()[:12]
        name = f"crash_{self.worker_id}_{count}_{digest}.hqln"
        path = os.path.join(self.crashes_dir, name)
        with open(path, "wb") as f:
            f.write(data)
        self.samples_per_fp[fp] = count + 1
        if fp not in self.crashes:
            self.crashes[fp] = Crash(
                id=f"{outcome.crash_kind}-{fp[:10]}",
                fingerprint=fp,
                exception=outcome.exception or outcome.crash_kind or "unknown",
                kind=outcome.crash_kind or "exception",
                input=path,
                replay=_replay_command(path),
            )

    def _evaluate(self, data: bytes, record_crashes: bool = True) -> Outcome:
        self.tracer.lines.clear()
        self.tracer.edges.clear()
        outcome = run_one(data, self.args.timeout, self.rss_bytes, self.tracer)
        self.executions += 1
        new_lines = self.tracer.lines - self.global_lines
        new_edges = self.tracer.edges - self.global_edges
        if new_lines or new_edges:
            self.global_lines |= self.tracer.lines
            self.global_edges |= self.tracer.edges
            self.corpus.append(data)
            self.favored.append(data)
            if len(self.favored) > 64:
                self.favored.pop(0)
            self._save_corpus(data)
        if outcome.kind == "crash" and record_crashes:
            self._record_crash(data, outcome)
        return outcome

    def _load_seeds(self) -> None:
        seed_dir = self.args.seed_dir
        for name in sorted(os.listdir(seed_dir)):
            path = os.path.join(seed_dir, name)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as f:
                data = f.read()
            outcome = self._evaluate(data)
            if outcome.kind == "reject":
                print(f"warning: seed {path} was rejected by the decoder", file=sys.stderr)
            # Always keep seeds in the corpus, even if they add no new coverage.
            if data not in self.corpus:
                self.corpus.append(data)
                self._save_corpus(data)

    def _pick_up_shared_corpus(self) -> None:
        """Pull in corpus files written by sibling workers (jobs > 1)."""
        try:
            names = os.listdir(self.corpus_dir)
        except OSError:
            return
        for name in names:
            if name in self._known_corpus_files or not name.endswith(".hqln"):
                continue
            self._known_corpus_files.add(name)
            path = os.path.join(self.corpus_dir, name)
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if data and data not in self.corpus:
                self.corpus.append(data)
                self._evaluate(data, record_crashes=False)

    def run(self) -> WorkerResult:
        started = time.monotonic()
        deadline = started + self.args.max_time
        self._load_seeds()
        if not self.corpus:
            print("error: no usable seeds to fuzz", file=sys.stderr)
            return WorkerResult(executions=self.executions)
        while time.monotonic() < deadline:
            if self.favored and self.rng.random() < 0.7:
                base = self.rng.choice(self.favored)
            else:
                base = self.rng.choice(self.corpus)
            data = self.mutator.mutate(base, self.corpus)
            self._evaluate(data)
            if self.executions % 256 == 0 and self.args.jobs > 1:
                self._pick_up_shared_corpus()
        return WorkerResult(
            executions=self.executions,
            elapsed=time.monotonic() - started,
            lines=set(self.global_lines),
            crashes=list(self.crashes.values()),
        )


def _worker_entry(args, worker_id: int) -> None:
    signal.signal(signal.SIGALRM, _alarm_handler)
    result = FuzzWorker(args, worker_id).run()
    path = os.path.join(os.path.abspath(args.out_dir), f".worker-{worker_id}.pkl")
    with open(path, "wb") as f:
        pickle.dump(result, f)


def _validate(args) -> str | None:
    if not os.path.isdir(args.seed_dir):
        return f"seed directory does not exist: {args.seed_dir}"
    if not any(os.path.isfile(os.path.join(args.seed_dir, n)) for n in os.listdir(args.seed_dir)):
        return f"seed directory has no files: {args.seed_dir}"
    if args.dict_path and not os.path.isfile(args.dict_path):
        return f"dictionary file does not exist: {args.dict_path}"
    if args.max_time <= 0:
        return "--max-time must be positive"
    if args.timeout <= 0:
        return "--timeout must be positive"
    if args.rss_mb < 16:
        return "--rss-mb must be at least 16"
    if args.jobs < 1:
        return "--jobs must be at least 1"
    try:
        os.makedirs(os.path.join(os.path.abspath(args.out_dir), "corpus"), exist_ok=True)
        os.makedirs(os.path.join(os.path.abspath(args.out_dir), "crashes"), exist_ok=True)
    except OSError as e:
        return f"cannot create output directory {args.out_dir}: {e}"
    report = args.report or os.path.join(os.path.abspath(args.out_dir), "report.json")
    try:
        with open(report, "w") as f:
            f.write("")
    except OSError as e:
        return f"cannot write report to {report}: {e}"
    return None


def _build_report(args, results: list[WorkerResult], elapsed: float) -> dict:
    out_dir = os.path.abspath(args.out_dir)
    total_lines = total_executable_lines()
    hit_lines: set = set()
    for r in results:
        hit_lines |= r.lines
    hit = len(hit_lines & total_lines)
    total = len(total_lines)
    crashes: dict[str, Crash] = {}
    for r in results:
        for c in r.crashes:
            crashes.setdefault(c.fingerprint, c)
    try:
        corpus_size = len([n for n in os.listdir(os.path.join(out_dir, "corpus")) if n.endswith(".hqln")])
    except OSError:
        corpus_size = 0
    crash_list = [
        {
            "id": c.id,
            "fingerprint": c.fingerprint,
            "exception": c.exception,
            "input": c.input,
            "replay": c.replay,
        }
        for c in sorted(crashes.values(), key=lambda c: c.id)
    ]
    return {
        "seed_dir": os.path.abspath(args.seed_dir),
        "out_dir": out_dir,
        "elapsed_sec": round(elapsed, 3),
        "executions": sum(r.executions for r in results),
        "corpus_size": corpus_size,
        "coverage": {
            "unit": "lines",
            "hit": hit,
            "total": total,
            "percent": round(100.0 * hit / total, 2) if total else 0.0,
        },
        "unique_crashes": len(crash_list),
        "crashes": crash_list,
    }


def run_fuzz(args) -> int:
    error = _validate(args)
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    report_path = args.report or os.path.join(os.path.abspath(args.out_dir), "report.json")
    started = time.monotonic()
    results: list[WorkerResult] = []
    try:
        if args.jobs == 1:
            signal.signal(signal.SIGALRM, _alarm_handler)
            results.append(FuzzWorker(args, 0).run())
        else:
            import multiprocessing as mp

            ctx = mp.get_context("fork")
            procs = [
                ctx.Process(target=_worker_entry, args=(args, i))
                for i in range(args.jobs)
            ]
            for p in procs:
                p.start()
            for p in procs:
                p.join(timeout=args.max_time + 30)
                if p.is_alive():
                    p.terminate()
                    p.join()
            out_dir = os.path.abspath(args.out_dir)
            for i in range(args.jobs):
                pkl = os.path.join(out_dir, f".worker-{i}.pkl")
                if os.path.exists(pkl):
                    with open(pkl, "rb") as f:
                        results.append(pickle.load(f))
                    os.unlink(pkl)
    finally:
        elapsed = time.monotonic() - started
        report = _build_report(args, results, elapsed)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
    print(
        f"done: {report['executions']} executions, corpus={report['corpus_size']}, "
        f"coverage={report['coverage']['hit']}/{report['coverage']['total']} lines "
        f"({report['coverage']['percent']}%), unique_crashes={report['unique_crashes']}"
    )
    print(f"report: {report_path}")
    return 0
