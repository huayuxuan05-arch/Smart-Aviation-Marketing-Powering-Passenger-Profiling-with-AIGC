"""固定本地模型与CUDA运行时版本；不含凭据。"""
from data_layer import RUNTIME
ROOT=RUNTIME/'local_aigc'
MODEL_NAME='Qwen3.5-9B-Q4_K_M'
BASE_REPOSITORY='https://huggingface.co/Qwen/Qwen3.5-9B'
REPOSITORY='https://huggingface.co/unsloth/Qwen3.5-9B-GGUF'
REVISION='3885219b6810b007914f3a7950a8d1b469d598a5'
MODEL_FILE='Qwen3.5-9B-Q4_K_M.gguf'
MODEL_SHA256='03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8'
MODEL_BYTES=5680522464
RUNTIME_VERSION='b11565'
RUNTIME_DIR='llama-cuda'
PORT=8767
ALIAS='aerolens-qwen3.5-9b'
LABEL='Qwen3.5-9B · Q4_K_M · 本地GPU'
FILES=[
 ('llama-b11565-bin-win-cuda-13.4-x64.zip','https://github.com/ggml-org/llama.cpp/releases/download/b11565/llama-b11565-bin-win-cuda-13.4-x64.zip','8293cc5ee4762576f6f5ac70e5cfae3928b5689870410daa4f83acd56c16b723',153446087),
 ('cudart-llama-bin-win-cuda-13.4-x64.zip','https://github.com/ggml-org/llama.cpp/releases/download/b11565/cudart-llama-bin-win-cuda-13.4-x64.zip','738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668',423535356),
 (MODEL_FILE,REPOSITORY+'/resolve/'+REVISION+'/'+MODEL_FILE,MODEL_SHA256,MODEL_BYTES),
]
