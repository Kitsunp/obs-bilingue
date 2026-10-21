from engine.launch import restart_reason
from engine.server import read_config


def test_silent_but_progressing_recognizer_is_not_restarted():
    health = {"ready": True, "recognizer_alive": True, "recognizer_progress_age_seconds": 0.2}
    assert restart_reason(health, 3600, 0, read_config()) is None


def test_stalled_and_dead_workers_trigger_recovery():
    config = read_config()
    stalled = {"ready": True, "recognizer_alive": True,
               "recognizer_progress_age_seconds": config["asr_stall_timeout_seconds"] + 1}
    assert restart_reason(stalled, 100, 0, config) == "recognizer_stalled"
    assert restart_reason({"ready": True, "recognizer_alive": False}, 100, 0, config) == "recognizer_stopped"


def test_startup_has_its_own_deadline_and_shutdown_is_not_a_crash():
    config = read_config()
    assert restart_reason({"ready": False}, 1, 0, config) is None
    assert restart_reason({"ready": False}, config["asr_startup_timeout_seconds"] + 1, 0, config)
    assert restart_reason({"stopping": True}, 999, 0, config) is None
    assert restart_reason(None, 999, config["asr_stall_timeout_seconds"] + 1, config, started_ready=True)


def test_ready_worker_hang_does_not_receive_startup_grace_again():
    config = read_config()
    assert restart_reason(None, 9, 11, config, started_ready=True) == "health_unavailable"
    assert restart_reason(None, 9, 11, config, started_ready=False) is None
