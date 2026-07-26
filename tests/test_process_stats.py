import pytest

from process_stats import ProcessSampler


class ManualClock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def process(pid, name, cpu_seconds, memory_bytes, *, started_at=1.0, username="root"):
    return {
        "pid": pid,
        "name": name,
        "username": username,
        "cpu_seconds": cpu_seconds,
        "memory_bytes": memory_bytes,
        "started_at": started_at,
    }


def make_sampler(passes, clock):
    frames = iter(passes)
    last = [passes[-1]]

    def reader():
        try:
            last[0] = next(frames)
        except StopIteration:
            pass
        return list(last[0])

    return ProcessSampler(process_reader=reader, clock=clock, ttl_seconds=0.0), reader


def test_first_pass_has_no_cpu_reading_and_second_derives_it():
    clock = ManualClock()
    sampler, _ = make_sampler(
        [
            [process(1, "ffmpeg", cpu_seconds=10.0, memory_bytes=100)],
            [process(1, "ffmpeg", cpu_seconds=15.0, memory_bytes=100)],
        ],
        clock,
    )

    assert sampler.sample()[0]["cpu_percent"] is None

    clock.advance(10.0)
    # 5 CPU-seconds over 10 wall seconds is half a core.
    assert sampler.sample()[0]["cpu_percent"] == pytest.approx(50.0)


def test_recycled_pid_waits_for_a_fresh_baseline():
    clock = ManualClock()
    sampler, _ = make_sampler(
        [
            [process(7, "old", cpu_seconds=90.0, memory_bytes=10, started_at=1.0)],
            [process(7, "new", cpu_seconds=1.0, memory_bytes=10, started_at=500.0)],
        ],
        clock,
    )

    sampler.sample()
    clock.advance(5.0)
    assert sampler.sample()[0]["cpu_percent"] is None


def test_top_ranks_separately_by_cpu_and_memory():
    clock = ManualClock()
    frame_one = [
        process(1, "ffmpeg", cpu_seconds=0.0, memory_bytes=200),
        process(2, "postgres", cpu_seconds=0.0, memory_bytes=900),
        process(3, "idle", cpu_seconds=0.0, memory_bytes=50),
    ]
    frame_two = [
        process(1, "ffmpeg", cpu_seconds=8.0, memory_bytes=200),
        process(2, "postgres", cpu_seconds=1.0, memory_bytes=900),
        process(3, "idle", cpu_seconds=0.0, memory_bytes=50),
    ]
    sampler, _ = make_sampler([frame_one, frame_two], clock)

    sampler.sample()
    clock.advance(10.0)
    result = sampler.top(limit=2)

    assert [item["name"] for item in result["by_cpu"]] == ["ffmpeg", "postgres"]
    assert [item["name"] for item in result["by_memory"]] == ["postgres", "ffmpeg"]
    assert result["total"] == 3


def test_idle_processes_are_left_out_of_the_cpu_ranking():
    clock = ManualClock()
    sampler, _ = make_sampler(
        [
            [process(1, "sleeper", cpu_seconds=4.0, memory_bytes=10)],
            [process(1, "sleeper", cpu_seconds=4.0, memory_bytes=10)],
        ],
        clock,
    )
    sampler.sample()
    clock.advance(5.0)

    assert sampler.top(limit=5)["by_cpu"] == []


def test_results_are_cached_within_the_ttl():
    clock = ManualClock()
    calls = []

    def reader():
        calls.append(clock.now)
        return [process(1, "ffmpeg", cpu_seconds=1.0, memory_bytes=10)]

    sampler = ProcessSampler(process_reader=reader, clock=clock, ttl_seconds=5.0)
    sampler.top()
    sampler.top()
    assert len(calls) == 1

    clock.advance(6.0)
    sampler.top()
    assert len(calls) == 2
