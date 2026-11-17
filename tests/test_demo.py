from iiot_agent.cli import main


def test_demo_alarms_and_determinism(capsys):
    # An early injected fault reaches 7.1 mm/s within this short run.
    args = ["demo", "--steps", "80", "--fault-start", "-40"]
    main(args)
    first = capsys.readouterr().out
    main(args)
    assert first == capsys.readouterr().out
    assert "ALARM" in first and "Notification:" in first
    assert "Readings stored: 240" in first
    assert "Sources" in first and "time to alarm limit" in first


def test_default_run_warns_then_alarms(capsys):
    main(["demo"])
    out = capsys.readouterr().out
    assert "vibration WARN" in out and "vibration ALARM" in out
