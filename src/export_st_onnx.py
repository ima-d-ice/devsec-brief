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

def main():
    onnx_dir = Path(__file__).resolve().parents[1] / "data" / "onnx_st"
    onnx_dir.mkdir(parents=True, exist_ok=True)
    
    embed_path = onnx_dir / "bge-m3-onnx"
    if not embed_path.exists():
        print("Exporting and quantizing BAAI/bge-m3 to ONNX...")
        pt_model = SentenceTransformer(
            "BAAI/bge-m3",
            processor_kwargs={"fix_mistral_regex": True}
        )
        pt_model.save("tmp_bge_m3")
        
        print("Loading local PyTorch model into ONNX backend...")
        model = SentenceTransformer(
            "tmp_bge_m3", 
            backend="onnx",
            processor_kwargs={"fix_mistral_regex": True}
        )
        
        print("Running ONNX INT8 Quantization...")
        export_dynamic_quantized_onnx_model(
            model,
            quantization_config="arm64",
            model_name_or_path=str(embed_path),
        )
        print(f"Embedding model successfully quantized and saved to {embed_path}")
        
        shutil.rmtree("tmp_bge_m3", ignore_errors=True)
    else:
        print(f"ONNX embedding model already exists at {embed_path}")
        
    rerank_path = onnx_dir / "mmarco-onnx"
    if not rerank_path.exists():
        print("Exporting and quantizing mMARCO reranker to ONNX...")
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
                quantization_config="arm64",
                model_name_or_path=str(rerank_path),
            )
            print(f"Reranker successfully quantized and saved to {rerank_path}")
            shutil.rmtree("tmp_mmarco", ignore_errors=True)
        except Exception as e:
            print(f"Failed to export CrossEncoder via backend: {e}")
            print("Falling back to optimum-cli for CrossEncoder export...")
            os.system(f"optimum-cli export onnx --model cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 --task text-classification --optimize O3 --quantize arm64 {str(rerank_path)}")
    else:
        print(f"ONNX reranker already exists at {rerank_path}")

    shutil.rmtree(tmp_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
