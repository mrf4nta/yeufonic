#!/bin/sh
# Fetch the models into ./models, about 17 GB:
#
#   checkpoints/yue2_3b_bf16.safetensors                 YuE2, plans and renders       7.8 GB
#   audio_encoders/sheetsage2_bf16.safetensors           SheetSage2, transcription      1.4 GB
#   text_encoders/gemma4_e4b_it_int8_convrot.safetensors Gemma 4 E4B, lyric drafts      8.1 GB
#   loras/ar_lora_inst_v3abc_comfyui.safetensors         instrumental LoRA              0.2 GB
#   loras/nar_lora_joint_v9_comfyui.safetensors          Realaudio decoder LoRA         0.1 GB
#   audio_encoders/tokenizer_head_joint_v9.safetensors   Realaudio tokenizer head       0.2 GB
#   data/models/soundfonts/sf2/github_Jnsgm2.sf2         Jnsgm2 SoundFont                33 MB
#   data/models/soundfonts/sf2/Arachno_SoundFont...sf2   Arachno SoundFont 1.0          149 MB
#
#   sh scripts/fetch-models.sh
#
# A file that is already there is kept, and an interrupted download resumes.
# It also creates data/ and engine-state/output/, which the app needs to own, and
# records your user and group ids in .env for compose.yml to run the app as.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
YUE2=https://huggingface.co/Comfy-Org/YuE2/resolve/main
GEMMA=https://huggingface.co/Comfy-Org/gemma-4/resolve/main
INSTRUMENTAL=https://huggingface.co/Mothersuperior/YuE2-instrumental-cot-full-loras/resolve/main
REAL_AUDIO=https://huggingface.co/Mothersuperior/yue2-mothersuperior-realaudio-tokenizer-v4/resolve/main
REGULARIZER=https://huggingface.co/Mothersuperior/YuE2-hum-to-song/resolve/main

mkdir -p "$ROOT/models/checkpoints" "$ROOT/models/audio_encoders" "$ROOT/models/text_encoders" "$ROOT/models/loras" "$ROOT/models/fs_audio"
# The folders compose.yml mounts into the app.  Created here, as you, because a
# folder Docker creates for a mount belongs to root, and the app cannot write to it.
mkdir -p "$ROOT/data" "$ROOT/data/models/soundfonts/sf2" "$ROOT/engine-state/output"
# The app runs as APP_UID:APP_GID, 1000:1000 unless set, and what it writes belongs
# to those ids. Compose reads .env beside compose.yml, so record whoever is setting
# this up, once. Linux only: Docker Desktop maps ownership itself, and root is
# not someone the app should run as.
if [ "$(uname -s)" = Linux ] && [ "$(id -u)" != 0 ] && ! grep -qs '^APP_UID=' "$ROOT/.env"; then
  if [ -s "$ROOT/.env" ] && [ -n "$(tail -c 1 "$ROOT/.env")" ]; then echo >> "$ROOT/.env"; fi
  printf 'APP_UID=%s\nAPP_GID=%s\n' "$(id -u)" "$(id -g)" >> "$ROOT/.env"
  echo "wrote APP_UID=$(id -u) and APP_GID=$(id -g) to .env"
fi

fetch() {
  url="$1"; dest="$2"
  if [ -s "$dest" ]; then
    echo "have  $(basename "$dest")"
    return 0
  fi
  echo "fetch $(basename "$dest")"
  curl -L --fail --retry 5 --retry-all-errors -C - -o "$dest.part" "$url"
  mv "$dest.part" "$dest"
}

fetch "$YUE2/checkpoints/yue2_3b_bf16.safetensors" \
      "$ROOT/models/checkpoints/yue2_3b_bf16.safetensors"

fetch "$YUE2/audio_encoders/sheetsage2_bf16.safetensors" \
      "$ROOT/models/audio_encoders/sheetsage2_bf16.safetensors"

fetch "$GEMMA/text_encoders/gemma4_e4b_it_int8_convrot.safetensors" \
      "$ROOT/models/text_encoders/gemma4_e4b_it_int8_convrot.safetensors"

fetch "$INSTRUMENTAL/ar_lora_inst_v3abc_comfyui.safetensors" \
      "$ROOT/models/loras/ar_lora_inst_v3abc_comfyui.safetensors"

fetch "$REAL_AUDIO/nar_lora_joint_v9_comfyui.safetensors" \
      "$ROOT/models/loras/nar_lora_joint_v9_comfyui.safetensors"

fetch "$REAL_AUDIO/tokenizer_head_joint_v9.safetensors" \
      "$ROOT/models/audio_encoders/tokenizer_head_joint_v9.safetensors"

fetch "$REGULARIZER/minted_regularizer_pack_v2.pt" \
      "$ROOT/models/fs_audio/minted_regularizer_pack_v2.pt"

SF2_DIR="$ROOT/data/models/soundfonts/sf2"
fetch "https://raw.githubusercontent.com/wrightflyer/SF2_SoundFonts/master/Jnsgm2.sf2" \
      "$SF2_DIR/github_Jnsgm2.sf2"

fetch "https://archive.org/download/free-soundfonts-sf2-2019-04/Arachno_SoundFont_Version_1.0.sf2" \
      "$SF2_DIR/Arachno_SoundFont_Version_1.0.sf2"

echo "done.  models/ now holds:"
ls -la "$ROOT/models/checkpoints" "$ROOT/models/audio_encoders" "$ROOT/models/text_encoders" "$ROOT/models/loras" "$ROOT/models/fs_audio" | grep -v '^total' | grep -v '^d'
echo ""
echo "soundfonts/sf2/ now holds:"
ls -la "$SF2_DIR" | grep -v '^total' | grep -v '^d'
