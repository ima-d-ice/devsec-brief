import os
import platform
import shutil
from pathlib import Path
from sentence_transformers import SentenceTransformer
from sentence_transformers.backend.quantize import export_dynamic_quantized_onnx_model
from src.logger import get_logger

logger = get_logger(__name__)

tmp_dir = Path(__file__).resolve().parents[1] / "data" / "onnx_tmp"
tmp_dir.mkdir(parents=True, exist_ok=True)
os.environ["TMPDIR"] = str(tmp_dir)
os.environ["TEMP"] = str(tmp_dir)
os.environ["TMP"] = str(tmp_dir)

def _quant_config() -> str:
    """Pick quantization config based on host arch — arm64 vs x86."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    # x86 fallback: use avx2 if available, else arm64 still works but slower
    return "avx2" if machine in ("x86_64", "amd64") else "arm64"

def main():
    onnx_dir = Path(__file__).resolve().parents[1] / "data" / "onnx_st"
    onnx_dir.mkdir(parents=True, exist_ok=True)
    
    embed_path = onnx_dir / "bge-m3-onnx"
    quant_cfg = _quant_config()
    if not embed_path.exists():
        logger.info("onnx_export_start", extra={"model": "BAAI/bge-m3", "quant": quant_cfg})
        pt_model = SentenceTransformer(
            "BAAI/bge-m3",
            processor_kwargs={"fix_mistral_regex": True}
        )
        pt_model.save("tmp_bge_m3")
        
        logger.info("onnx_loading_local")
        model = SentenceTransformer(
            "tmp_bge_m3", 
            backend="onnx",
            processor_kwargs={"fix_mistral_regex": True}
        )
        
        logger.info("onnx_quantizing", extra={"quant": quant_cfg})
        export_dynamic_quantized_onnx_model(
            model,
            quantization_config=quant_cfg,
            model_name_or_path=str(embed_path),
        )
        logger.info("onnx_export_done", extra={"path": str(embed_path), "quant": quant_cfg})
        
        shutil.rmtree("tmp_bge_m3", ignore_errors=True)
    else:
        logger.info("onnx_exists", extra={"path": str(embed_path)})
        
    rerank_path = onnx_dir / "mmarco-onnx"
    if not rerank_path.exists():
        logger.info("onnx_export_start", extra={"model": "mmarco", "quant": quant_cfg})
        try:
            from sentence_transformers.cross_encoder import CrossEncoder
            
            pt_model = CrossEncoder(
            "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
            processor_kwargs={"fix_mistral_regex": True}
        )
            pt_model.save("tmp_mmarco")
            model = CrossEncoder(
            "tmp_mmarco", 
            backend="onnx",
            processor_kwargs={"fix_mistral_regex": True}
        )
            
            export_dynamic_quantized_onnx_model(
                model, 
                quantization_config=quant_cfg,
                model_name_or_path=str(rerank_path),
            )
            logger.info("onnx_export_done", extra={"path": str(rerank_path), "quant": quant_cfg})
            shutil.rmtree("tmp_mmarco", ignore_errors=True)
        except Exception as e:
            logger.warning("onnx_export_failed", extra={"error": str(e)[:300]})
            logger.info("onnx_fallback_optimum", extra={"quant": quant_cfg})
            os.system(f"optimum-cli export onnx --model cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 --task text-classification --optimize O3 --quantize {quant_cfg} {str(rerank_path)}")
    else:
        logger.info("onnx_exists", extra={"path": str(rerank_path)})

    shutil.rmtree(tmp_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
