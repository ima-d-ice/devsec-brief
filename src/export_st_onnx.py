import os
import shutil
from pathlib import Path
from sentence_transformers import SentenceTransformer
from sentence_transformers.backend.quantize import export_dynamic_quantized_onnx_model

tmp_dir = Path(__file__).resolve().parents[1] / "data" / "onnx_tmp"
tmp_dir.mkdir(parents=True, exist_ok=True)
os.environ["TMPDIR"] = str(tmp_dir)
os.environ["TEMP"] = str(tmp_dir)
os.environ["TMP"] = str(tmp_dir)

# Overridable for sandboxed validation runs (keeps real output untouched).
ONNX_DIR = Path(os.getenv("ONNX_OUT_DIR", Path(__file__).resolve().parents[1] / "data" / "onnx_st"))

QUANTIZE_CONFIG = os.getenv("ONNX_QUANTIZE_CONFIG", "arm64")


def export_embedding(onnx_dir: Path):
    embed_path = onnx_dir / "bge-m3-onnx"
    if embed_path.exists():
        print(f"ONNX embedding model already exists at {embed_path}")
        return
    # Load straight from the Hub into the ONNX backend in one step.
    # (Previous save-to-tmp + reload round-trip broke on newer transformers:
    # AutoProcessor rejects the locally-saved dir.)
    print("Exporting BAAI/bge-m3 to ONNX...")
    model = SentenceTransformer(
        "BAAI/bge-m3",
        backend="onnx",
        processor_kwargs={"fix_mistral_regex": True},
    )

    print("Running ONNX INT8 Quantization...")
    export_dynamic_quantized_onnx_model(
        model,
        quantization_config=QUANTIZE_CONFIG,
        model_name_or_path=str(embed_path),
    )
    print(f"Embedding model successfully quantized and saved to {embed_path}")


def export_reranker(onnx_dir: Path):
    rerank_path = onnx_dir / "mmarco-onnx"
    if rerank_path.exists():
        print(f"ONNX reranker already exists at {rerank_path}")
        return
    print("Exporting mMARCO reranker to ONNX...")
    try:
        from sentence_transformers.cross_encoder import CrossEncoder

        model = CrossEncoder(
            "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
            backend="onnx",
            processor_kwargs={"fix_mistral_regex": True},
        )

        export_dynamic_quantized_onnx_model(
            model,
            quantization_config=QUANTIZE_CONFIG,
            model_name_or_path=str(rerank_path),
        )
        print(f"Reranker successfully quantized and saved to {rerank_path}")
    except Exception as e:
        print(f"Failed to export CrossEncoder via backend: {e}")
        print("Falling back to optimum-cli for CrossEncoder export...")
        ret = os.system(
            f"optimum-cli export onnx --model cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 "
            f"--task text-classification --optimize O3 --quantize {QUANTIZE_CONFIG} {str(rerank_path)}"
        )
        if ret != 0:
            raise RuntimeError(f"optimum-cli CrossEncoder export failed (exit {ret})")


def main():
    onnx_dir = ONNX_DIR
    onnx_dir.mkdir(parents=True, exist_ok=True)

    export_embedding(onnx_dir)
    export_reranker(onnx_dir)

    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
