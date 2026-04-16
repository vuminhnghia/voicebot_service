#!/usr/bin/env python3
"""
Export parakeet-ctc-0.6b-vi sang ONNX.
Chạy bên ngoài Docker trong môi trường có NeMo.

Output:
  /opt/models/parakeet_asr/model.onnx
  /opt/models/parakeet_asr/vocab.json
  /opt/models/parakeet_asr/preprocessor_cfg.yaml
"""
import json
import os

import nemo.collections.asr as nemo_asr
from omegaconf import OmegaConf

OUTPUT_DIR = "/home/vumnghia/workdir/Research/Qwen_35_4B/opt/models/parakeet_asr"
MODEL_NAME = "nvidia/parakeet-ctc-0.6b-vi"

os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"[export] Loading {MODEL_NAME} ...")
model = nemo_asr.models.ASRModel.from_pretrained(model_name=MODEL_NAME)
model.eval()

# 1. Export acoustic model to ONNX
onnx_path = os.path.join(OUTPUT_DIR, "model.onnx")
print(f"[export] Exporting to {onnx_path} ...")
model.export(onnx_path, check_trace=False)

# 2. Save vocabulary for CTC decoding
vocab = list(model.decoder.vocabulary)
vocab_path = os.path.join(OUTPUT_DIR, "vocab.json")
with open(vocab_path, "w", encoding="utf-8") as f:
    json.dump(vocab, f, ensure_ascii=False, indent=2)
print(f"[export] Vocabulary saved ({len(vocab)} tokens)")

# 3. Save preprocessor config
preprocessor_cfg_path = os.path.join(OUTPUT_DIR, "preprocessor_cfg.yaml")
OmegaConf.save(model.cfg.preprocessor, preprocessor_cfg_path)
print(f"[export] Preprocessor config saved to {preprocessor_cfg_path}")

print("[export] Done.")
