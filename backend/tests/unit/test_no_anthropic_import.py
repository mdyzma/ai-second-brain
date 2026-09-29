import subprocess
import sys

CHECK = """
import sys
import ai_second_brain.interfaces.api.app as app_module
import ai_second_brain.interfaces.cli.main
import ai_second_brain.chat.service
import ai_second_brain.chat.wiring
app_module.openapi_schema()
assert "anthropic" not in sys.modules, "private code paths imported the anthropic SDK"
print("ok")
"""


def test_private_code_paths_never_import_the_anthropic_sdk() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", CHECK], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
