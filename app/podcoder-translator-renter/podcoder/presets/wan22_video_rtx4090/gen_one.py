"""Wan 2.2 video - RTX 4090 preset: render ONE clip on the rented box via ComfyUI.

Env: SHOT (prompt key and <SHOT>.png keyframe in the job dir), SEED (optional).
Render: Wan 2.2 TI2V 5B, 704x1280, 121 frames @ 24 fps, 20 steps, uni_pc, cfg 5, shift 8.
Source: /workspace/simco-wan-or7/gen_one.py (Organics Raw run, 2026-10-30). No secrets.
"""
import json, time, urllib.request, urllib.error, os, shutil, sys, glob, subprocess
J=os.environ.get('PODCODER_JOB_DIR','/root/job'); C=os.environ.get('PODCODER_VIDEO_DEST','/root/simco')+'/ComfyUI'; SHOT=os.environ['SHOT']; SEED=int(os.environ.get('SEED','20261030'))
P=json.load(open(J+'/prompts.json'))
shutil.copy(f'{J}/{SHOT}.png', f'{C}/input/{SHOT}.png')
def req(path,data=None):
    r=urllib.request.Request('http://127.0.0.1:8188'+path,data=json.dumps(data).encode() if data else None,headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(r,timeout=60))
POS=P[SHOT]+", consistent character, natural motion, high detail"
NEG="色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走, text, watermark, morphing, duplicate objects"
wf={
"1":{"class_type":"UNETLoader","inputs":{"unet_name":"wan2.2_ti2v_5B_fp16.safetensors","weight_dtype":"default"}},
"2":{"class_type":"CLIPLoader","inputs":{"clip_name":"umt5_xxl_fp8_e4m3fn_scaled.safetensors","type":"wan"}},
"3":{"class_type":"VAELoader","inputs":{"vae_name":"wan2.2_vae.safetensors"}},
"4":{"class_type":"ModelSamplingSD3","inputs":{"model":["1",0],"shift":8.0}},
"5":{"class_type":"CLIPTextEncode","inputs":{"clip":["2",0],"text":POS}},
"6":{"class_type":"CLIPTextEncode","inputs":{"clip":["2",0],"text":NEG}},
"7":{"class_type":"LoadImage","inputs":{"image":f"{SHOT}.png"}},
"8":{"class_type":"Wan22ImageToVideoLatent","inputs":{"vae":["3",0],"width":704,"height":1280,"length":121,"batch_size":1,"start_image":["7",0]}},
"9":{"class_type":"KSampler","inputs":{"model":["4",0],"positive":["5",0],"negative":["6",0],"latent_image":["8",0],"seed":SEED,"steps":20,"cfg":5.0,"sampler_name":"uni_pc","scheduler":"simple","denoise":1.0}},
"10":{"class_type":"VAEDecode","inputs":{"samples":["9",0],"vae":["3",0]}},
"11":{"class_type":"CreateVideo","inputs":{"images":["10",0],"fps":24}},
"12":{"class_type":"SaveVideo","inputs":{"video":["11",0],"filename_prefix":f"video/{SHOT}","format":"auto","codec":"auto"}}}
try: pid=req('/prompt',{'prompt':wf})['prompt_id']
except urllib.error.HTTPError as e: print('PROMPT ERROR',e.read().decode()[:3000]); sys.exit(3)
t0=time.time(); print('queued',SHOT,pid,flush=True)
while True:
    time.sleep(30)
    h=req('/history/'+pid)
    tail=open('/root/comfy.log',errors='replace').read()[-300:].replace('\r','\n').strip().splitlines()
    print(f'[{SHOT} {int(time.time()-t0)}s] {tail[-1][-90:] if tail else ""}',flush=True)
    if pid in h:
        st=h[pid].get('status',{}); print('STATUS',json.dumps(st)[:600]); break
    if time.time()-t0>1500: print('GEN_TIMEOUT'); sys.exit(4)
fs=sorted(glob.glob(f'{C}/output/video/{SHOT}_*.mp4'))
if not fs: print(open('/root/comfy.log',errors='replace').read()[-2000:]); sys.exit(5)
shutil.copy(fs[-1],f'{J}/{SHOT}.mp4'); print(f'GEN_OK {SHOT} {time.time()-t0:.1f}s', os.path.getsize(f'{J}/{SHOT}.mp4'),flush=True)
