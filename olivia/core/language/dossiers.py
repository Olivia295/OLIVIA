"""The dossier layer: what an active situation changes in the wording (plan D-2, PRD §8.2).

The 60 distress dossiers (``situations/``, taxonomy ``distress_spectra``) reach the
runtime as situation codes: perception.yaml ``situation_cues`` sets them, the session
keeps them for the rest of the session (``methods/contraindications.py``), and two
pieces of language data drawn from the dossiers use them:

* ``metaphors.yaml`` ``by_situation``: nature images built on each dossier's own imagery.
  Precedence for the ``{metaphor}`` slot: the images of every active situation (pooled,
  codes in taxonomy order), then the spectrum x yearning cell, then the fallback list.
  With no active situation that has images the engine draws exactly as before.
* ``grade_bc_info.yaml`` ``situation_lenses``: the Grade B methods a dossier itself names.
  Precedence for the one S_clarify lens of a session: the active situations' lenses that
  the solver's ``info_cards`` masks allow, then the ``clarify_lenses`` of the spectra that
  fit the turn (``fitting_spectra``, F3).

Neither layer reaches crisis replies, red-flag referrals or the m0 rule: the seven
red-flag dossiers have no entries (the loaders reject them), the solver's masks and
arousal gate still decide which information card may appear at all, and m0 situations
get no information card from the solver.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence


def situation_images(
    by_situation: Mapping[str, tuple[str, ...]], situations: Iterable[str]
) -> tuple[str, ...]:
    """Every image of the active situations, codes in taxonomy (= sorted) order."""
    return tuple(image for code in sorted(situations) for image in by_situation.get(code, ()))


def lens_pool(
    allowed: Sequence[str],
    situation_lenses: Mapping[str, tuple[str, ...]],
    situations: Iterable[str],
    spectrum_lenses: Sequence[str],
) -> list[str]:
    """The lenses to draw from: dossier lenses the masks allowed, else the spectrum's.

    ``allowed`` is ``info_cards``'s answer for the turn (taxonomy order), so the result
    keeps that order and never holds a method the masks removed.
    """
    preferred = {mid for code in situations for mid in situation_lenses.get(code, ())}
    pool = [mid for mid in allowed if mid in preferred]
    return pool or [mid for mid in allowed if mid in spectrum_lenses]


def fitting_spectra(situations: Iterable[str], spectrum: str | None) -> frozenset[str]:
    """The spectra a spectrum lens must belong to (F3).

    With an active situation, the spectra of the active situations (``SIT-06-03`` -> "06"),
    so a breakup or a bereavement never gets a lens drawn for another spectrum (交互分析
    after "我们分手了"); otherwise ``spectrum``, the one the conversation showed last.
    Empty when neither is known: no spectrum lens then.
    """
    codes = [code.split("-") for code in situations]
    from_situations = frozenset(parts[1] for parts in codes if len(parts) == 3)
    if from_situations:
        return from_situations
    return frozenset({spectrum}) if spectrum is not None else frozenset()
