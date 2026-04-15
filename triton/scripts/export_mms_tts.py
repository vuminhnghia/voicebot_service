#!/usr/bin/env python3
"""
Export facebook/mms-tts-vie sang ONNX qua optimum.
Chạy bên ngoài Docker trong môi trường có optimum.

Cài trước:
    pip install "optimum[exporters]" transformers

Output:
  opt/models/mms_tts_vie/model.onnx
  opt/models/mms_tts_vie/tokenizer_config.json  (+ các tokenizer files)
"""
import os
from optimum.exporters.onnx import main_export
from transformers import AutoTokenizer

OUTPUT_DIR = "/home/vumnghia/workdir/Research/Qwen_35_4B/opt/models/mms_tts_vie"
MODEL_NAME = "facebook/mms-tts-vie"

os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"[export] Exporting {MODEL_NAME} -> ONNX ...")
main_export(
    model_name_or_path=MODEL_NAME,
    output=OUTPUT_DIR,
    task="text-to-audio",
    no_post_process=True,
    do_validation=False,  # VITS là stochastic nên shape thay đổi mỗi run, skip validation
)

# main_export không lưu tokenizer, save riêng
print("[export] Saving tokenizer ...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
tokenizer.save_pretrained(OUTPUT_DIR)

print(f"[export] Done. Files saved to {OUTPUT_DIR}")
