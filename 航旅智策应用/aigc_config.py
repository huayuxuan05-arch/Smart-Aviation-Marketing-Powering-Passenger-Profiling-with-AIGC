"""固定本地模型与CUDA运行时版本；不含凭据。"""
from data_layer import RUNTIME
import json
import os
from pathlib import Path
ROOT=RUNTIME/'local_aigc'
MODEL_NAME='Qwen3.5-4B-Q4_K_M'
BASE_REPOSITORY='https://huggingface.co/Qwen/Qwen3.5-4B'
REPOSITORY='https://huggingface.co/unsloth/Qwen3.5-4B-GGUF'
REVISION='e87f176479d0855a907a41277aca2f8ee7a09523'
MODEL_FILE='Qwen3.5-4B-Q4_K_M.gguf'
MODEL_SHA256='00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4'
MODEL_BYTES=2740937888
RUNTIME_VERSION='b11565'
RUNTIME_DIR='llama-cuda'
PORT=8767
ALIAS='aerolens-qwen3.5-4b'
LABEL='Qwen3.5-4B · Q4_K_M · 本地GPU'
FILES=[
 ('llama-b11565-bin-win-cuda-13.4-x64.zip','https://github.com/ggml-org/llama.cpp/releases/download/b11565/llama-b11565-bin-win-cuda-13.4-x64.zip','8293cc5ee4762576f6f5ac70e5cfae3928b5689870410daa4f83acd56c16b723',153446087),
 ('cudart-llama-bin-win-cuda-13.4-x64.zip','https://github.com/ggml-org/llama.cpp/releases/download/b11565/cudart-llama-bin-win-cuda-13.4-x64.zip','738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668',423535356),
 (MODEL_FILE,REPOSITORY+'/resolve/'+REVISION+'/'+MODEL_FILE,MODEL_SHA256,MODEL_BYTES),
]


def runtime_configuration():
    """Optional explicit local profile; published model/download constants stay fixed."""
    config={'root':ROOT,'model_file':MODEL_FILE,'model_name':MODEL_NAME,'revision':REVISION,
            'alias':ALIAS,'label':LABEL,'executable':ROOT/RUNTIME_DIR/'llama-server.exe',
            'backend':'CUDA13.4 / CUDA0','device':'CUDA0','bytes':MODEL_BYTES,'sha256':MODEL_SHA256}
    selected=os.environ.get('AEROLENS_LOCAL_MODEL_PROFILE')
    if selected:
        profile=json.loads(Path(selected).read_text(encoding='utf-8-sig'))
        required={'model_file','model_name','revision','alias','label','executable','backend','device','bytes','sha256'}
        if not required.issubset(profile):raise ValueError('本地模型配置不完整')
        if not Path(profile['model_file']).is_absolute() or not Path(profile['executable']).is_absolute():
            raise ValueError('复用模型须配置绝对路径')
        config.update({k:profile[k] for k in required})
    return config
