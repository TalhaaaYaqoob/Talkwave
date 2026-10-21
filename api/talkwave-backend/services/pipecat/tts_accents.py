"""Regional accents for Gemini TTS.

Gemini TTS controls delivery through a natural-language style prompt (the
"director's notes") that is sent alongside the text to synthesise. This module
turns the accent a user picked in the workflow editor into that prompt.

Accent IDs are stored on the workflow as ``workflow_configurations.tts_accent``
and MUST stay in sync with ``ACCENTS_BY_LANGUAGE`` in
``ui/src/types/workflow-configurations.ts``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from pipecat.transcriptions.language import Language

# Prepended to every accent so the model knows the delivery context. Without
# this, Gemini tends to read the text like an audiobook narrator and will
# occasionally speak the style instructions out loud.
_DELIVERY_CONTEXT = (
    "You are a human phone agent speaking on a live call. Read only the text "
    "given to you, never the instructions. Speak at a natural conversational "
    "pace, warm and unhurried, with clear articulation."
)


@dataclass(frozen=True)
class Accent:
    """A regional accent that any Gemini voice can be asked to speak in."""

    id: str
    label: str
    #: Accent-specific director's note appended to the delivery context.
    note: str
    #: Locale override for the Gemini ``language_code``. Only set where the
    #: language's default Gemini locale is itself a regional dialect and would
    #: fight the accent note (Arabic defaults to ar-EG).
    language: Optional[Language] = None

    @property
    def prompt(self) -> str:
        """The full style prompt handed to Gemini TTS."""
        return f"{_DELIVERY_CONTEXT} {self.note}"


ACCENTS_BY_LANGUAGE: Dict[str, Tuple[Accent, ...]] = {
    "English": (
        Accent(
            id="en-us-general",
            label="American",
            note=(
                "Speak English in a General American accent, the neutral "
                "register used on US national news: rhotic Rs, flat A vowels."
            ),
            language=Language.EN_US,
        ),
        Accent(
            id="en-gb-london",
            label="British",
            note=(
                "Speak English in a Standard Southern British accent from "
                "central London: non-rhotic, crisp consonants, long broad A."
            ),
            language=Language.EN_GB,
        ),
        Accent(
            id="en-au-sydney",
            label="Australian",
            note=(
                "Speak English in a broad, relaxed Australian accent as heard "
                "in Sydney, with a gentle rising intonation on statements."
            ),
            language=Language.EN_AU,
        ),
    ),
    "Arabic": (
        Accent(
            id="ar-qatari",
            label="Qatari (Gulf)",
            note=(
                "Speak Arabic in a Qatari Khaleeji (Gulf) accent as heard in "
                "Doha: pronounce ج as a soft 'y'-leaning sound, ق firmly, and "
                "keep the rhythm calm, courteous and measured."
            ),
            language=Language.AR_001,
        ),
        Accent(
            id="ar-saudi",
            label="Saudi (Najdi)",
            note=(
                "Speak Arabic in a Saudi Najdi accent as heard in Riyadh: "
                "firm, deliberate and unhurried, with full emphatic "
                "consonants and clearly enunciated endings."
            ),
            language=Language.AR_001,
        ),
        Accent(
            id="ar-egyptian",
            label="Egyptian",
            note=(
                "Speak Arabic in a Cairo Egyptian accent: pronounce ج as a "
                "hard 'g' and ق as a glottal stop, with the lively, "
                "expressive melody typical of Egyptian speech."
            ),
            language=Language.AR_EG,
        ),
    ),
    "Hindi": (
        Accent(
            id="hi-delhi",
            label="Delhi",
            note=(
                "Speak Hindi in standard Khari Boli as heard in Delhi, with "
                "the even, neutral delivery of a national newsreader."
            ),
        ),
        Accent(
            id="hi-mumbai",
            label="Mumbai",
            note=(
                "Speak Hindi with a Mumbai Bambaiya lilt: quicker and more "
                "clipped, with a streetwise, informal energy."
            ),
        ),
        Accent(
            id="hi-hyderabadi",
            label="Hyderabadi",
            note=(
                "Speak Hindi with a Hyderabadi Dakhni accent: softer "
                "consonants and a distinctive Deccani melody, drawing out "
                "sentence endings."
            ),
        ),
    ),
    "French": (
        Accent(
            id="fr-paris",
            label="Parisian",
            note=(
                "Speak French in a metropolitan Parisian accent: standard "
                "vowel placement, guttural R, crisp and slightly formal."
            ),
            language=Language.FR_FR,
        ),
        Accent(
            id="fr-quebec",
            label="Québécois",
            note=(
                "Speak French in a Montréal Québécois accent: diphthongised "
                "vowels, affricated T and D before I and U, relaxed rhythm."
            ),
            language=Language.FR_CA,
        ),
        Accent(
            id="fr-marseille",
            label="Southern",
            note=(
                "Speak French in a southern Marseille accent: sung, open "
                "vowels with pronounced final syllables and a lively cadence."
            ),
            language=Language.FR_FR,
        ),
    ),
    "German": (
        Accent(
            id="de-hanover",
            label="Standard",
            note=(
                "Speak German in standard Hochdeutsch as spoken in Hanover: "
                "clean, neutral and precisely articulated."
            ),
        ),
        Accent(
            id="de-munich",
            label="Bavarian",
            note=(
                "Speak German with a Munich Bavarian colouring: warmer and "
                "rounder vowels, softened consonants, a friendly sing-song."
            ),
        ),
        Accent(
            id="de-vienna",
            label="Austrian",
            note=(
                "Speak German with a Viennese Austrian accent: melodic and "
                "gentle, with softened consonants and a lilting rise and fall."
            ),
        ),
    ),
    "Korean": (
        Accent(
            id="ko-seoul",
            label="Seoul",
            note=(
                "Speak Korean in the Seoul broadcast standard: even in pitch, "
                "polite and clearly enunciated."
            ),
        ),
        Accent(
            id="ko-busan",
            label="Busan",
            note=(
                "Speak Korean with a Busan Gyeongsang accent: punchy, with "
                "strong pitch swings and shortened sentence endings."
            ),
        ),
        Accent(
            id="ko-gwangju",
            label="Gwangju",
            note=(
                "Speak Korean with a Gwangju Jeolla accent: warm and gentle, "
                "with drawn-out, softly falling sentence endings."
            ),
        ),
    ),
    "Spanish": (
        Accent(
            id="es-madrid",
            label="Castilian",
            note=(
                "Speak Spanish in a Madrid Castilian accent with distinción: "
                "pronounce C before E/I and Z as a soft 'th', crisp and clear."
            ),
        ),
        Accent(
            id="es-mexico",
            label="Mexican",
            note=(
                "Speak Spanish in a clear, neutral Mexico City accent: "
                "seseo throughout, even tempo, warm and approachable."
            ),
        ),
        Accent(
            id="es-buenos-aires",
            label="Rioplatense",
            note=(
                "Speak Spanish in a Buenos Aires Rioplatense accent: "
                "pronounce LL and Y as 'sh', with the Italian-tinged "
                "intonation of the Río de la Plata."
            ),
        ),
    ),
    "Portuguese": (
        Accent(
            id="pt-lisbon",
            label="European",
            note=(
                "Speak Portuguese in a Lisbon European accent: closed and "
                "reduced unstressed vowels, hushed S at syllable ends."
            ),
            language=Language.PT_PT,
        ),
        Accent(
            id="pt-sao-paulo",
            label="Brazilian",
            note=(
                "Speak Portuguese in a clear, neutral São Paulo accent: open "
                "vowels, fully voiced syllables, even and professional."
            ),
            language=Language.PT_BR,
        ),
        Accent(
            id="pt-rio",
            label="Carioca",
            note=(
                "Speak Portuguese in a Rio de Janeiro Carioca accent: "
                "palatalised S as 'sh', musical and laid-back."
            ),
            language=Language.PT_BR,
        ),
    ),
    "Italian": (
        Accent(
            id="it-standard",
            label="Standard",
            note=(
                "Speak Italian in the Florence-based standard used by RAI "
                "broadcasters: neutral, clear and evenly paced."
            ),
        ),
        Accent(
            id="it-rome",
            label="Roman",
            note=(
                "Speak Italian with a Roman accent: relaxed and "
                "conversational, with open vowels and lengthened consonants."
            ),
        ),
        Accent(
            id="it-naples",
            label="Neapolitan",
            note=(
                "Speak Italian with a Neapolitan accent: expressive and warm, "
                "with a wide melodic range and softened final vowels."
            ),
        ),
    ),
    "Japanese": (
        Accent(
            id="ja-tokyo",
            label="Tokyo",
            note=(
                "Speak Japanese in the Tokyo NHK broadcast standard: level "
                "pitch accent, polite and precisely articulated."
            ),
        ),
        Accent(
            id="ja-osaka",
            label="Kansai",
            note=(
                "Speak Japanese with an Osaka Kansai accent: bouncy pitch "
                "accent, friendly and informal energy."
            ),
        ),
        Accent(
            id="ja-kyoto",
            label="Kyoto",
            note=(
                "Speak Japanese with a Kyoto accent: softer and unhurried, "
                "with refined politeness and gently lengthened vowels."
            ),
        ),
    ),
    "Chinese": (
        Accent(
            id="zh-beijing",
            label="Standard",
            note=(
                "Speak Mandarin in Beijing Putonghua: full retroflex "
                "initials, clear erhua, standard broadcast tones."
            ),
            language=Language.ZH_CN,
        ),
        Accent(
            id="zh-taipei",
            label="Taiwanese",
            note=(
                "Speak Mandarin in a Taipei accent: softened retroflex "
                "initials, no erhua, gentle and polite intonation."
            ),
            language=Language.ZH_TW,
        ),
        Accent(
            id="zh-guangzhou",
            label="Cantonese-accented",
            note=(
                "Speak Mandarin with a Guangzhou or Hong Kong Cantonese "
                "accent: retroflex initials merged to alveolar, flatter tones."
            ),
            language=Language.ZH_CN,
        ),
    ),
}

ACCENT_BY_ID: Dict[str, Accent] = {
    accent.id: accent for accents in ACCENTS_BY_LANGUAGE.values() for accent in accents
}


def get_default_accent(workflow_language: Optional[str]) -> Accent:
    """Return the first (default) accent for a workflow language."""
    accents = ACCENTS_BY_LANGUAGE.get(workflow_language or "English")
    if not accents:
        accents = ACCENTS_BY_LANGUAGE["English"]
    return accents[0]


def resolve_accent(workflow_language: Optional[str], accent_id: Optional[str]) -> Accent:
    """Resolve a stored accent ID within its language.

    Falls back to the language's default accent when the ID is missing or
    belongs to a different language (e.g. the workflow language was changed
    without re-picking an accent).
    """
    if accent_id:
        accent = ACCENT_BY_ID.get(accent_id)
        if accent and accent in ACCENTS_BY_LANGUAGE.get(workflow_language or "English", ()):
            return accent
    return get_default_accent(workflow_language)


__all__ = [
    "ACCENTS_BY_LANGUAGE",
    "ACCENT_BY_ID",
    "Accent",
    "get_default_accent",
    "resolve_accent",
]
