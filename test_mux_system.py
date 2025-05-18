import subprocess


def test_mux_system_dry_run():
    """Test mux-system.py in dry-run mode."""
    result = subprocess.run(
        ["python3", "mux-system.py", "--dry-run", "1"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Dry-run failed: {result.stderr}"
    assert "Dry run for episode 01 completed" in result.stdout
