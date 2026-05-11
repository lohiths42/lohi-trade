"""
Download ProsusAI/finbert from HuggingFace and convert to ONNX format.

Saves the ONNX model and tokenizer to data/models/ for use with
ONNX Runtime (optimized for Apple Neural Engine via CoreML provider).

Requirements: 7.1, 7.2

Usage:
    python scripts/convert_finbert_onnx.py
"""

import os
import sys
from pathlib import Path

MODEL_NAME = "ProsusAI/finbert"
OUTPUT_DIR = Path("data/models")
ONNX_MODEL_PATH = OUTPUT_DIR / "finbert.onnx"


def download_and_convert() -> None:
    """Download FinBERT and export to ONNX format."""
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError:
        print(
            "ERROR: torch and transformers are required.\n"
            "  pip install torch transformers"
        )
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {MODEL_NAME} from HuggingFace...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    model.eval()

    # Save tokenizer for runtime use
    tokenizer.save_pretrained(str(OUTPUT_DIR / "finbert_tokenizer"))
    print("Tokenizer saved.")

    # Create dummy input for ONNX export
    dummy_text = "The company reported strong quarterly earnings."
    inputs = tokenizer(
        dummy_text,
        return_tensors="pt",
        max_length=512,
        truncation=True,
        padding="max_length",
    )

    print(f"Exporting model to ONNX: {ONNX_MODEL_PATH}")
    with torch.no_grad():
        torch.onnx.export(
            model,
            (inputs["input_ids"], inputs["attention_mask"]),
            str(ONNX_MODEL_PATH),
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "seq_len"},
                "attention_mask": {0: "batch", 1: "seq_len"},
                "logits": {0: "batch"},
            },
            opset_version=14,
        )

    size_mb = ONNX_MODEL_PATH.stat().st_size / (1024 * 1024)
    print(f"ONNX model saved ({size_mb:.1f} MB): {ONNX_MODEL_PATH}")
    print("Conversion complete.")


if __name__ == "__main__":
    download_and_convert()
