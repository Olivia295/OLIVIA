"""Someone else's words, reported by the user ("她跟我说她不想活了", "他说了句“活够了”").

A Stage 2 phrase matches whoever says it, so a user worried about a friend who quotes the
friend's words entered the crisis flow herself. This module finds the phrases that are
structurally someone else's speech (``risk.yaml`` section ``reported_speech``, described
on :class:`~olivia.core.safety.lexicon.ReportedSpeechRules`): a third-person speaker, a
speech verb, then only fillers before the phrase. It never decides a level: the rule model
voids reported phrases only when nothing else in the message is a risk cue (``crisis.py``),
so the user's own words next to a quote always keep their level.

``ReportedSpeech.contents`` (问题单第 6 条, 2026-10-26) gives the spans of those reported
words, so the screen can rate them on their own (``SafetyScreen.reported_risk``) and the
session can answer with resources for the other person.

Every check fails toward keeping the phrase: a self word anywhere between the speaker and
the phrase (except an object such as 跟我说), clause punctuation between speaker and verb,
anything but a filler after the verb, or a veto such as 我也是 in the message.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from olivia.core.safety.lexicon import CompositionRules, ReportedSpeechRules
from olivia.core.safety.matcher import Match, PhraseMatcher

_SPEAKER = "s"
_SPEAKER_EXCEPTION = "S"
_VERB = "v"
_VERB_EXCEPTION = "V"
_SELF = "m"
_RECIPIENT = "r"
_VETO = "x"


def _covered(span: Match, covers: Iterable[Match]) -> bool:
    return any(c.start <= span.start and span.end <= c.end for c in covers)


class ReportedSpeech:
    """Answers "is this Stage 2 phrase someone else's reported words?"."""

    def __init__(self, rules: ReportedSpeechRules, compositions: CompositionRules) -> None:
        self._enabled = bool(rules.speakers and rules.verbs)
        self._gap = rules.speaker_gap
        self._stops = compositions.stops
        # Longest first, so "他们" is stripped before "他".
        self._fillers = tuple(sorted(rules.fillers, key=len, reverse=True))
        roles: dict[str, set[str]] = {}
        for role, phrases in (
            (_SPEAKER, rules.speakers),
            (_SPEAKER_EXCEPTION, rules.speaker_exceptions),
            (_VERB, rules.verbs),
            (_VERB_EXCEPTION, rules.verb_exceptions),
            (_SELF, compositions.selves),
            (_RECIPIENT, compositions.recipients),
            (_VETO, rules.vetoes),
        ):
            for phrase in phrases:
                roles.setdefault(phrase, set()).add(role)
        self._roles = {phrase: frozenset(r) for phrase, r in roles.items()}
        self._matcher = PhraseMatcher({phrase: phrase for phrase in self._roles})

    def reported(self, text: str, phrases: Sequence[Match]) -> list[Match]:
        """The ``phrases`` (spans in the normalized ``text``) that are reported speech.

        Empty when the message carries a veto (the user joins in: 我也是, 一起)."""
        if not self._enabled or not phrases:
            return []
        found: dict[str, list[Match]] = {}
        for match in self._matcher.find_all(text):
            for role in self._roles[match.key]:
                found.setdefault(role, []).append(match)
        if found.get(_VETO) or not found.get(_VERB) or not found.get(_SPEAKER):
            return []
        recipient_ends = {m.end for m in found.get(_RECIPIENT, ())}
        selves = found.get(_SELF, [])
        verbs = [v for v in found[_VERB] if not _covered(v, found.get(_VERB_EXCEPTION, ()))]
        speakers = [
            s
            for s in found[_SPEAKER]
            if not _covered(s, found.get(_SPEAKER_EXCEPTION, ())) and s.start not in recipient_ends
        ]
        return [
            phrase
            for phrase in phrases
            if not any(phrase.start <= m.start and m.end <= phrase.end for m in selves)
            and any(
                self._after_verb(text, verb, phrase)
                and self._spoken_by(text, verb, speakers, selves, recipient_ends)
                for verb in verbs
                if verb.end <= phrase.start
            )
        ]

    def contents(self, text: str) -> list[tuple[int, int]]:
        """Spans of someone else's reported words in the normalized ``text`` (问题单第 6
        条, 2026-10-26): from a speech verb whose third-person speaker stands shortly
        before it, in its clause and with no self word as subject (as for :meth:`reported`),
        to the end of that clause, leading fillers dropped ("他说周末要……" -> "周末要……").

        Every check fails toward the user: a span that holds a self word (我, 自己 as the
        user ...) is left out, and the message has none when it carries a veto (我也, 一起)
        or no speaker and verb. Spans never overlap; only the session reads them, to tell
        the level of the reported words themselves."""
        if not self._enabled:
            return []
        found: dict[str, list[Match]] = {}
        for match in self._matcher.find_all(text):
            for role in self._roles[match.key]:
                found.setdefault(role, []).append(match)
        if found.get(_VETO) or not found.get(_VERB) or not found.get(_SPEAKER):
            return []
        recipient_ends = {m.end for m in found.get(_RECIPIENT, ())}
        selves = found.get(_SELF, [])
        verbs = [v for v in found[_VERB] if not _covered(v, found.get(_VERB_EXCEPTION, ()))]
        speakers = [
            s
            for s in found[_SPEAKER]
            if not _covered(s, found.get(_SPEAKER_EXCEPTION, ())) and s.start not in recipient_ends
        ]
        spans: list[tuple[int, int]] = []
        for verb in sorted(verbs, key=lambda m: m.start):
            if spans and verb.start < spans[-1][1]:
                continue
            if not self._spoken_by(text, verb, speakers, selves, recipient_ends):
                continue
            start = self._skip_fillers(text, verb.end, len(text))
            end = next((i for i in range(start, len(text)) if text[i] in self._stops), len(text))
            if start >= end or any(start <= m.start < end for m in selves):
                continue
            spans.append((start, end))
        return spans

    def _skip_fillers(self, text: str, start: int, end: int) -> int:
        """The first index from ``start`` that does not begin a filler (他, 也, 已经 ...)."""
        while start < end:
            filler = next((f for f in self._fillers if text.startswith(f, start, end)), None)
            if filler is None:
                break
            start += len(filler)
        return start

    def _after_verb(self, text: str, verb: Match, phrase: Match) -> bool:
        """Only fillers stand between the verb and the phrase."""
        rest = text[verb.end : phrase.start]
        while rest:
            filler = next((f for f in self._fillers if rest.startswith(f)), None)
            if filler is None:
                return False
            rest = rest[len(filler) :]
        return True

    def _spoken_by(
        self,
        text: str,
        verb: Match,
        speakers: Sequence[Match],
        selves: Sequence[Match],
        recipient_ends: set[int],
    ) -> bool:
        """A third-person speaker shortly before the verb, in its clause, with no self
        word in between that is not an object (跟我说) or part of the verb (告诉我)."""
        for speaker in speakers:
            if speaker.end > verb.start or verb.start - speaker.end > self._gap:
                continue
            between = text[speaker.end : verb.start]
            if any(ch in self._stops for ch in between):
                continue
            subject = any(
                speaker.end <= m.start and m.end <= verb.start and m.start not in recipient_ends
                for m in selves
            )
            if not subject:
                return True
        return False
