"""FCP7 timeline from final delivery audio; sample positions remain authoritative."""
from pathlib import PurePosixPath
from urllib.parse import quote
import xml.etree.ElementTree as ET

FPS_CHOICES = (24, 25, 30, 50, 60)


def frame(sample: int, sample_rate: int, fps: int) -> int:
    """Round an absolute nonnegative sample position, with exact half ties up."""
    return (2 * sample * fps + sample_rate) // (2 * sample_rate)


def clip_name(text: str) -> str:
    clean = ''.join(c for c in text if c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
    return clean if len(clean) <= 120 else clean[:119] + '…'


def timeline_xml(manifest: dict, fps: int = 30) -> bytes:
    if type(fps) is not int or fps not in FPS_CHOICES:
        raise ValueError('视频项目帧率请选择 24、25、30、50 或 60')
    rate = manifest['sample_rate']
    def add(parent, name, value=None):
        child = ET.SubElement(parent, name)
        if value is not None:
            child.text = str(value)
        return child
    def framerate(parent):
        node = add(parent, 'rate')
        add(node, 'timebase', fps)
        add(node, 'ntsc', 'FALSE')
    root = ET.Element('xmeml', version='5')
    seq = add(root, 'sequence')
    seq.set('id', f'voxstage-{fps}')
    add(seq, 'name', f'VoxStage {fps}fps')
    add(seq, 'duration', frame(manifest['total_samples'], rate, fps))
    framerate(seq)
    tc = add(seq, 'timecode')
    framerate(tc)
    add(tc, 'string', '00:00:00:00')
    add(tc, 'frame', 0)
    add(tc, 'displayformat', 'NDF')
    media = add(seq, 'media')
    video = add(media, 'video')
    sc = add(add(video, 'format'), 'samplecharacteristics')
    framerate(sc)
    for key, value in [('width', 1920), ('height', 1080), ('pixelaspectratio', 'square'), ('fielddominance', 'none')]:
        add(sc, key, value)
    audio = add(media, 'audio')
    add(audio, 'numOutputChannels', 1)
    sc = add(add(audio, 'format'), 'samplecharacteristics')
    add(sc, 'depth', 16)
    add(sc, 'samplerate', rate)
    track = add(audio, 'track')
    for row in manifest['segments']:
        relative = PurePosixPath(row['file'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in row['file']:
            raise ValueError('交付包音频路径必须是相对路径')
        start = frame(row['start_sample'], rate, fps)
        end = frame(row['end_sample'], rate, fps)
        if end <= start:
            raise ValueError(f'第 {row["index"]} 句太短，无法在所选帧率下保留为独立片段；可使用 WAV 或剪辑交付包')
        source_frames = (row['samples'] * fps + rate - 1) // rate
        clip = add(track, 'clipitem')
        clip.set('id', f'clip-{row["index"]}')
        add(clip, 'name', clip_name(row['text']))
        add(clip, 'enabled', 'TRUE')
        framerate(clip)
        for key, value in [('duration', source_frames), ('start', start), ('end', end), ('in', 0), ('out', end-start)]:
            add(clip, key, value)
        file = add(clip, 'file')
        file.set('id', f'file-{row["index"]}')
        add(file, 'name', relative.name)
        add(file, 'pathurl', quote('delivery/' + relative.as_posix(), safe='/'))
        framerate(file)
        add(file, 'duration', source_frames)
        fa = add(add(file, 'media'), 'audio')
        sc = add(fa, 'samplecharacteristics')
        add(sc, 'depth', 16)
        add(sc, 'samplerate', rate)
        add(fa, 'channelcount', 1)
        st = add(clip, 'sourcetrack')
        add(st, 'mediatype', 'audio')
        add(st, 'trackindex', 1)
    add(track, 'enabled', 'TRUE')
    add(track, 'locked', 'FALSE')
    ET.indent(root)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


IMPORT_GUIDE = """VoxStage 剪辑时间轴导入说明

1. 同一次导出中下载 XML 和剪辑交付包（ZIP），将 ZIP 解压。
   把 XML 放在解压后的 delivery 文件夹旁边。文件可整体搬走或改名。
   不要把旧版 ZIP 与重新编辑后导出的 XML 混用。
2. 在 DaVinci Resolve 中选择 File → Import → Timeline，选择 XML。
   导入对话框确认帧率与自己的视频项目一致、起始时间码为 00:00:00:00。
3. 如果提示找不到媒体，选择 Yes，然后在文件夹目录树里选中
   delivery/audio，再点 OK。文件选择器的路径显示栏不一定能输入路径。
   Resolve 可能要求手动重新定位；XML 使用相对路径，不记录你的电脑路径。
4. 句级字幕需单独下载，使用 File → Import → Subtitle 导入 SRT。

Resolve 在时间线上显示的是音频文件名，不是 XML 里的片段名称字段
（21.0.4 实测，改写 XML 的名称字段无效）。因此交付包的文件名本身
已带上该句台词，形如 0004_林小雪_应该就是这儿.wav，过长时按字节截断。
XML 的片段名称字段同样写入台词，供其他软件使用。声音来自交付包中的成品，
保留已应用的语速、精细剪辑和句间停顿，不会重新生成声音。
XML 时间单位是视频帧，各句起止点独立取整到最近帧；可能产生半帧以内的
边界偏移，片段时长或间隙也会随边界取整而变化。原 WAV 与交付包中的
JSON/CSV 仍按采样记录，零采样复原约定适用于交付包，不适用于 XML。
目前支持整数帧率 24、25、30、50、60。小于一帧并被取整成零长度的片段
会阻止 XML 导出，可继续使用 WAV 或剪辑交付包。
其他剪辑软件、非整数帧率和导入后的最终渲染须另行验证。
"""

# 最后更新：2026-09-11 · Astra
