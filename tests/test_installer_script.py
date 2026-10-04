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
