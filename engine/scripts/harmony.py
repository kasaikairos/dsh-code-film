"""Least-cost triad voicings over the authored melody, split by rests."""
from itertools import permutations
import math

def harmonize(cues):
    result = []
    for cue in cues:
        if cue.get("kind") != "phrase":
            continue
        result.append(cue)
        run = []
        elapsed = 0
        def emit():
            if not run:
                return
            layers = []
            costs = {}
            for pitch, beats in run:
                current, parents = {}, {}
                transitions = {}
                for root in range(12):
                    for third in (3, 4):
                        chord = (root, (root+third)%12, (root+7)%12)
                        distance = min(min((pitch-n)%12,(n-pitch)%12) for n in chord)
                        for low, high in permutations(chord, 2):
                            bass = 43 + (low-43)%12
                            inner = 51 + (high-51)%12
                            if bass >= inner or inner >= pitch:
                                continue
                            state = (bass, inner)
                            local = beats*(2*distance + (root != low)*0.3)
                            if state not in transitions:
                                transitions[state] = min(costs, key=lambda v: costs[v]+abs(v[0]-bass)+abs(v[1]-inner)) if costs else None
                            previous = transitions[state]
                            total = local + (costs[previous]+sum(abs(a-b) for a,b in zip(previous,state)) if previous else 0)
                            if total < current.get(state, math.inf):
                                current[state], parents[state] = total, previous
                if not current:
                    return
                layers.append(parents)
                costs = current
            state = min(costs, key=costs.get)
            path = []
            for parents in reversed(layers):
                path.append(state)
                state = parents[state]
            path.reverse()
            for j, voice in enumerate(("horn","reed")):
                notes = []
                for state, (_, beats) in zip(path,run):
                    if notes and notes[-1][0] == state[j]:
                        notes[-1][1] += beats
                    else:
                        notes.append([state[j],beats])
                result.append(dict(cue, voice=voice, level=0.05, notes=notes,
                    offset_beats=cue.get("offset_beats",0)+elapsed-sum(b for _,b in run)))
        for pitch, beats in cue["notes"]:
            if not math.isfinite(beats) or beats <= 0:
                raise ValueError("invalid note duration")
            if pitch is None:
                emit()
                run.clear()
            else:
                run.append((pitch, beats))
            elapsed += beats
        emit()
    if not result:
        raise ValueError("voicelead requires an authored phrase with notes")
    return result

