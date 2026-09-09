// Playback boundaries shared by timeupdate and ended, including the final clip.
export type PlayWindow={start:number;end?:number;loop?:boolean};
export type Playhead={currentTime:number;ended:boolean;pause:()=>void;play:()=>Promise<void>};
export function finishWindow(audio:Playhead,window:PlayWindow,onError:()=>void){
 if(window.end===undefined||(!audio.ended&&audio.currentTime<window.end))return;
 if(window.loop){audio.currentTime=window.start;void audio.play().catch(onError)}
 else{audio.pause();window.end=undefined}
}
// 最后更新：2026-09-09 · Astra
