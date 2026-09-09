"""Playback regressions: partial loops, final-clip loops and ordinary stop. Astra, 2026-09-09."""
from pathlib import Path
import subprocess


def test_selected_audio_window_and_loop(tmp_path):
    root=Path(__file__).resolve().parent.parent
    compiled=subprocess.run([str(root/'frontend/node_modules/.bin/tsc'),str(root/'frontend/src/playback.ts'),'--target','ES2022','--module','commonjs','--outDir',str(tmp_path),'--skipLibCheck'],capture_output=True,text=True)
    assert compiled.returncode==0,compiled.stdout+compiled.stderr
    script="""const a=require('node:assert/strict');const {finishWindow}=require('./playback.js');
    let plays=0,pauses=0,errors=0;const audio={currentTime:1,ended:false,pause:()=>pauses++,play:async()=>{plays++}};
    const window={start:1,end:2,loop:true};finishWindow(audio,window,()=>errors++);a.equal(plays,0);
    audio.currentTime=2.1;finishWindow(audio,window,()=>errors++);a.equal(audio.currentTime,1);a.equal(plays,1);a.equal(window.end,2);
    audio.ended=true;audio.currentTime=1.999999;finishWindow(audio,window,()=>errors++);a.equal(plays,2);a.equal(audio.currentTime,1);
    window.loop=false;finishWindow(audio,window,()=>errors++);a.equal(pauses,1);a.equal(window.end,undefined);
    finishWindow(audio,window,()=>errors++);a.equal(pauses,1);
    audio.play=async()=>{throw new Error('blocked')};window.end=2;window.loop=true;
    finishWindow(audio,window,()=>errors++);setImmediate(()=>a.equal(errors,1));
    """
    checked=subprocess.run(['node','-e',script],cwd=tmp_path,capture_output=True,text=True)
    assert checked.returncode==0,checked.stdout+checked.stderr

# 最后更新：2026-09-09 · Astra
