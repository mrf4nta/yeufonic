"""Things in the Windows installer script that went wrong once and are cheap to keep from coming back."""
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "windows" / "installer.nsi").read_text(encoding="utf-8")


def test_the_model_size_choice_does_not_use_the_radio_button_macros():
    """NSIS's StartRadioButtons takes a variable holding the previously chosen section and unticks that
    section first. With it unset it unticked the core section on the first click anywhere on the
    components page, so nothing was installed and setup failed. The two sizes are handled in
    .onSelChange by hand, touching only those two sections."""
    assert "StartRadioButtons" not in SCRIPT
    assert "Function .onSelChange" in SCRIPT
    assert "Var ModelRadio" in SCRIPT


def test_the_component_choice_is_set_up_before_the_page_is_shown():
    start = SCRIPT.index("Function .onInit")
    init = SCRIPT[start:SCRIPT.index("\nFunctionEnd", start)]
    assert "StrCpy $ModelRadio" in init


def test_both_installers_put_the_tokenizer_head_where_the_trainer_looks():
    """The trainer lists the head from models/fs_audio, the rest of the app reads it from audio_encoders. Without a
    copy in both, a fresh install refuses to train ("not in ['(run FS_Audio Training Assets first)']")."""
    root = Path(__file__).resolve().parent.parent
    windows = (root / "windows" / "setup.ps1").read_text(encoding="utf-8")
    docker = (root / "scripts" / "fetch-models.sh").read_text(encoding="utf-8")
    assert "tokenizer_head_joint_v9.safetensors" in windows and "'fs_audio'" in windows and "Copy-Item $headFrom $headTo" in windows
    assert "models/fs_audio/tokenizer_head_joint_v9.safetensors" in docker


def test_the_launcher_shows_a_dead_engine_once_not_on_every_tick():
    """fail() shows a message box from inside the half-second timer; the box runs its own message loop, so the
    timer fired again beneath it and stacked another box each time (126 in one failure)."""
    launcher = (Path(__file__).resolve().parent.parent / "windows" / "launcher.py").read_text(encoding="utf-8")
    body = launcher[launcher.index("    def stop_with("):launcher.index("    # ---------- the loop")]
    assert "self.quitting = True" in body and "KillTimer" in body
    assert body.index("self.quitting = True") < body.index("fail(text, log)")
    assert "if self.quitting:\n            return" in launcher[launcher.index("    def tick("):]


def test_extra_engine_switches_can_be_set_in_settings_ini():
    launcher = (Path(__file__).resolve().parent.parent / "windows" / "launcher.py").read_text(encoding="utf-8")
    assert '"engine_args": ""' in launcher and 'shlex.split(self.cfg.get("engine_args", ""))' in launcher


def test_the_windows_engine_gets_the_torch_the_docker_engine_uses():
    """The portable build for newer drivers brings torch 2.13 on CUDA 13, on which training either stopped the
    engine or ran several times slower than on the 2.9.1/CUDA 12.8 pair the Docker engine pins. The step is
    its own, keyed on the engine's mark, so an updated install is repaired and a re-unpacked engine is redone."""
    setup = (Path(__file__).resolve().parent.parent / "windows" / "setup.ps1").read_text(encoding="utf-8")
    dockerfile = (Path(__file__).resolve().parent.parent / "engine" / "Dockerfile").read_text(encoding="utf-8")
    block = setup[setup.index("if ($variant -eq 'cu130') {"):setup.index("$nodes = Join-Path")]
    assert "'torch==2.9.1', 'torchvision==0.24.1', 'torchaudio==2.9.1'" in block
    assert "https://download.pytorch.org/whl/cu128" in block
    assert '$torchMark = "torch-2.9.1-cu128-$engineMark"' in block
    assert 'torch==2.9.*' in dockerfile and "whl/cu128" in dockerfile
