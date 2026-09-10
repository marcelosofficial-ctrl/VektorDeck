from vektordeck.preflight import assess_idle_baseline


def sample(cpu: float, ram: float, gpu: float) -> dict:
    return {
        "cpu": {"utilization_percent": cpu},
        "memory": {"percent": ram},
        "gpu": {"utilization_percent": gpu},
    }


def test_quiet_baseline_is_ready() -> None:
    result = assess_idle_baseline([sample(22, 40, 15), sample(28, 41, 18), sample(25, 40, 17)])
    assert result["ready"] is True
    assert result["reasons"] == []


def test_busy_cpu_blocks_optimizer() -> None:
    result = assess_idle_baseline([sample(84, 40, 20), sample(86, 41, 22), sample(85, 40, 21)])
    assert result["ready"] is False
    assert any("background CPU averaged" in reason for reason in result["reasons"])


def test_high_baseline_ram_blocks_optimizer() -> None:
    result = assess_idle_baseline([sample(20, 75, 15), sample(25, 76, 16), sample(22, 74, 15)])
    assert result["ready"] is False
    assert any("baseline RAM averaged" in reason for reason in result["reasons"])
