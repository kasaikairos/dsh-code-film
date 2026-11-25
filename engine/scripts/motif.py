"""motif.py —— 第五轮配乐：同一句 5 音动机的两个编曲（原创，不用现成旋律）。

动机（大调五声、可哼）：0 4 7 9 7 —— do mi sol la sol，最后落回 la→sol 是“说话”的口气。
两个版本的**唯一主要编曲差异**：
  A 连贯版：中音区主奏（reed）把 5 个音完整说完；句尾由 horn 应答两音；压下前有起势、装订后有解决。
  B 克制版：同一句，前半句晚进 0.7s、后半句只留两音；应答交给高音区 pluck，并且放在“抽纸之后”；
            订钉一入画就收住（留白），把注意力还给画面。
"""
import numpy as np

SR = 44100
MOTIF = [0, 4, 7, 9, 7]          # 五声音阶级数（大调）
SCALE = [0, 2, 4, 7, 9]


def _midi(tonic, degree, octave=0):
    return tonic + SCALE[degree % 5] + 12 * (degree // 5) + 12 * octave


def _reed(mix, at, length, midi, level, attack=0.05):
    start = max(0, round(at * SR)); n = min(round(length * SR), len(mix) - start)
    if n < 2: return
    t = np.arange(n) / SR
    f = 440 * 2 ** ((midi - 69) / 12)
    ph = 2 * np.pi * f * t
    env = np.minimum(1, t / attack) * np.minimum(1, (n / SR - t) / 0.18)
    tone = np.sin(ph) + 0.30 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)
    mix[start:start + n] += level * env * tone


def _horn(mix, at, length, midi, level):
    start = max(0, round(at * SR)); n = min(round(length * SR), len(mix) - start)
    if n < 2: return
    t = np.arange(n) / SR
    f = 440 * 2 ** ((midi - 69) / 12)
    ph = 2 * np.pi * f * t
    env = np.minimum(1, t / 0.09) * np.minimum(1, (n / SR - t) / 0.26)
    tone = np.sin(ph) + 0.45 * np.sin(2 * ph) + 0.18 * np.sin(3 * ph) + 0.07 * np.sin(4 * ph)
    mix[start:start + n] += level * env * tone


def _pluck(mix, at, length, midi, level):
    start = max(0, round(at * SR)); n = min(round(length * SR), len(mix) - start)
    if n < 2: return
    t = np.arange(n) / SR
    f = 440 * 2 ** ((midi - 69) / 12)
    ph = 2 * np.pi * f * t
    env = np.minimum(1, t / 0.006) * np.exp(-t * 5.5)
    tone = np.sin(ph) + 0.25 * np.sin(2 * ph)
    mix[start:start + n] += level * env * tone


def _finish(mix, seconds):
    fade = min(len(mix), round(0.25 * SR))
    if fade: mix[-fade:] *= np.linspace(1, 0, fade)
    peak = float(np.max(np.abs(mix))) or 1.0
    return (0.85 * mix / max(peak, 0.45)).astype(np.float32)


def compose_A(seconds, bpm, seed, cues):
    """连贯版：动机完整说完；应答在句尾；压下前有起势，装订后有解决。"""
    rng = np.random.default_rng(seed)
    tonic = int(rng.choice([60, 62, 65]))
    mix = np.zeros(round(seconds * SR), dtype=np.float32)
    beat = 60.0 / bpm
    a = cues[0] if cues else {"t": 1.7, "pull": 3.9}
    press = float(a.get("time", a.get("t", 1.7))); pull = float(a.get("pull", press + 2.2))
    # 起势：动机前两音先作为“招呼”出现（不等动作）
    start = max(0.35, press - 2.4 * beat)
    for i, deg in enumerate(MOTIF[:2]):
        _reed(mix, start + i * beat, beat * 0.9, tonic + deg, 0.16)
    # 完整动机：跨过“压下”
    for i, deg in enumerate(MOTIF):
        _reed(mix, start + beat * (2 + i * 0.75), beat * 0.85, tonic + deg, 0.17)
    # 句尾应答：horn 两音（低声部，短）
    ans = start + beat * (2 + 4 * 0.75) + beat * 0.4
    _horn(mix, ans, beat * 1.6, _midi(tonic, 4, -1), 0.13)
    _horn(mix, ans + beat * 0.8, beat * 2.2, _midi(tonic, 0, -1), 0.12)
    # 装订后解决：动机最后一音在中音区停住
    _reed(mix, pull + beat * 0.3, beat * 2.6, _midi(tonic, 7), 0.14, attack=0.12)
    return _finish(mix, seconds)


def compose_B(seconds, bpm, seed, cues):
    """克制版：同一句，前半句晚进、后半句只剩两音；应答交给高音 pluck，且放在抽纸之后；
    订钉入画时收住（留白）。"""
    rng = np.random.default_rng(seed)
    tonic = int(rng.choice([60, 62, 65]))
    mix = np.zeros(round(seconds * SR), dtype=np.float32)
    beat = 60.0 / bpm
    a = cues[0] if cues else {"t": 1.7, "pull": 3.9}
    press = float(a.get("time", a.get("t", 1.7))); pull = float(a.get("pull", press + 2.2))
    # 前半句：晚 0.7s 进，只三音
    start = press - 1.1 * beat
    for i, deg in enumerate(MOTIF[:3]):
        _reed(mix, start + i * beat, beat * 0.7, tonic + deg, 0.13, attack=0.03)
    # 后半句：只两音（9、7），更短
    for i, deg in enumerate(MOTIF[3:]):
        _reed(mix, start + beat * (3.2 + i * 0.6), beat * 0.5, tonic + deg, 0.12, attack=0.03)
    # 应答：高音 pluck，放在抽纸之后（不是跟着动作起音）
    ans = pull + beat * 0.55
    _pluck(mix, ans, beat * 1.1, _midi(tonic, 9, 1), 0.10)
    _pluck(mix, ans + beat * 0.55, beat * 1.4, _midi(tonic, 7, 1), 0.09)
    # 订钉入画：收住，只留一个很轻的泛音尾巴
    tail = pull + beat * 1.6
    if tail < seconds:
        n = min(int(1.2 * SR), len(mix) - int(tail * SR))
        if n > 2:
            i = int(tail * SR)
            mix[i:i + n] *= np.linspace(1, 0, n) ** 1.5
    return _finish(mix, seconds)


def compose_phrases(seconds, bpm, cues):
    """User-authored phrases, anchored in seconds; note durations and offsets in beats."""
    beat = 60.0 / bpm
    mix = np.zeros(round(seconds * SR), dtype=np.float32)
    voices = {"reed": _reed, "horn": _horn, "pluck": _pluck}
    for cue in cues:
        if cue.get("kind") != "phrase":
            continue
        voice = voices[cue.get("voice", "reed")]
        pos = round((cue["time"] + beat * cue.get("offset_beats", 0)) * SR)
        for midi, beats in cue["notes"]:
            if not np.isfinite(beats) or beats <= 0:
                raise ValueError("note duration must be positive")
            n = max(1, round(beat * beats * SR))
            if midi is not None and pos < len(mix) and pos+n > 0:
                if not 0 <= midi <= 127:
                    raise ValueError("MIDI pitch outside 0..127")
                length = min(n, len(mix)-pos)
                note = np.zeros(length, dtype=np.float32)
                voice(note, 0, length/SR, midi, cue.get("level", 0.15))
                mix[max(pos,0):pos+length] += note[max(-pos,0):]
            pos += n
    return _finish(mix, seconds)
