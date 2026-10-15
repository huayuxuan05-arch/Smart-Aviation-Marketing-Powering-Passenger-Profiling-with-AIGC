"""把Chromium真实录屏帧按原始时间戳编码，不伪造产品交互。"""
from pathlib import Path
import json
import subprocess
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'航旅智策应用/runtime/evidence'
QA=OUT/'qa'

def main():
    frames=json.loads((QA/'frames.json').read_text(encoding='utf-8'))
    if len(frames)<20:raise ValueError('Not enough real screencast frames')
    lines=[]
    total=0
    for i,frame in enumerate(frames):
        path=(QA/'frames'/frame['name']).resolve().as_posix()
        duration=max(.04,frames[i+1]['timestamp']-frame['timestamp']) if i+1<len(frames) else 2
        total+=duration
        lines.extend(["file '"+path.replace("'","'\\''")+"'",f'duration {duration:.6f}'])
    lines.append(lines[-2])
    playlist=QA/'capture.ffconcat'
    playlist.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    output=OUT/'航旅智策案例与实验操作展示.mp4'
    command=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','warning','-y','-safe','0','-f','concat','-i',str(playlist),
             '-vf','fps=20,scale=1280:880:force_original_aspect_ratio=decrease,pad=1280:880:(ow-iw)/2:(oh-ih)/2',
             '-c:v','libx264','-preset','fast','-crf','21','-pix_fmt','yuv420p','-movflags','+faststart',str(output)]
    subprocess.run(command,check=True)
    metadata={'duration_seconds_approx':round(total,2),'captured_frames':len(frames),
              'resolution':'1280x880','audio':False,'captions':'浏览器内演示说明字幕，非产品固定元素',
              'source':'Chromium CDP真实录屏帧 按原始时间戳编码',
              'bytes':output.stat().st_size,'synthetic_data':True}
    (OUT/'video-verification.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(metadata,ensure_ascii=False))

if __name__=='__main__':main()
