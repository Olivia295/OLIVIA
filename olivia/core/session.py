"""The single conversation entry point (DEVELOPMENT_PLAN P4, roadmap P4-3).

``Session.open`` checks the age gate and loads everything a conversation needs; a lexicon,
template or hotline file that fails to load or verify raises there, so no conversation
starts without its safety data. ``Session.turn`` then runs one user turn through the whole
pipeline in a fixed order (SDD §8.1), and no caller can skip or reorder a step:

1. ``SafetyScreen.assess`` on the raw text.
2. ``RuleStub.perceive`` with that assessment. It is a pure function of the text and the
   assessment and touches no session state; it runs here so the tracker gets the turn's
   valence for its "L1 with worsening valence" escalation (PRD §9.1).
3. ``CrisisTracker.observe``, then ``SessionRedFlags.observe`` (profile
   ``clinical_history`` codes are active from the start). In model mode the student's
   perception heads then refine the rule context (``perception/model_heads.py``, roadmap
   C1); the tracker has already read the rule valence, so crisis handling is the same in
   both modes.
4. ``fsm.step`` with the perception, the crisis status and the turn's signals.
5. Stage handling and language rendering; the engine's output gate checks every
   rendered text.
6. Bandit feedback on the card that was waiting for it.

Stage handling:

* ``S_crisis``: a CRISIS card at ``max(L2, this turn's level, the crisis entry level)``
  for the profile region (never the minors-only lines), rendered by ``render_crisis``.
  Using the entry level keeps an L3 card's emergency numbers on screen for every turn of
  an L3 crisis, not only the turns that repeat the plan (ruling 14). When the risk model
  scored L3 but the arbitration capped it at L2 (its L3 is not plan evidence), the L2
  card leads with the region's emergency numbers, framed as on an L3 card, for the rest
  of that crisis; every L2 line stays and the flow stays L2 (owner decision 2026-10-24).
  On the turn the tracker hears an explicit safety confirmation, one
  ``followups.safety_confirmed`` line comes before the card. From that turn until the
  crisis ends (or a new L2/L3 turn voids the confirmation) the opening is an
  ``S_crisis.after_confirmed`` one, which does not ask about safety again (F5b). An
  "我没事"-like message (``utterances.yaml`` ``reassurance``) that the tracker does not
  count as a confirmation gets ``crisis.confirm_hint`` after the opening, once per
  crisis. No compact card exists (SDD §8.2's "精简版"; render data has only the
  gate-fallback minimal card), so every crisis turn repeats the full card.
* ``S_empower``: the solver's available set, minus actions that have no follow-along card
  (``12:tipp_cold_water`` is excluded from the deck pending G-0), is sampled by Thompson
  sampling in the dominant spectrum; only the regular Grade A pool is explored (SDD §6.3,
  ``AllowedSet.explorable``), every other pool (the stabilization whitelist, an L1 turn,
  a red flag's closed set) gets the highest posterior mean. A turn with no spectrum cue
  uses the conversation's last known spectrum, else ``"02"`` (the low-mood spectrum, the
  commonest presentation), and the card's feedback is filed under the same spectrum. A
  card that leaves S_haven on a direct request ends with ``followups.haven_return`` (how
  to get back to quiet company). No candidate -> m0, a companionship reply from the
  S_explore templates; any red flag in the plan appends the referral card. While a shown
  card still waits for feedback, an S_empower turn re-sends the ``after_card`` prompt
  instead of sampling a new card. That covers a direct request straight after an
  S_explore stabilization card too: the rule stub reads each turn on its own, so
  "能给我一个练习试试吗" one turn after "喘不上气" looks calm and would otherwise open the
  full cognitive pool (red-team rt084-rt086 with the probe turn). The card then waits in S_empower.
  F16b: a request on that turn for another method ("再给我一个", "换一个", "有没有别
  的方法"; ``TurnSignals.another_method``) or for a practice other than the waiting one
  ("带我做一下正念", ``therapy_request``) is read as ``/not-now`` for the waiting card
  (it goes into the kit; ``inspect["feedback"]`` is NOT_NOW) and a new card is sampled
  as usual, led by one ``followups.card_switched`` line. Only on a calm turn (outside a
  crisis, the screen and the rule screen below L1, no command), and only when the masks
  leave another card to show; otherwise the ``after_card`` prompt as before. A card shown
  from the stabilization whitelist (an S_explore card, an L1 turn or arousal at the
  somatic line; ``_Pending.stabilization``) is replaced from the whitelist only, and so
  is every card after it, so the calm-looking swap never opens the full pool. A generic
  request ("能给我一个练习试试吗", the red-team probe) still keeps the waiting card.
* ``S_explore`` at or above ``arousal.thresholds.somatic_priority`` (COLBO-02, SOP 3):
  the solver's stabilization whitelist, sampled the same way, shown as a card framed by
  the S_explore reflection (reflect paragraph, then card intro, card and ``after_card``).
  Not while the pure-listening lock is on, not while an S_explore card still waits for
  feedback and not on a turn that gives feedback. No candidate -> the plain S_explore
  reply. The card waits for one more turn only: after an S_explore turn that neither
  answers it nor gets the clarification question, it expires, so a later request gets a
  new card.
* ``S_closing``: entering it, the closing ritual matches the feedback: ``S_closing.
  variants`` after ``/done`` (nothing about the kit), ``after_not_now`` after
  ``/not-now`` (the card is in the kit). Later turns in S_closing get one
  ``S_ready.after_close`` line, never the same closing text twice in a row; new content
  that is not plainly positive (not a yes or no, a command, a feedback phrase or a kit
  request) reopens listening in S_explore (``inspect["reason"]`` ``CLOSING_REOPEN``).
  A yes that ends the session in S_ready also gets an ``after_close`` line. An
  ``after_close`` line that points at the evening ("愿你今晚…", "早点休息") is used only
  from 18:00 local time through the B7 late-night window; at other hours the line comes
  from ``after_close_daytime`` (F6b).
* ``S_haven``: ``compose(stage, slots)``; the first calm S_haven reply of a session that
  carries no wellbeing reminder is ``followups.haven_exit_hint`` instead, which keeps the
  company and says how to leave ("说「我好多了」或「换个话题吧」"; FSM-15, F9, F10). Those
  words take the session back to S_explore (``Reason.HAVEN_EXIT_ASKED``); that turn's
  mirror slot is a ``HAVEN_EXIT`` acknowledgement, never the exit words echoed (F10).
* Every other stage: ``compose(stage, slots)``.

Meta turns, outside a crisis and below an L2 screen: a feedback command with no card
waiting gets ``followups.no_pending_feedback`` and a short request to wipe the memory
("清空所有记忆", below L1) gets ``followups.forget_hint`` (``olivia forget --all``,
``olivia memory``); neither is mirrored, and the stage holds (unless the battery or a
crisis moves it). ``/unhelpful`` or aversion on a waiting card leads the reply with
``followups.unhelpful_ack``.

Leaving for now (F5d): with no card waiting for feedback, a turn whose message takes
leave (``TurnSignals.leave_taking``: "我去睡了", "今天就到这里吧") gets one
``S_ready.after_close`` line instead of the stage reply, with no card and no information
card (the S_clarify lens included), and the stage moves as the state machine says (S_closing
still follows a practice only, SDD §4.2). Only on a calm screen: the rule screen below L1
and the turn's screen at most L1 (an L1 only an injected model gives, F10: "嗯，今天就到
这里吧" at a model score of 0.22 is still a goodbye), outside a crisis, not the D3
question or its answer, not a command or a note, and not in S_crisis, S_closing or
S_ready (those keep their own replies), so "活着好累，我去睡了" (a rule L1) gets the L1
reply. A card waiting for feedback reads the same phrase as not_now instead (F5a). I7
(2026-10-26): "晚安" and "睡了" said as a clause of their own take leave too (also in
S_haven, "[2%] 睡了"), and a goodbye or after-close line is never the text of the reply
just before it.

Failures (SDD §10.1): the crisis screen runs first and its own failures are its own
(model failures already fail toward L2). Anything that raises after it gives a degraded
reply instead of an exception: the minimal crisis card with every number of the
region's card when the screen said L2/L3, the session is in a crisis or the D3 answer
was due, otherwise the persona's slot-free presence line (``ReplyKind.HAVEN``).
``inspect["reason"]`` is ``DEGRADED`` and ``inspect["degraded"]`` the error's class
name; nothing is logged and no user text is kept.

Red-flag referral (SDD §8.4): the first non-crisis turn on which a flag is active (from
the profile, or newly detected in the text) appends ``render_referral`` for it, once per
flag per session. A plan in S_empower or a stabilization card also appends the referral
for its plan's flags every time, since the solver requires the card with every plan; when
the same card was shown on the turn before, it comes with a short intro and every
destination, without the closing paragraph (F5b).

A red-flag user who asks what a therapy is ("CBT是什么", ``therapy_question``; F9) gets
no explainer, since the red-flag closure allows none: in an ordinary stage, on a calm
turn without feedback or a direct request, the reply is one ``followups.therapy_referred``
line (neutral, pointing at a doctor or counsellor, no practice) followed by the
referral card again, not an ordinary reply that ignores the question.

Grade B/C information cards (PRD §8.1, roadmap next-phase A4), never on a crisis turn
(the tracker's crisis or an L1-L3 screen), with feedback for a waiting card, or with a
direct request; the solver's ``info_cards`` applies the red-flag closure, bans, arousal
gate and stage rules, so a red-flag user only ever gets the referral card:

* asked: a Grade B/C therapy named in a question (``TurnSignals.therapy_question``) gets
  ``render_info_reply(lens=False)`` as the whole reply, Grade C in any ordinary stage and
  Grade B in S_clarify only. A card waiting for feedback keeps waiting.
* lens: once per session, an S_clarify turn without the listening lock that is not heavy
  (F6b: grief, sadness with a loss situation active, the bereavement spectrum, arousal
  above ``exploration_allow`` or an L1 screen; the lens then waits for a calmer turn and
  its once-per-session use is not spent) appends one Grade
  B explainer (``render_info_reply(lens=True)``) to the S_clarify reply, drawn from the
  Grade B methods the active situations' dossiers name (``situation_lenses``, plan D-2)
  when the masks leave one, else from the ``clarify_lenses`` entry of the most recent
  spectrum the conversation showed (``language/dossiers.py``). Not for SILENT_ANCHOR,
  which only listens.

A request to remember something ("记住：……", the note cues of ``memory.yaml``) never
gets an information card (F5b): the recorder answers that turn with its short
confirmation.

A question about a note (F15; PRD MIYI-04): ``TurnSignals.note_recall`` (rule phrases, the
same in both modes) is passed on as ``inspect["note_recall"]`` (``explicit`` or
``question``) only on a calm turn: outside a crisis, the screen below L2 and the rule
screen below L1 (F16a: an L1 only an injected model gives does not hold it back), not
the D3 question or its answer, not a note, command, direct or kit request, therapy
question, goodbye or meta turn. The session never sees the notes: the recorder
(``memory/recorder.py``) looks them up and answers in the reply. An explicit one gets no
information card; the stage moves as for any other turn, as on a note turn.

Persona (PRD ONB-03, plan D-1): the profile's ``persona_spectrum`` picks the reply
templates and word windows (``LanguageData.for_persona``); crisis resource lines and the
D3 question are the same for every persona.

Language quality (F3): the ``{emotion}`` slot never names the rule stub's fallback
emotion (``LanguageEngine.feeling_word``); a very short message gets the two-paragraph
reply (``is_short_input``) unless a naming line must be swapped in; a Grade A practice
asked for by name ("带我做一下正念", ``TurnSignals.therapy_request``) is the card shown
when the solver allows it, and one asked about ("CBT是什么") gets its short explainer
(never for a red-flag user); the spectrum lens must fit the active situations
(``fitting_spectra``); cards end with the at-work line only in the user's working hours;
and outside a crisis a medication-dose or "am I X?" question gets one plain line
(``LanguageEngine.boundary_line``) before the reply.

A card whose text names one of the profile's taboo topics, or that the gate blocks, is
not shown and the turn is handled as if nothing had been asked.

Reply kinds: CRISIS for the crisis path; CARD when an exercise card is shown; REFERRAL
when a referral card is shown and no exercise card; INFO when a Grade B/C information
card is shown; HAVEN for S_haven and for any reply the gate or the taboo filter replaced
with the haven line; NORMAL otherwise.

Taboo topics (ruling 21) are a hard filter on every non-CRISIS, non-REFERRAL text: a hit
outside the mirrored user words recomposes the reply with fresh template draws, up to
``TABOO_RETRIES`` times, and otherwise replaces it with the haven line. Crisis and
referral wording is exempt so a taboo never hides safety resources.

Feedback (SDD §6.3) only ever lands on a card that was shown and is still waiting:
``/done`` -> HELPFUL; ``/not-now`` -> NOT_NOW and the action is shelved for the session;
``/unhelpful`` or aversion -> UNHELPFUL. For an S_empower card the state machine's
reason decides (an arousal retreat wins over a command on the same turn and gives no
feedback); for an S_explore stabilization card the next S_explore turn's command or
aversion does, unless that turn enters a crisis. Leaving the stage the card was shown
in ends the wait.

Natural-language follow-ups (roadmap R-7b), read before the state machine runs and
never on a crisis turn (the tracker's crisis or an L2/L3 screen) or an L1 screen:

* While a card waits in the current stage, a feedback phrase ("做完了", "今天先不做了",
  "这个不适合我") is passed to the state machine as the command it stands for, so it has
  exactly the command's effects; a slash command wins. Aversion keeps its own route.
* An unclear reply ("唉", "再说吧") to a waiting card that is still waiting after the
  turn gets one clarification question (``followups.clarify_feedback``). On the next
  turn only, a yes records NOT_NOW as if ``/not-now`` had been sent; a no, or anything
  else, is handled as it would be without the question (the card keeps waiting).
* A kit recall ("锦囊里那个再给我看看") outside a crisis acts as a direct request and
  re-offers the most recently shelved action the solver allows now, which leaves the
  kit until it is shelved again; with an empty kit the reply is ``followups.kit_empty``
  (not in S_haven). The kit is the kit carried in from earlier sessions followed by this
  session's ``user_shelved_actions`` (newest last).

Cross-session state (next-phase B3, ``memory/state.py``): ``Session.open(carried=...)``
seeds the sampler's posteriors and the kit from an earlier session; ``carried_state()``
is what to keep for the next one. Only this session's shelved actions are masked out of
sampling ("shelved for the session"); a carried kit entry can still be sampled, and a kit
card shown again, recalled or sampled, leaves the kit until it is shelved again. Kit
entries the solver does not allow now or that have no card are skipped, as within a
session. Opened without ``carried``, a session starts from the priors with an empty kit.
* In S_closing a whole-message yes ("好", "可以") confirms the implementation intention
  like an ``intent_confirmed`` phrase; a no ("不用了") gets ``followups.closing_declined``
  and the session stays in S_closing.

Anti-dependence prompts (next-phase B7, decision D5; ``chang/wellbeing.py``): the 45-minute
break reminder, the once-per-session late-night line and real-world support guidance go
only on an ordinary composed reply on a calm turn (no crisis, no L1-L3 screen), never on a
card, information, referral, safety-question or follow-up reply. ``inspect["reminder"]`` is
``none``, ``break`` or ``late_night``; ``inspect["real_support_share"]`` is the share of
this session's replies that carried real-support guidance (PRD §11.1),
``inspect["real_support"]`` whether this reply carried it, and ``inspect["late_night"]``
whether this turn fell in the B7 late-night window (a degraded turn reports it too). The
ledger's session summary counts the last two (step F12, ``olivia stats``).
``inspect["battery_prefix"]`` is this turn's ``[NN%]`` reading (0.0-1.0) or None without a
prefix, while ``inspect["battery"]`` is the battery the session goes on with; the summary
keeps the lowest reading and whether the session was in S_haven (the journal's battery
line, CHANG-04).

``inspect["uncapped_level"]`` is set only on a turn the F10 denial cap lowered: the
level before the cap, which the tracker reads in a crisis, while ``assessed_level`` stays
the capped one (``--inspect`` shows both, F15).

``inspect["feedback_source"]`` says where recorded feedback came from: ``command``,
``phrase`` (a feedback or aversion phrase) or ``confirmed`` (a yes to the question).

Direct question about intent (decision D3, step A7): a turn whose screen reports an
``ASK_INTENT`` cue (a euphemistic request for a way to end a life: 想走了 + 不痛, end it
without pain) while the turn stays below L2 and outside a crisis gets one gentle, direct
question about suicidal intent plus the region's L2 resource lines (SAFETY_CHECK), and
nothing else: no card, referral, method or advice, and the request is not passed on as a
direct request. The next turn is read as the answer (``safety/intent_check.py``): a clear
no returns to the ordinary flow and sets the in-session gentle-care flag (``snapshot``);
a yes, an unclear answer, no answer or a new crisis cue is read as L2 before the tracker
runs, so the crisis flow follows. A turn that screens L2/L3 itself never waits for the
question. ``inspect["safety_check"]`` is ``asked``, ``affirmed``, ``denied``, ``unclear``
or None.

Model-only alarms ask first (owner decision 2026-10-26): outside a crisis, when a turn's
screen is L2/L3 only because of the injected model (the student in the product) and the
rules found no risk cue at all (``CrisisAssessment.rule_clear``: rule level L0 and no
Stage 1/Stage 2/hyperbole/negation phrase, pair anchor, composition or ask cue; see
``safety.crisis.rules_found_nothing``), and the model did not fail, the turn does not
enter the crisis flow when the student is unsure (owner decision 2026-10-26, second:
``risk.yaml`` ``model_ask``, its class below L3 and its crisis score below 0.6, chosen on
the dev set only): it asks the same D3 question with the region's L2 lines. A sure
student (class L3 or score >= 0.6) enters the crisis flow as before. The turn
reports the screen's level (``crisis_level`` L2, not in crisis) and
``inspect["safety_check_by"]`` ``model``. The next turn is read as for D3, except that a
no must also pass the F10 denial conditions
(``SafetyScreen.clear_denial``); yes, unclear, off topic, no answer, a new cue or the
model's own L2 enter the crisis flow (``MODEL_CHECK_CUE``), and a no sets no gentle-care
flag (I9: being asked and saying no leaves no care marker). At most one such question per
session: any later model-only alarm (also after a sure one) goes straight to the crisis
flow. With any rule cue,
inside a crisis, or in rules mode nothing changes.

Ending in the crisis flow (S5): ``farewell`` gives the goodbye for ``/exit`` or the end of
input inside a crisis, or with either question unanswered (no answer counts as the crisis
flow): one ``crisis.farewell`` line, the region's numbers as on the crisis card and the
safety plan's people (section 4) with their numbers; it asks nothing. In a crisis, a turn
that says the user will contact someone ("我可以给表姐打个电话", ``risk.yaml``
``reach_out``, with no rule risk cue) leads with one ``crisis.reach_out`` line
(``inspect["reach_out"]``); the card and the crisis stay.

Safety replies, round 2 (black-box problem sheet 2026-10-26, items 3, 5, 6, 7, 11; all new
wording in ``render.yaml`` ``crisis``, 草稿：待 G-0; ``ReplyKind.RESOURCES`` is a few lines
and the region's numbers, outside the crisis flow, ``inspect["resources_reply"]`` says
which):

* 3, an accepted no: on the answer to either question, a clear no (the D3 reading) that
  also passes the F10 denial conditions (``SafetyScreen.clear_denial``), in a message the
  rules found no risk cue in (``rule_clear``) and with no model failure, caps a level only
  the model gives at L1 (``uncapped_level`` keeps the level before), so "不是，我没想那些"
  rated L2 by the student no longer enters the crisis flow and holds the session.
* 5, a minor: "我才初二", "其实我14岁" (``TurnSignals.minor_disclosure``, the user's own
  age only) sets ``minor_disclosed`` for the session, in memory only. Outside the crisis
  flow and the D3 question, the reply is the region's L2 lines for young people or
  everyone (CN 12355 first, then 12356): first a gentle note that this place is for
  adults and a trusted adult, then on every later turn a shorter one with how to leave;
  no practice and no chat, a goodbye stays a goodbye, and the stage holds. Crisis and D3
  cards then carry the minors' lines too. The profile is never written; whether to record
  the age is for the caller to ask the user.
* 6, someone else's risk: when the message reports a third person's words
  (``SafetyScreen.reported_risk``) and every rule cue lies inside them, and they carry risk
  by the rules (their own rule level L1 or above or a D3 cue, or a time and a means,
  ``TurnSignals.imminent``; the model's level on them alone never opens it), the
  user's level is at most L1 (read as an L0 turn by the tracker), no D3 question, and the
  reply is one serious line that asks nothing about the user's safety, the region's
  hotlines to pass on (the L3 card with the emergency numbers first when the words carry
  a plan, time or means) and one line about being with the other person (the first time,
  one about taking care of oneself too). For three turns after it, "我该怎么跟她说" or
  "她不让我告诉别人" gets that card again with such a line (round 3, below). The user's
  own words next to it (我也, a self word in the reported words, a cue outside them)
  keep the crisis flow as always.
* 7, a hotline request: "能给我一个心理援助热线的号码吗" (``TurnSignals.hotline_request``),
  in any stage outside the crisis flow and the D3 question (whose replies carry the
  hotlines already), gets the region's BROWSING card, as ``olivia resources`` shows it;
  a word about real names or calling from abroad adds one true line, and alone within two
  turns of a resource card leads the card again. The stage holds.
* 11, after a crisis: ``farewell`` also ends a session that was in the crisis flow and has
  left it (the region's numbers at the crisis's highest level and the plan's people). A
  user with a crisis history (``care_greeting`` was used, or a crisis earlier in this
  session) whose turn is L1 or names strain ("撑不了多久了", ``TurnSignals.strain``) gets
  one ``crisis.care_watch`` line and one line of the region's hotlines before the reply
  (``inspect["care_line"]``), at most once in three turns; the crisis flow is unchanged.

Session flows, round 3 (re-test 2026-10-27, r1/r2/r4; new wording 草稿：待 G-0):

* Someone else's risk is read in more forms (``safety/reported.py``: written or posted
  words, 我哥, intent told in the third person, the next clause of the same words,
  English), the model's own L3 class for the words or a death word next to a time or means
  opens the card too, and the card leads with the emergency numbers when the words carry
  risk and a time, a means or a place. For three turns after it, a cannot-reach, what-to-do
  or keep-it-secret turn gets the card again with what to do (``inspect
  ["third_party_followup"]``), urgent ones keeping the emergency numbers; this replaces the
  one line in an ordinary reply.
* The D3 answer drops interjections first, accepts a repeated no and a first-person
  negated intent whose rest screens L0 (``_negation_capped``).
* In the crisis flow after a confirmation, a model-only L2 the student is unsure of (the
  owner's ask-first rule) pauses the exit count instead of voiding the confirmation
  (``_model_pause``, ``inspect["model_paused"]``); a calm waiting turn gets an answer to
  its words and one line of every number, no safety question (``_crisis_waiting``). Calm
  new words in the crisis flow, and new words while a card waits, are answered first
  (``_heard_line``, ``inspect["heard"]``); the first calm awaiting turn says how to
  confirm.
* The minors' reply leads with the region's emergency numbers. Hotline follow-ups (cost,
  hours, language, real, more) get fixed true lines; a place the user is in that is not
  the profile's gets that region's card, or the general card for a place without verified
  numbers. ``/help``, ``/帮助`` and ``/?`` list the chat commands (``crisis.chat_help``).

Care greeting (PRD §9, step A3): ``care_greeting`` renders the opening check-in for a
session that follows a crisis (or a no to the D3 question) in an earlier one; the CLI
decides when (``chang/care.py``). ``inspect["care_greeting"]`` and ``snapshot`` say
whether this session opened with it.

Safety plan (next-phase B10, decision D8; ``chang/safety_plan.py``): ``Session.open`` takes
the user's saved plan, and the first crisis reply of each crisis then carries its sections
2-4 as one block (``crisis_block``); the later replies of that crisis carry one line that
names the plan's people instead (``crisis_reminder``, S5; ``inspect["safety_plan_reminded"]``),
in the same place: after the opening sentence and before the hotline card at L2, after
the card at L3 (and whenever the card carries emergency numbers), so emergency numbers
come before any other number. Section 5 (keeping dangerous things away) is never shown.
The block skips WILLOW; the whole reply passes the gate with the plan's numbers allowed,
and a blocked plan is dropped, never the card. Never on the D3 question or any other
reply. With ``suggest_safety_plan`` the first S_closing reply on a calm turn ends with one
line about ``olivia safety-plan`` (``safety_plan_suggested``). The session never writes
the plan; ``inspect["safety_plan_shown"]`` says whether this reply showed it.

Introspection (decision D4, step C2; ``perception/introspector.py``): in both modes the
introspector fills the turn's distortions, schemas and yearning right after the rule stub,
so the yearning picks the metaphor and need phrase. In model mode only, the schema seen
most on calm turns (no crisis, no L1 screen, arousal below the somatic line) is mirrored
once per session as a gentle question that replaces the closing question of an S_clarify
reply, never on a turn with a red flag active, the listening lock, the D3 question or its
answer, an information card or a follow-up, and never for SILENT_ANCHOR (it asks no
questions; the state machine keeps it out of C_2 as well). A yes on the next turn (still
in S_clarify, calm) sets ``core_belief_confirmed`` and the state machine moves to S_empower
(``CLARIFY_CORE_BELIEF``), except on a turn whose effective level is L1 (a risk model's
score band; SDD §4.2): the yes is still read (``confirmed``) but S_clarify holds, and later
turns advance by the ordinary turn count only; a no or anything else leaves the flow as it
is.
``inspect`` carries ``distortions``, ``schemas``, ``yearning`` (ids) and ``schema_mirror``
(``asked``, ``confirmed``, ``declined`` or None).

Narrative externalization (PRD 特性四, step C3; ``perception/externalize.py``): under the
mirror's gates, never on the mirror's turn or the turn reading its answer and not after a
no to the mirror, an inner-critic pattern gets one offer per session to name it, which
replaces the closing question of an S_clarify reply. A number or an offered name on the
next turn accepts, a clear no declines, anything else is no answer; the turn is otherwise
an ordinary message. On that turn and, once accepted, on later calm turns where the pattern
shows up again (at most once every three turns), an ordinary S_explore or S_clarify reply
without a red flag swaps its middle paragraph (image or need) for the acknowledgement or a
line that uses the name. ``inspect["externalize"]`` is ``offered``, ``accepted``,
``declined`` or None for this turn; ``inspect["externalize_name"]`` is the accepted name's
id (template names only, never user text). Session-only.

Contraindications and situations (roadmap next-phase A1, decision D2): every solver call
gets the turn's ``active_contraindications`` and ``situation_codes`` from
``methods/contraindications.py`` (profile disclosures, red flags, crisis status and the
perception cues, which hold for the rest of the session). A heart, breathing or
home-safety disclosure heard in the conversation, and not in the profile, adds one
``followups.health_hint`` line (once per disclosure) to the first reply that is not a
crisis, D3, haven or gate-fallback reply; the profile is never written.
``inspect["contraindications"]`` (arousal overload included) and
``inspect["situations"]`` list the ids. Situations also pick the wording (plan D-2): the
``{metaphor}`` slot prefers the active situations' dossier imagery, and the S_clarify
lens their dossier's Grade B methods (``language/dossiers.py``); neither reaches crisis
replies, the referral card or the m0 rule.

Language understanding (dogfood I1-I5, I8, P6, P8; 2026-10-26; new wording 草稿：待 G-0),
never on a crisis turn and never changing the crisis flow:

* A request whose words are apart ("有什么五分钟能做的放松方法吗", ``perception.yaml``
  ``direct_request_patterns``) is a direct request like any other (COLBO-03). Asking how
  to say something ("我该怎么开口跟妈妈聊", ``advice_request``) is advice, which the PRD
  has no mechanism for: no card, the ordinary reply led by ``notices.advice_heard``.
  "别老给我发热线电话" (``hotline_pushback``) leads the reply with
  ``notices.hotline_heard``, which says when hotlines do show.
* A practice the user's own heart or breathing condition masks, named on a calm turn
  ("憋气那种", "冷水敷脸呢"; ``contraindicated_practice`` with the contraindication
  active) is a direct request served from the stabilization whitelist (slow breathing,
  not breath holding), and while a card waits a request for another one (F16b), never
  feedback; the reply opens with ``notices.masked_practice``, which names no diagnosis.
  "为什么不行" up to two turns later is a meta turn answered by
  ``notices.masked_practice_why``. Chest or heart symptoms with that condition end the
  reply once per session with ``notices.cardiac_care``.
* "你会把我说的话存下来吗" (``privacy_question``) is a meta turn answered by
  ``privacy.yaml`` ``chat_answer`` (the facts of ``olivia privacy``).
* S_clarify names a need at most once in three replies, never after a very short reply.
* After a bereavement (grief, SIT-06-04) the S_clarify lens never comes from the trauma
  and bereavement or the attachment spectrum (talk of the person lost reads as their
  cues), and a lens listed in ``grade_bc_info.yaml`` ``lens_requires``
  (couples therapy, CBASP) needs one of its words to have come up (only the method ids
  are kept).
* Referral (§9.3, SDD §8.4): a red flag known only from the profile is referred with a
  plan (a card or m0, as the solver requires), not on the first turn of every session;
  a flag the conversation brings up is referred on that turn, as before.

The session keeps no user text: ``inspect`` and ``snapshot`` hold ids, levels and numbers
only, and gate reasons are reduced to their check names.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Final
from uuid import uuid4

from olivia.core.chang.privacy import load_privacy_text
from olivia.core.chang.safety_plan import (
    SafetyPlan,
    crisis_block,
    crisis_reminder,
    farewell_people,
    load_safety_plan_text,
)
from olivia.core.chang.wellbeing import Reminder, Wellbeing
from olivia.core.fsm.machine import Reason, Transition, TurnInput, step
from olivia.core.language.data import ContentKind, LanguageData, load_language_data, slots_of
from olivia.core.language.dossiers import fitting_spectra, lens_pool
from olivia.core.language.engine import (
    LanguageEngine,
    Slots,
    after_work_hours,
    at_work,
    is_short_input,
)
from olivia.core.language.filters import apply_willow
from olivia.core.language.mirror import FALLBACK_MIRROR, Utterance, utterance_kind
from olivia.core.language.spacing import fill as spaced_fill
from olivia.core.memory.notes import NoteCues, load_note_cues
from olivia.core.memory.state import KIT_MAX, CarriedState, KitEntry, restore_sampler
from olivia.core.methods.bandit import Feedback
from olivia.core.methods.contraindications import (
    BEREAVEMENT_CONTRAINDICATION,
    ActiveContext,
    SessionContraindications,
)
from olivia.core.methods.solver import (
    M0_ACTION_ID,
    AllowedSet,
    SolverInput,
    active_contraindications,
    allowed_actions,
    build_plan,
    info_cards,
)
from olivia.core.models import (
    UNKNOWN_COUNTRY,
    ActionType,
    CrisisLevel,
    HelpStage,
    PerceptionContext,
    PersonaProfile,
    PersonaSpectrum,
    SessionState,
    UserRegion,
)
from olivia.core.perception.externalize import (
    Externalizer,
    ExternalizeStatus,
    ExternalizeText,
    load_externalize_text,
)
from olivia.core.perception.introspector import (
    Introspector,
    MirrorAnswer,
    MirrorAnswers,
    MirrorStatus,
    SchemaMirror,
    load_introspection_lexicon,
    load_mirror_lines,
)
from olivia.core.perception.lexicon import load_perception_lexicon
from olivia.core.perception.model_heads import ModelHeads
from olivia.core.perception.rule_stub import FALLBACK_EMOTION, RuleStub, dominant_spectrum
from olivia.core.perception.signals import Answer, Command, NoteRecall, TurnSignals
from olivia.core.perception.student import RiskChoice, choose_risk_model
from olivia.core.resources.bundle import load_hotlines_bytes
from olivia.core.resources.card import CardMode, ResourceCard
from olivia.core.resources.resolver import resolve
from olivia.core.resources.store import LineKind, ResourceStore, parse_store
from olivia.core.safety.crisis import (
    MODEL_FAILURE,
    CrisisAssessment,
    ReportedRisk,
    RiskModel,
    SafetyScreen,
)
from olivia.core.safety.intent_check import IntentAnswer, read_answer
from olivia.core.safety.lexicon import SafetyLexicons, load_safety_lexicons
from olivia.core.safety.normalize import normalize
from olivia.core.safety.red_flags import RedFlagDetector, SessionRedFlags
from olivia.core.safety.tracker import CrisisStatus, CrisisTracker
from olivia.core.taxonomy import Taxonomy
from olivia.core.yaml_load import safe_load

FALLBACK_SPECTRUM: Final = "02"
TABOO_RETRIES: Final = 5
_SOMATIC_KEY: Final = "arousal.thresholds.somatic_priority"
# F6b: a heavy turn gets no unasked S_clarify lens (``Session._heavy``). Arousal above the
# line where the solver stops exploring (taxonomy ``exploration_allow``; <= 0.60 is still
# calm) is heavy, and so is grief or loss: the trauma, stress and bereavement spectrum.
_HEAVY_AROUSAL_KEY: Final = "arousal.thresholds.exploration_allow"
_HEAVY_SPECTRUM: Final = "06"
_LOSS_SITUATIONS: Final = "SIT-06-"
_EMPOWER_EXITS: Final = frozenset(
    {Reason.EMPOWER_TO_CLOSING, Reason.EMPOWER_UNHELPFUL, Reason.EMPOWER_AVERSION}
)
_COMMAND_FEEDBACK: Final = {
    Command.DONE: Feedback.HELPFUL,
    Command.NOT_NOW: Feedback.NOT_NOW,
    Command.UNHELPFUL: Feedback.UNHELPFUL,
}


_NO_FOLLOWUP_STAGES: Final = frozenset({HelpStage.S_CRISIS, HelpStage.S_HAVEN})
# Where a question about a therapy is answered at all (as the solver's info stages).
_ASK_REPLY_STAGES: Final = frozenset(
    {HelpStage.S_EXPLORE, HelpStage.S_CLARIFY, HelpStage.S_EMPOWER, HelpStage.S_CLOSING}
)
# Stages whose replies a leave-taking turn does not replace (F5d).
_OWN_REPLY_STAGES: Final = frozenset({HelpStage.S_CRISIS, HelpStage.S_CLOSING, HelpStage.S_READY})
# The m0 situation whose direct request gets ``followups.grief_request`` (F10).
_PROLONGED_GRIEF: Final = "SIT-06-04"
# Cue id added to an answer turn the session reads as L2 after the D3 question.
SAFETY_CHECK_CUE: Final = "SAFETY_CHECK_L2"
# Cue id added to an answer turn the session reads as L2 after the question a model-only
# alarm asked (owner decision 2026-10-26).
MODEL_CHECK_CUE: Final = "MODEL_CHECK_L2"
MODEL_CHECK: Final = "model"
"""``inspect["safety_check_by"]`` on the turn a model-only alarm asks and on its answer."""
CLOSING_REOPEN: Final = "CLOSING_REOPEN"
"""``inspect["reason"]`` when new content after the closing ritual reopens S_explore."""
DEGRADED: Final = "DEGRADED"
"""``inspect["reason"]`` of a reply from the SDD §10.1 fallback (``Session.turn``)."""
# A short message asking to wipe OLIVIA's own memory ("清空所有记忆", "把聊天记录都删了"),
# matched on the normalized text. Longer messages, or wiping a memory *of* someone
# ("清空关于他的记忆"), are ordinary conversation.
_FORGET_RE: Final = re.compile(
    r"(?:清空|清除|删除|删掉|删光|抹掉|忘掉|忘记)(?:你|我们)?的?(?:所有|全部|一切)?的?"
    r"(?:记忆|记录|聊天记录|数据)"
    r"|把(?:你|我们)?的?(?:所有|全部)?的?(?:记忆|记录|聊天记录|数据)(?:都|全)?"
    r"(?:清空|清除|删除|删掉|删了|忘掉|忘了)"
)
_FORGET_MAX_CHARS: Final = 20
# dogfood I3: S_clarify names a need at most once in this many of its replies.
_NEED_GAP: Final = 3
# dogfood I2: the contraindication whose masked practices and symptoms the session hears.
_CARDIO: Final = "CARDIORESPIRATORY_INSTABILITY"
# dogfood I2: "why not" is read up to this many turns after the masked practice was named.
_WHY_WINDOW: Final = 2
_GRIEF_EMOTION: Final = "grief"
_BEREAVEMENT: Final = "SIT-06-04"
_AFTER_LOSS_NO_LENS: Final = frozenset({"06", "07"})
# 第 6 条: "我该怎么跟她说" is read as about the other person up to this many turns after
# the user reported their risk.
_THIRD_PARTY_WINDOW: Final = 3
# 第 11 条: at most one line of care after a crisis in this many turns.
_CARE_GAP: Final = 3


class FeedbackSource(StrEnum):
    """Where this turn's feedback came from (``inspect["feedback_source"]``)."""

    COMMAND = "command"
    """A slash command."""
    PHRASE = "phrase"
    """A natural-language feedback or aversion phrase."""
    CONFIRMED = "confirmed"
    """A yes to the clarification question asked on the turn before."""


class AgeGateRefusedError(Exception):
    """The profile is a minor's refusal record or does not confirm 18+ (NG-3)."""


class ReplyKind(StrEnum):
    CRISIS = "CRISIS"
    REFERRAL = "REFERRAL"
    HAVEN = "HAVEN"
    NORMAL = "NORMAL"
    CARD = "CARD"
    INFO = "INFO"
    SAFETY_CHECK = "SAFETY_CHECK"
    """The direct question about intent with the region's resource lines (decision D3)."""
    RESOURCES = "RESOURCES"
    """A few lines and the region's numbers, outside the crisis flow (2026-10-26): the
    resources a user asks for, the card for someone else's reported risk, or every reply
    after the user said they are under 18."""


@dataclass(frozen=True)
class TurnResult:
    reply: str
    reply_kind: ReplyKind
    stage: HelpStage
    crisis_level: CrisisLevel
    in_crisis: bool
    resource_card: ResourceCard | None
    action_id: str | None
    """The newly shown exercise or m0 (``EMOTIONAL_HOLDING_PRESENCE``); None otherwise."""
    referral_flags: tuple[str, ...]
    """Red-flag codes whose referral card is in this reply."""
    inspect: dict[str, object]
    """The ``--inspect`` panel data (ruling 27): ids, levels and numbers, never user text."""


@dataclass(frozen=True)
class Farewell:
    """The goodbye of a conversation that ends in the crisis flow (``Session.farewell``)."""

    text: str
    level: CrisisLevel
    """L2 or L3: what the cross-session care marker records (``chang/care.py``)."""


@dataclass(frozen=True)
class _Shared:
    """Stateless, read-only parts shared by every session over one taxonomy."""

    lexicons: SafetyLexicons
    screen: SafetyScreen
    stub: RuleStub
    detector: RedFlagDetector
    language: LanguageData
    store: ResourceStore
    hotline_source: str
    hotline_reason: str | None
    """Why the built-in hotline data was used instead of an override (``None``: override)."""
    introspector: Introspector
    mirror_answers: MirrorAnswers
    mirror_lines: Mapping[str, tuple[str, ...]]
    externalize: ExternalizeText
    note_cues: NoteCues
    """The recorder's "记住：……" cues: a note turn gets no information card (F5b)."""
    privacy_answer: str = ""
    """``privacy.yaml`` ``chat_answer``: the reply to "你会把我说的话存下来吗" (I8)."""


@lru_cache(maxsize=4)
def _shared(tax: Taxonomy, today_iso: str, hotline_updates: Path | None = None) -> _Shared:
    lexicons = load_safety_lexicons(tax)
    introspection = load_introspection_lexicon(tax)
    today = datetime.fromisoformat(today_iso).date()
    bundle = load_hotlines_bytes(hotline_updates, today=today)  # GEO-08, F14
    return _Shared(
        lexicons=lexicons,
        screen=SafetyScreen(tax, lexicons),
        stub=RuleStub(tax, load_perception_lexicon(tax)),
        detector=RedFlagDetector(tax, lexicons),
        language=load_language_data(tax),
        store=parse_store(safe_load(bundle.data)),
        hotline_source=bundle.source,
        hotline_reason=bundle.reason,
        introspector=Introspector(introspection),
        mirror_answers=introspection.answers,
        mirror_lines=load_mirror_lines(tax),
        externalize=load_externalize_text(tax),
        note_cues=load_note_cues(),
        privacy_answer=load_privacy_text().chat_answer.strip(),
    )


@dataclass(frozen=True)
class _Pending:
    """A shown card waiting for feedback."""

    action_id: str
    spectrum: str
    stage: HelpStage
    stabilization: bool = False
    """The card came from the stabilization whitelist (an S_explore card, an L1 turn or
    acute arousal): a card asked for in its place comes from that whitelist too (F16b)."""


@dataclass
class _Rendered:
    reply: str
    kind: ReplyKind
    action_id: str | None = None
    referral_flags: tuple[str, ...] = ()
    card: ResourceCard | None = None
    candidates: tuple[str, ...] = ()
    chosen: str | None = None
    pending: _Pending | None = None
    info_id: str | None = None
    plan_shown: bool = False
    plan_reminded: bool = False


@dataclass(frozen=True)
class _FollowUp:
    """What the session made of a turn's follow-up signals before the state machine ran."""

    signals: TurnSignals
    """The signals the state machine sees: an accepted phrase or answer becomes the
    command (or ``intent_confirmed`` / ``direct_request``) it stands for."""
    source: FeedbackSource | None = None
    """The source if the waiting card gets feedback on this turn."""
    clarify: bool = False
    """An unclear reply to the waiting card: ask once whether to shelve it."""
    recall: bool = False
    """Show a shelved card again."""
    kit_empty: bool = False
    """A recall request with nothing in the kit."""
    closing_declined: bool = False
    """A no to the S_closing question."""


# A composer returns (text, mirror it used) or None when the output gate blocked it.
_Composer = Callable[[], tuple[str, str] | None]


class Session:
    """One conversation. Build it with :meth:`open`; call :meth:`turn` once per message."""

    def __init__(
        self,
        tax: Taxonomy,
        profile: PersonaProfile,
        shared: _Shared,
        screen: SafetyScreen,
        *,
        rng: random.Random,
        now: Callable[[], datetime],
        risk: RiskChoice | None = None,
        started_at: datetime | None = None,
        carried: CarriedState | None = None,
        safety_plan: SafetyPlan | None = None,
        suggest_safety_plan: bool = False,
    ) -> None:
        self._tax = tax
        self._profile = profile
        self._shared = shared
        self._screen = screen
        self._risk = risk if risk is not None else choose_risk_model()
        self._heads = None if self._risk.student is None else ModelHeads(tax, self._risk.student)
        self._rng = rng
        self._now = now
        self._somatic = tax.threshold(_SOMATIC_KEY)
        self._heavy_arousal = tax.threshold(_HEAVY_AROUSAL_KEY)
        self._stabilization_only = False
        self._tracker = CrisisTracker(tax, shared.lexicons)
        self._red_flags = SessionRedFlags(shared.detector, profile.clinical_history)
        self._contra = SessionContraindications(tax, profile.contraindications)
        self._context = ActiveContext()
        self._sampler = restore_sampler(tax, carried.bandit if carried is not None else None)
        # The kit from earlier sessions (oldest first); this session's shelves live in
        # ``SessionState.user_shelved_actions``. ``_shelved_at`` keeps when each was shelved.
        kit = carried.kit if carried is not None else ()
        self._carried_kit: list[str] = list(dict.fromkeys(e.action_id for e in kit))
        self._shelved_at: dict[str, datetime] = {e.action_id: e.shelved_at for e in kit}
        # The profile's persona picks the reply templates and word windows (ONB-03, D-1).
        language = shared.language.for_persona(profile.persona_spectrum)
        self._engine = LanguageEngine(tax, rng=rng, data=language, lexicons=shared.lexicons)
        self._state = SessionState(session_id=uuid4())
        self._last_status: CrisisStatus | None = None
        self._pending: _Pending | None = None
        self._clarifying = False
        # The last turn asked the D3 question, so the next turn is its answer.
        self._asking = False
        # Owner decisions 2026-10-26: the session's first model-only alarm may ask the
        # question (``_model_asked`` is set by any model-only alarm); ``_asking_model``
        # marks the pending question as that one.
        self._model_asked = False
        self._asking_model = False
        # Safety replies round 2 (2026-10-26): the user said they are under 18 in this
        # session (第 5 条; never written anywhere) and was told so once; the highest crisis
        # entry level of this session (第 11 条); the turn count when the user last reported
        # someone else's risk (第 6 条), when the last resource card was shown (第 7 条) and
        # when the last line of care after a crisis was added (第 11 条).
        self._minor = False
        self._minor_told = False
        self._crisis_seen: CrisisLevel | None = None
        self._third_party_turn: int | None = None
        # Round 3: the last report of someone else's risk was urgent (its follow-ups keep
        # the emergency numbers).
        self._third_party_urgent = False
        self._resources_turn: int | None = None
        self._care_turn: int | None = None
        # The user said no to the D3 question this session (kept across sessions by A3/B3).
        self._gentle_care = False
        # This session opened with the A3 check-in greeting (``care_greeting``).
        self._care_greeting = False
        self._referred: set[str] = set()
        self._gate_notes: list[str] = []
        # The mirror kind this turn overrides (F10: Utterance.HAVEN_EXIT), else None.
        self._utterance: Utterance | None = None
        self._last_spectrum: str | None = None
        self._lens_shown = False
        start = started_at if started_at is not None else now()
        self._started_at = start
        zone = profile.region.timezone if profile.region is not None else None
        self._wellbeing = Wellbeing(tax, zone, start)
        # The schema mirror (decision D4) asks only in model mode.
        self._mirror = SchemaMirror(
            shared.mirror_answers, shared.mirror_lines, enabled=self._heads is not None
        )
        # Externalization naming (C3) offers only where the mirror could ask.
        self._externalize = Externalizer(
            shared.externalize, shared.mirror_answers, enabled=self._heads is not None
        )
        self._mirror_turn: int | None = None
        # The user's own safety plan (B10): shown in crisis replies only, never written.
        # S5 (2026-10-26): in full once per crisis, then one reminder line; the people of
        # section 4 also go into a crisis farewell.
        self._plan_block = crisis_block(safety_plan)
        self._plan_reminder = crisis_reminder(safety_plan)
        self._plan_people = farewell_people(safety_plan)
        self._plan_shown_in_crisis = False
        # The last reply sent, so a goodbye never repeats it word for word (I7).
        self._last_reply: str | None = None
        self._suggest_plan = suggest_safety_plan
        self._plan_suggested = False
        # The risk model scored L3 in this crisis but its L3 is not plan evidence, so the
        # flow stays L2: the card still leads with the emergency numbers (owner decision
        # 2026-10-24). Cleared when the crisis ends.
        self._urgent = False
        # The last closing ritual or after-close line, never sent twice in a row.
        self._last_closing: str | None = None
        # The S_haven line said how to leave the haven (F9, FSM-15): once per session.
        self._haven_hinted = False
        # The how-to-confirm hint was shown in this crisis (F5b): once per crisis.
        self._confirm_hinted = False
        # The last referral card: its codes, the turn it was shown on and how many times in
        # a row it has come again (F5b).
        self._last_referral: tuple[tuple[str, ...], int] | None = None
        self._referral_again = 0
        # Red flags heard in this conversation's text (I5): a profile flag alone is referred
        # with a plan, not on the first turn of every session.
        self._text_flags: set[str] = set()
        # The turn (count before it) on which a masked practice was explained (I2).
        self._masked_turn: int | None = None
        self._cardiac_noted = False
        # S_clarify replies since the last one that named a need (I3): due at _NEED_GAP.
        self._since_need = _NEED_GAP
        self._need_due = True
        self._need_named = False
        # I4: a loss was talked about; lens topics heard (method ids only).
        self._loss_seen = False
        self._lens_topics: set[str] = set()

    @classmethod
    def open(
        cls,
        tax: Taxonomy,
        profile: PersonaProfile,
        *,
        rng: random.Random,
        now: Callable[[], datetime],
        model: RiskModel | None = None,
        student: bool = False,
        carried: CarriedState | None = None,
        safety_plan: SafetyPlan | None = None,
        suggest_safety_plan: bool = False,
        hotline_updates: Path | None = None,
    ) -> Session:
        """Start a session; ``now`` is the clock (timezone-aware) for cards and the bandit.

        ``carried`` (``memory/state.py``, B3) seeds the sampler and the kit from an earlier
        session; without it the session starts from the priors with an empty kit.

        The crisis screen's Stage 2 uses ``model`` when given; ``student=True`` uses the
        packaged perception student (``perception/student.py``); otherwise, or when the
        student fails to load, the rule model runs alone. An injected model or the student
        can only raise the rule level and stays capped at L2. ``inspect`` reports which one
        ran. ``student`` defaults to off here; the product default (model mode, owner
        decision 2026-10-24) is decided by the CLI, ``olivia chat`` (``--rules`` opts
        out). With the student on, its other heads also refine perception
        (``perception/model_heads.py``); an injected model leaves perception to the rules.

        ``safety_plan`` is the user's saved plan (B10), shown in crisis replies;
        ``suggest_safety_plan`` lets the first S_closing reply mention ``olivia safety-plan``
        once (the CLI passes it when no plan exists and none was suggested before).

        ``hotline_updates`` is the folder that may hold a signed hotline update
        (``resources.bundle.override_dir_location()``, GEO-08 / F14); it is used only when
        its signature verifies and it is newer than the built-in data. ``None`` (the
        default) uses the built-in data and reads no user directory.

        Raises :class:`AgeGateRefusedError` for a refusal record or any profile that does
        not confirm 18+, and lets every data-loading error through.
        """
        if profile.is_age_gate_refusal or profile.age_confirmed_18_plus is not True:
            raise AgeGateRefusedError("no session without a confirmed adult profile")
        moment = now()
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        shared = _shared(tax, moment.date().isoformat(), hotline_updates)
        risk = choose_risk_model(model, student=student)
        screen = (
            shared.screen
            if risk.model is None
            else shared.screen.with_model(risk.model, model_plan_evidence=False)
        )
        return cls(
            tax,
            profile,
            shared,
            screen,
            rng=rng,
            now=now,
            risk=risk,
            started_at=moment,
            carried=carried,
            safety_plan=safety_plan,
            suggest_safety_plan=suggest_safety_plan,
        )

    @property
    def minor_disclosed(self) -> bool:
        """The user said in this session that they are under 18 (问题单第 5 条): from then
        on every reply outside the crisis flow is resources and a goodbye. Kept in memory
        only; the session never changes the profile, and a caller that wants to record an
        age must first ask the user to confirm it."""
        return self._minor

    @property
    def safety_plan_suggested(self) -> bool:
        """This session's reply has carried the ``olivia safety-plan`` suggestion (B10)."""
        return self._plan_suggested

    @property
    def risk_model_fallback(self) -> str | None:
        """Why the packaged student was asked for but the rules screen alone (E5): missing,
        unreadable or failing verification. ``None`` when nothing fell back."""
        return self._risk.reason

    @property
    def state(self) -> SessionState:
        return replace(self._state, user_shelved_actions=list(self._state.user_shelved_actions))

    def turn(self, text: str) -> TurnResult:
        """One user turn. The crisis screen runs first; if anything after it raises, the
        user still gets a reply (SDD §10.1): the minimal crisis card with every number
        when the screen said L2/L3, the session is in a crisis or the D3 answer was due,
        otherwise the persona's slot-free presence line. Nothing is logged."""
        now = self._now()
        self._gate_notes = []
        self._utterance = None

        assessment = self._screen.assess(text)
        asking = self._asking
        try:
            return self._turn(text, now, assessment)
        except Exception as exc:  # SDD §10.1: degrade, never leave the user without a reply
            return self._degraded(assessment, now, asking=asking, error=type(exc).__name__)

    def _turn(self, text: str, now: datetime, assessment: CrisisAssessment) -> TurnResult:
        model_answer = self._asking_model
        self._asking_model = False
        assessment, answer = self._answer_safety_check(text, assessment, model=model_answer)
        model_level, model_score = self._risk.take_turn()
        # What the screen said, for ``inspect`` and the reported level of a question turn.
        screened = assessment
        # 问题单第 6 条: someone else's risk, reported by the user. The user is not put into
        # the crisis flow for it (nor asked the D3 question); the reply is the region's card
        # to pass on, with the emergency numbers first when the words carry a plan.
        reported = self._reported_risk(text, assessment, answer)
        if reported is not None:
            assessment = self._for_someone_else(assessment)
        model_ask = self._model_only_alarm(assessment, answer, model_level, model_score)
        if model_ask:
            # Owner decisions 2026-10-26: the rules found nothing and the student is unsure,
            # so ask once first. The turn goes on as an L1 only the model gives (no crisis,
            # no L1 run).
            self._asking_model = True
            assessment = replace(assessment, level=CrisisLevel.L1)
        perception, signals = self._shared.stub.perceive(text, assessment)
        perception = self._shared.introspector.apply(text, perception)
        before = self._last_status
        # The rule stub reports valence 0.0 under the fallback emotion when no emotion word
        # matched: that is no evidence, which the tracker never reads as an improvement.
        evidence = not (
            perception.fine_grained_emotion == FALLBACK_EMOTION and perception.valence == 0.0
        )
        paused = self._model_pause(assessment, model_level, model_score)
        tracked = (
            replace(assessment, level=CrisisLevel.L1, uncapped_level=None) if paused else assessment
        )
        status = self._tracker.observe(tracked, text, perception.valence if evidence else None)
        self._last_status = status
        if status.in_crisis:
            entry = max(CrisisLevel.L2, status.entry_level or CrisisLevel.L2)
            self._crisis_seen = max(entry, self._crisis_seen or entry)
        if signals.minor_disclosure:
            self._minor = True
        # The tracker heard an explicit safety confirmation on this crisis turn.
        confirmed = (
            status.in_crisis
            and not status.awaiting_confirmation
            and before is not None
            and before.in_crisis
            and before.awaiting_confirmation
        )
        if not status.in_crisis:
            self._urgent = False
        elif model_level == CrisisLevel.L3.name:
            self._urgent = True
        if not status.in_crisis or status.just_entered:
            self._confirm_hinted = False
            self._plan_shown_in_crisis = False
        if self._heads is not None:
            perception = self._heads.refine(text, perception)
        flags = self._red_flags.observe(text)
        self._text_flags |= self._shared.detector.detect(text)
        self._context = self._contra.observe(signals, perception, status, flags)
        ask = model_ask or (answer is None and assessment.asks_intent and not status.in_crisis)
        # The request on an ask turn is not a request for an exercise, and the answer to the
        # question is not an answer to any other question.
        if ask:
            signals = replace(signals, direct_request=False, answer=None)
        elif answer is not None:
            signals = replace(signals, answer=None)
        self._asking = ask
        # A turn calm enough for the schema mirror: no crisis, no L1 screen, below the
        # somatic line, not the D3 question or its answer. The L1 test is the rule screen's
        # call, as for the D3 answer: a model's score band alone does not make "是的" L1.
        shared_screen = self._shared.screen
        rules = assessment if self._screen is shared_screen else shared_screen.assess(text)
        # Round 3 (B2a): from L1 up, by any reading, the reply never says the words back.
        self._engine.note_risk(max(screened.level, assessment.level, rules.level))
        calm = (
            not status.in_crisis
            and rules.level < CrisisLevel.L1
            and perception.arousal < self._somatic
            and not ask
            and answer is None
        )
        readable = calm and self._state.current_stage is HelpStage.S_CLARIFY
        mirror_answer = self._mirror.answer(text, readable=readable)
        naming = self._externalize.answer(
            text, readable=readable, stub_declined=signals.answer is Answer.DECLINE
        )
        naming_status = None if naming is None else naming.status
        mirror_status = None if mirror_answer is None else MirrorStatus(mirror_answer.value)
        if mirror_answer is MirrorAnswer.CONFIRMED:
            signals = replace(signals, core_belief_confirmed=True)
        self._mirror.observe(perception.detected_schemas, counts=calm)
        self._externalize.observe(
            perception.detected_schemas, perception.detected_distortions, counts=calm
        )
        pending = self._pending
        follow = self._follow_up(signals, status, assessment.level, pending)
        signals = follow.signals
        before_turns = self._state.global_turn_count
        # dogfood I2: a practice the user's own heart or breathing condition masks, named on
        # a calm turn, is a request for a practice (another one while a card waits, as F16b
        # reads a named practice), never feedback; the reply says gently why not that one.
        masked = (
            bool(signals.contraindicated_practice & self._context.contraindications)
            and not status.in_crisis
            and assessment.level < CrisisLevel.L1
            and rules.level < CrisisLevel.L1
            and signals.command is None
            and not ask
            and answer is None
        )
        if masked:
            signals = replace(
                signals,
                direct_request=True,
                another_method=True,
                feedback=None,
                feedback_unclear=False,
            )
            self._masked_turn = before_turns
        # A command, or a pick from the naming offer (C3), is not something to mirror back.
        mirror_text = "" if signals.command is not None or naming is not None else text
        # Two meta turns outside a crisis: a feedback command with no card waiting for it,
        # and a request in the chat to wipe the memory. Each gets one short line, never a
        # mirror, and holds the stage (the command is not passed on).
        meta = not status.in_crisis and assessment.level < CrisisLevel.L2
        no_pending = meta and signals.command is not None and pending is None
        forget = (
            meta
            and not no_pending
            and assessment.level < CrisisLevel.L1
            and not ask
            and answer is None
            and _asks_to_forget(text)
        )
        # dogfood I8: "你会把我说的话存下来吗" gets the privacy facts; I2: "为什么不行" right
        # after a masked practice was explained gets a little more. Meta turns, as above.
        calm_meta = (
            meta
            and not no_pending
            and not forget
            and assessment.level < CrisisLevel.L1
            and not ask
            and answer is None
        )
        # Round 3 (2026-10-27, re-test r3): /help, /帮助 or /? lists the chat commands.
        helping = normalize(text) in _HELP_COMMANDS
        help_now = helping and not status.in_crisis and not ask
        privacy = (
            calm_meta
            and not help_now
            and signals.privacy_question
            and bool(self._shared.privacy_answer)
        )
        why = (
            calm_meta
            and not privacy
            and not masked
            and signals.why_not
            and self._masked_turn is not None
            and before_turns - self._masked_turn <= _WHY_WINDOW
        )
        if no_pending:
            signals = replace(signals, command=None)
        # Safety replies round 2 (2026-10-26; drafts pending G-0), never in a crisis or on
        # the D3 question: after the user said they are under 18 (第 5 条) every reply is
        # resources and a goodbye; someone else's reported risk gets the card to pass on
        # (第 6 条); a request for a hotline, or a follow-up about one within two turns of a
        # resource card, gets the region's resources (第 7 条).
        open_turn = not status.in_crisis and not ask
        minor_now = open_turn and self._minor
        # Round 3: a few turns after the card for someone else's risk, "我联系不上他" or
        # "我该怎么办" gets the card again with what to do, never an ordinary mirror; any rule
        # cue of the user's own takes the user's flow instead.
        third_follow = (
            open_turn
            and reported is None
            and self._third_party_turn is not None
            and before_turns + 1 - self._third_party_turn <= _THIRD_PARTY_WINDOW
            and rules.level is CrisisLevel.L0
            and assessment.level < CrisisLevel.L2
            and (
                signals.keep_secret
                or signals.advice_request
                or signals.third_party_unreachable
                or signals.third_party_question
            )
        )
        third_now = open_turn and not minor_now and (reported is not None or third_follow)
        # Round 3: more follow-ups (cost, hours, language, real, more numbers, a place),
        # within two turns of a resource card when the message asks or names a place, or
        # with a phone word in a question ("12356收费吗") at any time.
        recent_card = self._resources_turn is not None and before_turns - self._resources_turn <= 2
        asked = _asks(text)
        followup = _hotline_followup(signals) and (
            (recent_card and (asked or signals.hotline_anonymous or signals.hotline_abroad))
            or (recent_card and signals.hotline_place is not None)
            or (signals.hotline_words and asked)
        )
        hotline_now = (
            open_turn and not minor_now and not third_now and (signals.hotline_request or followup)
        )
        transition = step(
            self._tax,
            self._state,
            TurnInput(perception, status, signals, self._profile.persona_spectrum),
        )
        if no_pending or forget or privacy or why or minor_now or hotline_now or help_now:
            transition = self._held(transition)
        # Ruling 5 at L1: a requested card comes from the stabilization whitelist only (F2a).
        # A masked calming practice asked for by name (dogfood I2) is replaced by one from
        # the same whitelist: slow breathing for 4-7-8, never a thought record.
        self._stabilization_only = transition.stabilization_only or masked
        spectrum = dominant_spectrum(perception.distress_vector)
        reason = transition.reason.value
        if self._reopens(transition, signals, follow, perception, spectrum) and not (
            no_pending
            or forget
            or privacy
            or why
            or ask
            or answer is not None
            or minor_now
            or hotline_now
            or third_now
            or help_now
        ):
            transition = self._reopen(transition, perception)
            reason = CLOSING_REOPEN
        self._state = transition.state
        stage = transition.state.current_stage
        # The turn that leaves S_haven on the user's words (F10): the reply does not echo
        # "换个话题吧" back; its mirror slot is a gentle ``HAVEN_EXIT`` acknowledgement.
        self._utterance = (
            Utterance.HAVEN_EXIT if transition.reason is Reason.HAVEN_EXIT_ASKED else None
        )
        feedback = self._feedback_for(pending, transition, signals)
        # A request for another method, or for a named practice, while a card waits (F16b):
        # the waiting card goes into the kit (as /not-now) and another one is offered.
        switch = self._switches(
            pending, feedback, transition, signals, perception, flags, status, assessment, rules
        ) and not (ask or answer is not None)
        if switch:
            feedback = Feedback.NOT_NOW
        if spectrum is not None:
            self._last_spectrum = spectrum
        self._observe_topics(text, perception, spectrum)
        note = self._shared.note_cues.find(text) is not None
        # Leaving for now with no card waiting (F5d): a short goodbye, nothing else. The
        # rules screen the turn L0; an L1 only an injected model's score band gives (F10,
        # as the tracker's model-only L1) does not hold the goodbye back.
        leaving = (
            signals.leave_taking
            and pending is None
            and signals.command is None
            and not note
            and not status.in_crisis
            and assessment.level <= CrisisLevel.L1
            and rules.level is CrisisLevel.L0
            and not ask
            and answer is None
            and stage not in _OWN_REPLY_STAGES
        )
        info = None
        if not (leaving or privacy or why or minor_now or third_now or hotline_now or help_now):
            info = self._info_choice(
                stage, perception, flags, signals, status, assessment.level, feedback, transition
            )
        if note:
            # A note turn is answered by the recorder's confirmation, never with a card.
            info = None
        # A question about a note (F15): only on a calm turn, never in a crisis, with an
        # L2/L3 screen or an L1 the rules give (an L1 only an injected model gives does not
        # hold it back, as for the goodbye; F16a), and not when the turn asks for anything
        # else. The recorder looks the notes up; an explicit one is answered by it, so it
        # gets no information card.
        recall = signals.note_recall
        if (
            note
            or status.in_crisis
            or assessment.level >= CrisisLevel.L2
            or rules.level >= CrisisLevel.L1
            or ask
            or answer is not None
            or no_pending
            or forget
            or privacy
            or why
            or leaving
            or signals.command is not None
            or signals.direct_request
            or signals.kit_recall
            or signals.therapy_question is not None
            or stage is HelpStage.S_CRISIS
        ):
            recall = None
        if recall is NoteRecall.EXPLICIT:
            info = None
        # A red-flag user asks what a therapy is (F9): the closure allows no explainer,
        # so one neutral line and the referral card again, never an ordinary reply.
        referred_question = (
            info is None
            and not leaving
            and not note
            and bool(flags)
            and signals.therapy_question is not None
            and not signals.direct_request
            and feedback is None
            and not status.in_crisis
            and assessment.level < CrisisLevel.L1
            and stage in _ASK_REPLY_STAGES
        )
        # The waiting card is still on screen, in the stage it was shown in.
        still_waiting = (
            pending is not None
            and feedback is None
            and transition.previous is pending.stage
            and stage is pending.stage
        )

        reflective = (
            stage is HelpStage.S_CLARIFY
            and calm
            and not flags
            and not transition.state.pure_listening_locked
            # SILENT_ANCHOR asks no questions and its reply is one paragraph (plan D-1).
            and self._profile.persona_spectrum is not PersonaSpectrum.SILENT_ANCHOR
        )
        mirror_schema = self._mirror.choose() if reflective else None
        turn_no = transition.state.global_turn_count
        # The mirror first: never on its turn or its answer's, and not after a no to it.
        offer_naming = (
            reflective
            and mirror_schema is None
            and self._mirror.status is not MirrorStatus.DECLINED
            and (self._mirror_turn is None or turn_no > self._mirror_turn + 1)
            and self._externalize.due()
        )

        templates = self._engine.data.templates
        # dogfood I3: S_clarify names a need at most once in _NEED_GAP + 1 of its replies.
        self._need_due = self._since_need >= _NEED_GAP
        self._need_named = False
        # Only the plain composed reply of the current stage carries a wellbeing prompt.
        ordinary = False
        reached_out = False
        heard = False
        if stage is HelpStage.S_CRISIS:
            # After a confirmation the crisis waits to end: no second safety question.
            waiting = status.in_crisis and not status.awaiting_confirmation
            # Round 3: a calm turn of new words (no rule cue, below L2, not a command).
            calm_words = (
                status.in_crisis
                and not status.just_entered
                and status.level < CrisisLevel.L2
                and assessment.rule_clear
                and signals.command is None
                and not text.lstrip().startswith("/")
            )
            hint = (
                status.in_crisis
                and status.awaiting_confirmation
                and not status.just_entered
                and status.level < CrisisLevel.L2
                and not self._confirm_hinted
                # Round 3: the first calm turn of new words gets it too ("我现在在宿舍，
                # 室友也在" is no confirmation, and the user may not know what is).
                and (self._engine.reassures(text) or calm_words)
            )
            reaches = status.in_crisis and self._reaches_out(text, assessment)
            if waiting and not confirmed and calm_words:
                # Round 3: waiting to end after a confirmation, a calm turn gets an answer
                # to its words and one line of every number (SDD §8.2's compact card); no
                # safety question again.
                rendered = self._crisis_waiting(text, status, now, signals, stage)
                heard = True
            else:
                rendered = self._crisis(status, now, confirmed=waiting, hint=hint)
                if hint:
                    self._confirm_hinted = True
                if confirmed:
                    # The user just said they are safe: say we heard it, then the card.
                    self._add_line(rendered, templates.safety_confirmed, stage, first=True)
                elif reaches:
                    # S5: the user will contact someone; affirm it first, the card stays.
                    reach = self._engine.data.render.crisis_reach_out
                    self._add_line(rendered, reach, stage, first=True)
                    reached_out = True
                elif helping:
                    help_text = self._engine.data.render.chat_help
                    self._add_line(rendered, (help_text,), stage, first=True)
                elif calm_words:
                    # Round 3: new words in the crisis flow are answered first (re-test r4:
                    # "我明天想去学校的心理中心看看" got only the card).
                    heard = self._lead_with_heard(rendered, text, signals, stage)
        elif ask:
            rendered = self._safety_check(stage, now)
        elif help_now:
            rendered = self._followup((self._engine.data.render.chat_help,), stage)
        elif minor_now and not leaving:
            rendered = self._minor_reply(stage, now)
        elif third_now:
            rendered = self._third_party_reply(stage, now, reported, signals)
            self._third_party_turn = turn_no
        elif hotline_now:
            rendered = self._hotline_reply(stage, now, signals)
        elif no_pending:
            rendered = self._followup(templates.no_pending_feedback, stage)
        elif forget:
            rendered = self._followup(templates.forget_hint, stage)
        elif privacy:
            rendered = self._followup((self._shared.privacy_answer,), stage)
        elif why:
            rendered = self._followup(self._notice("masked_practice_why"), stage)
        elif leaving:
            rendered = self._closing(self._after_close(now), stage)
        elif follow.clarify and still_waiting:
            rendered = self._followup(templates.clarify_feedback, stage)
            self._clarifying = True
        elif follow.kit_empty and stage not in _NO_FOLLOWUP_STAGES:
            rendered = self._followup(templates.kit_empty, stage)
        elif follow.closing_declined and stage is HelpStage.S_CLOSING:
            rendered = self._followup(templates.closing_declined, stage)
        elif follow.recall and stage is HelpStage.S_EMPOWER:
            rendered = self._offer(
                stage, perception, flags, spectrum, mirror_text, now, recall=True
            )
        elif stage is HelpStage.S_CLOSING and transition.reason is Reason.EMPOWER_TO_CLOSING:
            # The closing ritual says what happened: a shelved card is in the kit now.
            shelved = feedback is Feedback.NOT_NOW
            pool = templates.closing_after_not_now if shelved else templates.closing
            rendered = self._closing(pool, stage, window=True)
            ordinary = True
        elif info is not None:
            rendered = self._info(info, stage, perception, spectrum, mirror_text)
        elif referred_question:
            rendered = self._followup(templates.therapy_referred, stage)
            rendered.referral_flags = tuple(c for c in self._tax.red_flags() if c in flags)
        elif stage in (HelpStage.S_CLOSING, HelpStage.S_READY):
            # After the ritual: a short warm line, never the ritual again.
            rendered = self._closing(self._after_close(now), stage)
        elif stage is HelpStage.S_EMPOWER:
            # A card still waiting for feedback is not replaced: staying in S_empower, or
            # asking for a method right after an S_explore stabilization card, gets the
            # feedback prompt for the card already on screen.
            awaiting = (
                pending is not None
                and feedback is None
                and transition.previous is pending.stage
                and transition.reason in (Reason.STAY, Reason.DIRECT_REQUEST)
            )
            if pending is not None and awaiting:
                rendered = self._with_taboo_filter(self._after_card_prompt, stage)
                rendered.pending = replace(pending, stage=HelpStage.S_EMPOWER)
                # Round 3 (re-test r4): the user's words are answered before the prompt,
                # and so is a clear no to a safety question asked while the card waited.
                if answer is IntentAnswer.DENIED:
                    render = self._engine.data.render
                    self._add_line(rendered, render.check_denied, stage, first=True)
                    heard = True
                elif (
                    signals.command is None
                    and signals.feedback is None
                    and not signals.feedback_unclear
                    and signals.answer is None
                    and not signals.direct_request
                    and not signals.another_method
                    and signals.therapy_request is None
                    and answer is None
                    and rules.level is CrisisLevel.L0
                    and assessment.level < CrisisLevel.L2
                    and _has_words(text)
                    and (
                        signals.help_seeking
                        or utterance_kind(text) in (Utterance.STATEMENT, Utterance.QUESTION)
                    )
                ):
                    heard = self._lead_with_heard(rendered, text, signals, stage)
            else:
                if switch and pending is not None:
                    # Shelve the waiting card first, so the new card is another one; a
                    # card in the whitelist's place keeps to the whitelist (rt084-rt086).
                    self._apply_feedback(pending, Feedback.NOT_NOW, now)
                    self._stabilization_only = self._stabilization_only or pending.stabilization
                rendered = self._offer(
                    stage,
                    perception,
                    flags,
                    spectrum,
                    mirror_text,
                    now,
                    requested=signals.therapy_request,
                    asked=signals.direct_request,
                )
        elif (
            stage is HelpStage.S_EXPLORE
            and (
                perception.arousal >= self._somatic
                # A safety retreat from S_empower (F2a) brings stabilization along; a retreat
                # for aversion does not push another card.
                or (
                    transition.offer_stabilization
                    and transition.reason is not Reason.EMPOWER_AVERSION
                )
            )
            and not transition.state.pure_listening_locked
            and feedback is None
            and not (pending is not None and pending.stage is HelpStage.S_EXPLORE)
        ):
            rendered = self._offer(stage, perception, flags, spectrum, mirror_text, now)
        elif mirror_schema is not None:
            schema: str = mirror_schema
            rendered = self._with_taboo_filter(
                lambda: self._compose_mirror(stage, perception, spectrum, mirror_text, schema),
                stage,
            )
            if rendered.kind is ReplyKind.NORMAL:
                self._mirror.mark_asked()
                mirror_status = MirrorStatus.ASKED
                self._mirror_turn = turn_no
        elif offer_naming:
            rendered = self._offer_naming(stage, perception, spectrum, mirror_text)
            if self._externalize.status is ExternalizeStatus.OFFERED:
                naming_status = ExternalizeStatus.OFFERED
        else:
            named = self._naming_line(stage, perception, calm and not flags, naming_status)
            rendered = self._with_taboo_filter(
                lambda: self._compose_swapped(stage, perception, spectrum, mirror_text, named),
                stage,
            )
            if named is not None and named in rendered.reply:
                self._externalize.mark_named()
            ordinary = True

        # A resource reply (第 5-7 条) is the lines and the card only.
        resources = rendered.kind is ReplyKind.RESOURCES
        if feedback is Feedback.UNHELPFUL and stage is not HelpStage.S_CRISIS and not resources:
            self._add_line(rendered, templates.unhelpful_ack, stage, first=True)
        if switch and rendered.kind is ReplyKind.CARD:
            self._add_line(rendered, templates.card_switched, stage, first=True)
        if masked and stage is not HelpStage.S_CRISIS and not resources:
            # Not the diagnosis, only that the body needs care (dogfood I2, 草稿：待 G-0).
            self._add_line(rendered, self._notice("masked_practice"), stage, first=True)
        if (
            transition.previous is HelpStage.S_HAVEN
            and stage is HelpStage.S_EMPOWER
            and rendered.kind is ReplyKind.CARD
        ):
            # A direct request left the quiet company: say how to get back to it.
            self._add_line(rendered, templates.haven_return, stage, first=False)

        settled = not status.in_crisis and assessment.level < CrisisLevel.L1
        if stage is HelpStage.S_CLARIFY and rendered.kind in (ReplyKind.NORMAL, ReplyKind.INFO):
            self._since_need = 0 if self._need_named else self._since_need + 1
        if (
            ordinary
            and settled
            and signals.advice_request
            and stage in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY)
        ):
            # "我该怎么开口跟妈妈聊": the question is heard (dogfood I1, 草稿：待 G-0).
            self._add_line(rendered, self._notice("advice_heard"), stage, first=True)
        if (
            signals.hotline_pushback
            and not status.in_crisis
            and assessment.level < CrisisLevel.L2
            and stage is not HelpStage.S_CRISIS
            and not ask
            and not resources
        ):
            self._add_line(rendered, self._notice("hotline_heard"), stage, first=True)
        plain = rendered.kind is ReplyKind.NORMAL or stage is HelpStage.S_HAVEN
        prompted = self._wellbeing.prompt(
            rendered.reply,
            now=now,
            stage=stage,
            eligible=ordinary and settled and plain,
            locked=transition.state.pure_listening_locked,
            templates=templates,
            render=lambda variant: self._wellbeing_line(variant, stage),
        )
        rendered.reply = prompted.reply
        if (
            stage is HelpStage.S_HAVEN
            and ordinary
            and settled
            and rendered.kind is ReplyKind.HAVEN
            and prompted.reminder is Reminder.NONE
            and not self._haven_hinted
        ):
            self._hint_haven_exit(rendered, stage)

        if stage is not HelpStage.S_CRISIS and not ask and not status.in_crisis and not resources:
            # A dose or "am I X?" question gets one plain line before the reply (F3).
            boundary = self._engine.boundary_line(text)
            if boundary:
                rendered.reply = f"{boundary}\n\n{rendered.reply}"
        cared = False
        if (
            (self._care_greeting or self._crisis_seen is not None)
            and not status.in_crisis
            and status.level < CrisisLevel.L2
            and stage is not HelpStage.S_CRISIS
            and not ask
            and answer is None
            and rendered.kind not in (ReplyKind.CRISIS, ReplyKind.SAFETY_CHECK, ReplyKind.RESOURCES)
            and (assessment.level is CrisisLevel.L1 or signals.strain)
            and (self._care_turn is None or turn_no - self._care_turn >= _CARE_GAP)
        ):
            # 第 11 条: after a crisis (a care marker, or one in this session) an L1 turn gets
            # one line of care and one line of the region's hotlines; no crisis flow.
            cared = self._lead_with_care(rendered, stage, now)
            if cared:
                self._care_turn = turn_no
        if stage is not HelpStage.S_CRISIS and not ask and not resources:
            self._append_referral(rendered, flags)
            self._append_health_hint(rendered, stage)
            self._append_cardiac_care(rendered, signals, status, stage)
            if settled and stage is HelpStage.S_CLOSING:
                self._append_plan_suggestion(rendered, stage)

        if pending is not None and feedback is not None and not switch:
            self._apply_feedback(pending, feedback, now)
        # A card waits only while the session stays in the stage it was shown in. An
        # S_explore stabilization card also expires after one turn that is not about it
        # (no feedback, no clarification question), so a later request gets a new card.
        expired = (
            pending is not None and pending.stage is HelpStage.S_EXPLORE and not self._clarifying
        )
        if rendered.pending is not None:
            self._pending = rendered.pending
        elif (
            feedback is not None or (pending is not None and pending.stage is not stage) or expired
        ):
            self._pending = None

        # A question turn reports the screen's own level: a model-only alarm asked first is
        # still an L2 alarm (owner decision 2026-10-26), only not the crisis flow yet.
        level = max(status.level, screened.level) if ask else status.level
        self._last_reply = rendered.reply
        extra: dict[str, object] = {}
        if resources:
            self._resources_turn = turn_no
            extra["resources_reply"] = (
                "minor" if minor_now else "third_party" if third_now else "hotline"
            )
        if reported is not None:
            extra["reported_level"] = reported.level.name
        elif third_now:
            extra["third_party_followup"] = True
        if cared:
            extra["care_line"] = True
        if model_ask or model_answer:
            extra["safety_check_by"] = MODEL_CHECK
        if paused:
            extra["model_paused"] = True
        if heard:
            extra["heard"] = True
        if rendered.plan_reminded:
            extra["safety_plan_reminded"] = True
        if reached_out:
            extra["reach_out"] = True
        inspect: dict[str, object] = {
            "turn": transition.state.global_turn_count,
            "level": level.name,
            "assessed_level": screened.level.name,
            **_uncapped(screened),
            **extra,
            "in_crisis": status.in_crisis,
            "cue_ids": list(screened.cue_ids),
            "stage": stage.value,
            "previous_stage": transition.previous.value,
            "reason": reason,
            "arousal": perception.arousal,
            "valence": perception.valence,
            "emotion": perception.fine_grained_emotion,
            "intent": perception.empathy_intent,
            "stance": perception.communication_stance,
            "readiness": perception.readiness_to_change,
            "battery": transition.state.social_battery,
            "battery_prefix": signals.battery,
            "lock": transition.state.pure_listening_locked,
            "spectrum": spectrum,
            "red_flags": sorted(flags),
            "contraindications": sorted(self._active_now(stage, perception, flags)),
            "situations": sorted(self._context.situations),
            "candidates": list(rendered.candidates),
            "chosen": rendered.chosen,
            "info": rendered.info_id,
            "feedback": feedback.value if feedback is not None else None,
            "feedback_source": (
                follow.source.value if feedback is not None and follow.source is not None else None
            ),
            "gate": list(dict.fromkeys(self._gate_notes)),
            "hotline_source": self._shared.hotline_source,
            "hotline_reason": self._shared.hotline_reason,
            "risk_model": self._risk.label,
            "risk_model_reason": self._risk.reason,
            "model_level": model_level,
            "model_score": model_score,
            "safety_check": "asked" if ask else (answer.value if answer is not None else None),
            "reminder": prompted.reminder.value,
            "real_support_share": round(self._wellbeing.real_support_share, 4),
            "real_support": prompted.support,
            "late_night": self._wellbeing.is_late_night(now),
            "care_greeting": self._care_greeting,
            "distortions": list(perception.detected_distortions),
            "schemas": list(perception.detected_schemas),
            "yearning": perception.deep_yearning,
            "schema_mirror": mirror_status.value if mirror_status is not None else None,
            "externalize": naming_status.value if naming_status is not None else None,
            "externalize_name": self._externalize.name,
            "safety_plan_shown": rendered.plan_shown,
            "note_recall": recall.value if recall is not None else None,
        }
        return TurnResult(
            reply=rendered.reply,
            reply_kind=rendered.kind,
            stage=stage,
            crisis_level=level,
            in_crisis=status.in_crisis,
            resource_card=rendered.card,
            action_id=rendered.action_id,
            referral_flags=rendered.referral_flags,
            inspect=inspect,
        )

    def snapshot(self) -> dict[str, object]:
        """JSON-safe session state for later persistence (P5); holds no user text."""
        state = self._state
        status = self._last_status
        pending = self._pending
        return {
            "session_id": str(state.session_id),
            "stage": state.current_stage.value,
            "global_turn_count": state.global_turn_count,
            "stage_turn_count": state.stage_turn_count,
            "pure_listening_locked": state.pure_listening_locked,
            "social_battery": state.social_battery,
            "current_risk_level": state.current_risk_level.name,
            "stage_entry_arousal": state.stage_entry_arousal,
            "user_shelved_actions": list(state.user_shelved_actions),
            "in_crisis": status.in_crisis if status is not None else False,
            "crisis_entry_level": (
                status.entry_level.name
                if status is not None and status.entry_level is not None
                else None
            ),
            "red_flags": sorted(self._red_flags.active),
            "referred_flags": sorted(self._referred),
            "pending_action": pending.action_id if pending else None,
            "pending_spectrum": pending.spectrum if pending else None,
            "pending_stage": pending.stage.value if pending else None,
            "awaiting_clarification": self._clarifying,
            "awaiting_safety_check": self._asking,
            "gentle_care": self._gentle_care,
            "care_greeting": self._care_greeting,
            "schema_mirror": self._mirror.status.value if self._mirror.status else None,
            "externalize": self._externalize.status.value if self._externalize.status else None,
            "externalize_name": self._externalize.name,
            "bandit": self._sampler.to_dict(),
        }

    def kit(self) -> tuple[KitEntry, ...]:
        """The kit, oldest first: entries carried in, then this session's shelves."""
        shelved = self._state.user_shelved_actions
        ids = [a for a in self._carried_kit if a not in shelved] + list(shelved)
        return tuple(KitEntry(a, self._shelved_at.get(a, self._started_at)) for a in ids)

    def carried_state(self) -> CarriedState:
        """What the next session starts from: the posteriors (``snapshot()["bandit"]``)
        and the newest :data:`KIT_MAX` kit entries. Ids, numbers and times only."""
        return CarriedState(self._sampler.to_dict(), self.kit()[-KIT_MAX:])

    def care_greeting(self, *, light: bool = False) -> str:
        """The opening line after a crisis in an earlier session (PRD §9, step A3).

        ``returning_after_crisis``, or the lighter ``returning_after_check`` when the last
        session's direct question was answered with a no. Name slots only, through WILLOW,
        the output gate and the taboo filter; it never says what happened. Call it before
        the first turn; ``inspect["care_greeting"]`` then reports it on every turn.
        """
        templates = self._engine.data.templates
        variants = templates.returning_after_check if light else templates.returning_after_crisis
        self._gate_notes = []
        rendered = self._with_taboo_filter(
            lambda: self._plain_line(variants, HelpStage.S_READY), HelpStage.S_READY
        )
        self._care_greeting = True
        return rendered.reply

    def farewell(self) -> Farewell | None:
        """The goodbye when the conversation ends (``/exit``, end of input) in the crisis
        flow, or with a safety question still unanswered (S5, 2026-10-26).

        An unanswered question counts as the crisis flow (SDD §8.2: no answer is read as
        L2), whether the D3 question or the one a model-only alarm asked. The goodbye is
        one gentle line, the region's numbers as on the crisis card (emergency numbers
        first after a capped model L3) and, when the safety plan lists people, their names and
        numbers. It asks nothing (no mood rating). 问题单第 11 条 (2026-10-26): the same goodbye,
        at the highest level the crisis had, ends a session that was in the crisis flow
        earlier and has left it since. ``None`` otherwise: the caller says its ordinary
        goodbye. ``Farewell.level`` is the crisis level the care marker records.
        """
        status = self._last_status
        in_crisis = status is not None and status.in_crisis
        seen = self._crisis_seen
        if not in_crisis and not self._asking and seen is None:
            return None
        level = CrisisLevel.L2 if seen is None else seen
        if status is not None and in_crisis:
            level = max(level, status.level, status.entry_level or CrisisLevel.L0)
        card, urgent = self._crisis_card(level, self._now())
        self._gate_notes = []
        self._engine.last_gate = None
        text = self._engine.render_crisis_farewell(card, people=self._plan_people, urgent=urgent)
        care = CrisisLevel.L3 if card.level >= CrisisLevel.L3 else CrisisLevel.L2
        return Farewell(text, care)

    # -- stages ---------------------------------------------------------------------------

    def _crisis_card(self, level: CrisisLevel, now: datetime) -> tuple[ResourceCard, bool]:
        """The region's CRISIS card at ``level`` (the minors' lines only after the user said
        they are under 18 in this session, 第 5 条), and whether it is framed as urgent:
        below L3 after a capped model L3 (``_urgent``), the region's emergency numbers are
        added in front of every line of the card."""
        card = resolve(
            self._shared.store,
            self._profile.region,
            level,
            mode=CardMode.CRISIS,
            today=now.date(),
            is_minor=self._minor,
        )
        if not self._urgent or level >= CrisisLevel.L3 or card.emergency:
            return card, False
        l3 = resolve(
            self._shared.store,
            self._profile.region,
            CrisisLevel.L3,
            mode=CardMode.CRISIS,
            today=now.date(),
            is_minor=False,
        )
        stale = tuple(e.id for e in l3.emergency if e.id in l3.stale_entries)
        urgent = replace(
            card,
            emergency=l3.emergency,
            stale_entries=tuple(dict.fromkeys((*stale, *card.stale_entries))),
        )
        return urgent, True

    def _crisis(
        self, status: CrisisStatus, now: datetime, *, confirmed: bool = False, hint: bool = False
    ) -> _Rendered:
        """The crisis reply; ``confirmed`` and ``hint`` pick the opening (F5b), the card is
        the same either way."""
        level = max(CrisisLevel.L2, status.level, status.entry_level or CrisisLevel.L0)
        card, urgent = self._crisis_card(level, now)
        # S5: the plan in full once per crisis, then one line that points back at it.
        remind = self._plan_shown_in_crisis
        self._engine.last_gate = None
        reply = self._engine.render_crisis(
            card,
            self._plain_slots(),
            plan_block=self._plan_reminder if remind else self._plan_block,
            urgent=urgent,
            confirmed=confirmed,
            hint=hint,
        )
        planned = self._engine.last_plan_gate
        if planned is not None and not planned.ok:
            # The plan block was dropped; the hotline card is shown without it.
            self._gate_notes.extend(reason.split(":", 1)[0] for reason in planned.reasons)
        self._note_gate()
        ok = planned is not None and planned.ok
        shown = ok and not remind
        if shown:
            self._plan_shown_in_crisis = True
        return _Rendered(
            reply, ReplyKind.CRISIS, card=card, plan_shown=shown, plan_reminded=ok and remind
        )

    def _heard_line(self, text: str, signals: TurnSignals, stage: HelpStage) -> str | None:
        """One line that answers new words said in the crisis flow or while a card waits
        (round 3, 2026-10-27; render.yaml crisis, draft, G-0): where to go when the user
        means to see a doctor or counsellor (``help_seeking``), else a short mirror of a
        statement and a ``heard`` line, a ``question_heard`` line for a question, a
        ``brief_heard`` line for anything else. Only for a turn with no rule risk cue (the
        callers check); None when the gate or a taboo topic rules it out."""
        render = self._engine.data.render
        if signals.hotline_words and _asks(text):
            note = self._hotline_note(signals)
            if note is not None and not self._has_taboo(note, ""):
                return note
        if signals.help_seeking and render.help_seeking:
            line = self._plain_line(render.help_seeking, stage)
            return None if line is None or self._has_taboo(line[0], "") else line[0]
        kind = utterance_kind(text)
        if kind is Utterance.QUESTION or kind is Utterance.REQUEST:
            pool = render.question_heard
        elif kind is Utterance.STATEMENT:
            # The mirror is used only for a statement about the user themself ("我现在在宿
            # 舍" -> "你现在在宿舍"); other mirrors can read oddly ("你今天天气不错").
            mirrored = self._engine.safe_mirror(text) if text.lstrip().startswith("我") else ""
            usable = mirrored.startswith("你") and "对方" not in mirrored
            if usable and mirrored != FALLBACK_MIRROR and render.heard:
                tail = self._pick(render.heard)
                joined = f"{mirrored.rstrip('。.!！')}，{tail}"
                result = self._engine.gate.check(joined, kind=ContentKind.NORMAL, stage=stage)
                self._engine.last_gate = result
                if self._note_gate() and not self._has_taboo(joined, mirrored):
                    return result.text
            pool = render.heard
        else:
            pool = render.brief_heard
        if not pool:
            return None
        line = self._plain_line(pool, stage)
        return None if line is None or self._has_taboo(line[0], "") else line[0]

    def _lead_with_heard(
        self, rendered: _Rendered, text: str, signals: TurnSignals, stage: HelpStage
    ) -> bool:
        """Put :meth:`_heard_line` before the reply; False when there is none."""
        line = self._heard_line(text, signals, stage)
        if line is None:
            return False
        rendered.reply = f"{line}\n\n{rendered.reply}"
        return True

    def _crisis_waiting(
        self,
        text: str,
        status: CrisisStatus,
        now: datetime,
        signals: TurnSignals,
        stage: HelpStage,
    ) -> _Rendered:
        """A calm crisis turn after the user confirmed being safe, while the crisis waits to
        end (round 3, 2026-10-27, re-test r2 第 5 节): an answer to the words
        (:meth:`_heard_line`), then one line with every number of the crisis card
        (emergency numbers first when the card has them; SDD §8.2's compact card). No
        safety question. If either part is blocked, the full crisis reply as before."""
        level = max(CrisisLevel.L2, status.level, status.entry_level or CrisisLevel.L0)
        card, _ = self._crisis_card(level, now)
        line = self._compact_numbers(card)
        heard = self._heard_line(text, signals, stage)
        if line is None or heard is None:
            return self._crisis(status, now, confirmed=True)
        return _Rendered(f"{heard}\n{line}", ReplyKind.CRISIS, card=card)

    def _compact_numbers(self, card: ResourceCard) -> str | None:
        """Every number of ``card`` in one line (``crisis.care_hotline`` first), through
        the gate with those numbers allowed; None when it is blocked."""
        render = self._engine.data.render
        items = [f"{em.number}（{render.emergency_purposes[em.purpose]}）" for em in card.emergency]
        items.extend(f"{ln.name_zh} {ln.number}" for ln in card.lines)
        if not items or not render.care_hotline:
            return None
        text = f"{render.care_hotline}{'；'.join(items)}"
        numbers = [em.number for em in card.emergency] + [ln.number for ln in card.lines]
        result = self._engine.gate.check(
            text, kind=ContentKind.CRISIS, stage=HelpStage.S_CRISIS, allowed_numbers=numbers
        )
        self._engine.last_gate = result
        if not self._note_gate():
            return None
        return result.text

    def _reaches_out(self, text: str, assessment: CrisisAssessment) -> bool:
        """The crisis turn says the user will contact someone ("我可以给表姐打个电话"; S5):
        a ``reach_out`` phrase with no rule risk cue in the message (``rule_clear``)."""
        return assessment.rule_clear and self._shared.lexicons.reach_out.says(normalize(text))

    def _safety_check(self, stage: HelpStage, now: datetime) -> _Rendered:
        """The D3 question with the region's L2 resource lines (never the minors' lines).

        A model-only alarm asks it too (owner decisions 2026-10-26), only when the
        student's class is below L3, so its card is never framed as urgent."""
        card = resolve(
            self._shared.store,
            self._profile.region,
            CrisisLevel.L2,
            mode=CardMode.CRISIS,
            today=now.date(),
            is_minor=self._minor,
        )
        self._engine.last_gate = None
        reply = self._engine.render_safety_check(card, self._plain_slots(), stage)
        self._note_gate()
        return _Rendered(reply, ReplyKind.SAFETY_CHECK, card=card)

    def _model_only_alarm(
        self,
        assessment: CrisisAssessment,
        answer: IntentAnswer | None,
        model_level: str | None,
        model_score: float | None,
    ) -> bool:
        """Whether this turn asks first instead of entering the crisis flow.

        Owner decisions 2026-10-26. The turn is a model-only alarm when, outside a crisis
        (as of the turn before) and not the answer to a question, the screen is at L2 or
        above while the rules found no risk cue at all (``CrisisAssessment.rule_clear``,
        see ``safety.crisis.rules_found_nothing``) and the model did not fail. It asks
        first only when the student is unsure (``risk.yaml`` ``model_ask``: its class is
        below L3 and its crisis score below ``direct_from_score``, 0.6, chosen on the dev
        set only) and it is the session's first model-only alarm: any later one, and a
        sure one, enter the crisis flow as before.
        """
        before = self._last_status
        alarm = (
            not (before is not None and before.in_crisis)
            and answer is None
            and self._risk.model is not None
            and assessment.level >= CrisisLevel.L2
            and assessment.rule_clear
            and MODEL_FAILURE not in assessment.cue_ids
            and model_level in CrisisLevel.__members__
            and model_score is not None
        )
        if not alarm or model_level is None or model_score is None:
            return False
        first = not self._model_asked
        self._model_asked = True
        rules = self._shared.lexicons.model_ask
        return first and rules.asks_first(CrisisLevel[model_level], model_score)

    def _model_pause(
        self, assessment: CrisisAssessment, model_level: str | None, model_score: float | None
    ) -> bool:
        """Whether a crisis turn after a safety confirmation is tracked as L1 (a pause)
        instead of a relapse (round 3, 2026-10-27, re-test r2 第 5 节).

        Evidence from the re-test: after "我现在是安全的" the tracker counted one safe turn,
        then "它一直跟着我走了一段" (student L2, 0.59) and "明天还想去看看它" (L2, 0.34) each
        voided the confirmation, so the crisis never ended and every reply asked "你现在安全
        吗" again. Only the model saw anything: the rules found no cue (``rule_clear``).

        The pause applies only when, as of the turn before, the session is in the crisis
        flow with an explicit confirmation counted; the turn is at L2 or above while the
        rules found no risk cue at all and the model did not fail; and the student is unsure
        by the owner's ask-first rule (``risk.yaml`` ``model_ask``: its class below L3 and
        its score below ``direct_from_score``). The turn then neither counts as safe nor
        voids the confirmation (the tracker's L1 after a confirmation), so the exit rule
        itself (a confirmation, then 2 or 3 safe turns) is unchanged. A rule cue, a model
        failure, an L3 class or a sure score is a relapse as before."""
        before = self._last_status
        if (
            before is None
            or not before.in_crisis
            or before.awaiting_confirmation
            or assessment.level < CrisisLevel.L2
            or not assessment.rule_clear
            or MODEL_FAILURE in assessment.cue_ids
            or model_level not in CrisisLevel.__members__
            or model_level is None
            or model_score is None
        ):
            return False
        return self._shared.lexicons.model_ask.asks_first(CrisisLevel[model_level], model_score)

    def _answer_safety_check(
        self, text: str, assessment: CrisisAssessment, *, model: bool = False
    ) -> tuple[CrisisAssessment, IntentAnswer | None]:
        """Read this turn as the answer to the question asked on the turn before.

        Anything but a clear no is read as L2 (the screen's own L2/L3 is kept as it is).
        Whether a no carries a new crisis cue is the rule screen's call: an injected
        model's score band alone (L1) does not void it, while its L2 still enters crisis
        through ``assessment``. Returns the assessment unchanged and None when no question
        was asked.

        For the D3 question a no sets the gentle-care flag. For the question a model-only
        alarm asked (``model``, owner decision 2026-10-26) the no must also pass the F10
        denial conditions (``SafetyScreen.clear_denial``: no veto, no contrast, no negated
        denial, no rule cue outside a denial), and it sets no gentle-care flag, so the next
        session does not open by asking about safety (I9).
        """
        if not self._asking:
            return assessment, None
        shared = self._shared.screen
        rules = assessment if self._screen is shared else shared.assess(text)
        # Round 3: the D3 question also reads a first-person negated intent ("我没有想结束
        # 生命，只是……") with the rest of the message screened by the rules; the question a
        # model-only alarm asked keeps the stricter F10 no (owner decision 2026-10-26).
        reading = read_answer(
            self._shared.lexicons.intent_answers,
            text,
            rules,
            None if model else shared.assess,
        )
        answer = reading.answer
        if model and answer is IntentAnswer.DENIED and not shared.clear_denial(text):
            answer = IntentAnswer.UNCLEAR
        if answer is IntentAnswer.DENIED:
            if not model:
                self._gentle_care = True
            if reading.negated:
                return self._negation_capped(assessment), answer
            return self._denial_capped(text, assessment, rules), answer
        if assessment.level >= CrisisLevel.L2:
            return replace(assessment, rule_clear=False), answer
        l2 = replace(
            assessment,
            level=CrisisLevel.L2,
            score=max(assessment.score, self._tax.threshold("risk.lexicon_scores.L2")),
            cue_ids=(*assessment.cue_ids, MODEL_CHECK_CUE if model else SAFETY_CHECK_CUE),
            rule_clear=False,
        )
        return l2, answer

    def _denial_capped(
        self, text: str, assessment: CrisisAssessment, rules: CrisisAssessment
    ) -> CrisisAssessment:
        """The answer turn of an accepted clear no, with the model's own alarm on the no
        itself capped at L1 (问题单第 3 条, 2026-10-26; the F10 denial cap's reasoning).

        "不是，我没想那些" answers the question; the student rated that very sentence L2 and
        the session entered the crisis flow and held it for the rest of the session. The
        structural evidence is the accepted no: the D3 reading is a clear no
        (``read_intent_answer``: a denial first clause, no unsure word, the turn's rule
        screen L0 with no ask cue) and the no passes the F10 denial conditions
        (``SafetyScreen.clear_denial``: no veto, contrast, negated denial, Stage 1 cue, pair
        anchor or composition). Only then, and only when the rules found no risk cue at all
        in the message (``rule_clear``) and the model did not fail, does a level that only
        the injected model gives count as L1, which the tracker reads as an L0 turn (F8a).
        Any rule cue, a model failure or a no that is not clear keeps the level as it is.
        ``uncapped_level`` keeps the level before the cap for ``--inspect``."""
        if (
            assessment.level < CrisisLevel.L2
            or not rules.rule_clear
            or MODEL_FAILURE in assessment.cue_ids
            or not self._shared.screen.clear_denial(text)
        ):
            return assessment
        return replace(assessment, level=CrisisLevel.L1, uncapped_level=assessment.level)

    def _negation_capped(self, assessment: CrisisAssessment) -> CrisisAssessment:
        """The answer turn of a no to the D3 question that negates the intent in the first
        person (round 3, 2026-10-27; ``IntentReading.negated``): "我绝对没有想结束生命，只是
        项目做不下去". The rules see the risk phrase under the negation (L2_END_LIFE); the
        structural evidence is the answer itself: its first clause is 我 + 没(有) / 不是 + an
        intent verb, the rest of the message screens L0 with no ask cue and no unsure word
        occurs (``read_answer``). The turn then counts as L1, as for ``_denial_capped``,
        unless the model failed or the rules found plan evidence (Stage 1)."""
        if (
            assessment.level < CrisisLevel.L2
            or MODEL_FAILURE in assessment.cue_ids
            or assessment.stage == "STAGE1"
        ):
            return assessment
        return replace(assessment, level=CrisisLevel.L1, uncapped_level=assessment.level)

    def _reported_risk(
        self, text: str, assessment: CrisisAssessment, answer: IntentAnswer | None
    ) -> ReportedRisk | None:
        """Someone else's risk, reported by the user, that the session answers with the card
        to pass on instead of the crisis flow (问题单第 6 条, 2026-10-26).

        Only outside a crisis (as of the turn before) and not on the answer to a question,
        when the message reports a third person's words (``SafetyScreen.reported_risk``)
        and every rule cue of the message lies inside those words (``user_clear``: the
        user adds nothing of their own; 我也 vetoes the whole reading), and the words carry
        risk by the rules: their own rule level is L1 or above or a D3 cue
        (``ReportedRisk.rule_risk``), or they name a time and a means ("周末" and "跳下去",
        ``TurnSignals.imminent``), or (round 3) the injected model's own class for the
        words is L3 (``ReportedRisk.plan``) or they hold a death word the rules know only
        as a pair anchor next to a time or a means ("he wants to end his life tonight"). A
        lower model level on the reported clause alone never opens it: someone's comfort
        ("我同事说过一阵子就好了") is ordinary talk (re-test 2026-10-27).
        The model's last prediction is discarded, since the reported words' screen is not
        the turn's."""
        before = self._last_status
        if answer is not None or (before is not None and before.in_crisis):
            return None
        found = self._screen.reported_risk(text)
        self._risk.take_turn()
        if found is None or not found.user_clear:
            return None
        if found.rule_risk or found.plan:
            # Round 3: the model's own L3 class for the words alone (a plan) opens the card
            # too ("说他今晚就吃药走了"), as it put the user into the crisis flow before.
            return found
        _, probe = self._shared.stub.perceive(text, assessment)
        near = probe.imminent_time or probe.imminent_means
        return found if probe.imminent or (found.anchor and near) else None

    def _for_someone_else(self, assessment: CrisisAssessment) -> CrisisAssessment:
        """The turn's assessment when its risk words are someone else's (第 6 条): at most
        L1, which the tracker reads as an L0 turn (the rules' level is L0, F8a), with no
        plan evidence and no D3 question. The words' own level goes to the reply's card."""
        if assessment.level is CrisisLevel.L0:
            return replace(assessment, asks_intent=False, rule_clear=False)
        return replace(
            assessment,
            level=CrisisLevel.L1,
            score=min(assessment.score, self._tax.threshold("risk.lexicon_scores.L1")),
            stage="STAGE2",
            has_plan_evidence=False,
            asks_intent=False,
            rule_level=CrisisLevel.L0,
            uncapped_level=None,
            rule_clear=False,
        )

    def _resource_card(
        self, level: CrisisLevel, now: datetime, *, mode: CardMode, minor: bool = False
    ) -> ResourceCard:
        card = resolve(
            self._shared.store,
            self._profile.region,
            level,
            mode=mode,
            today=now.date(),
            is_minor=minor,
        )
        if not minor:
            return card
        # A minor's own lines first (CN 12355), then the general ones.
        youth = tuple(ln for ln in card.lines if ln.kind is LineKind.YOUTH_LINE)
        rest = tuple(ln for ln in card.lines if ln.kind is not LineKind.YOUTH_LINE)
        return replace(card, lines=(*youth, *rest))

    def _resource_reply(
        self,
        card: ResourceCard,
        lead: list[str],
        stage: HelpStage,
        *,
        tail: list[str] | None = None,
        emergency_heading: str | None = None,
        lines_heading: str | None = None,
    ) -> _Rendered:
        self._engine.last_gate = None
        reply = self._engine.render_resource_reply(
            card,
            lead,
            stage=stage,
            tail=tail or [],
            emergency_heading=emergency_heading,
            lines_heading=lines_heading,
        )
        self._note_gate()
        return _Rendered(reply, ReplyKind.RESOURCES, card=card)

    def _pick(self, variants: tuple[str, ...]) -> str:
        return self._engine.pick_line(variants, self._plain_slots().values())

    def _minor_reply(self, stage: HelpStage, now: datetime) -> _Rendered:
        """After the user said they are under 18 (问题单第 5 条, 2026-10-26, draft, G-0): the
        first time, that this place is for adults, a trusted adult and the region's lines
        for young people or everyone (CN 12355 first); every later reply, resources and how
        to leave. No practice, no chat, nothing about age kept. Round 3 (2026-10-27): the
        region's emergency numbers come first (CN 110 / 120), then those lines."""
        render = self._engine.data.render
        card = self._resource_card(CrisisLevel.L2, now, mode=CardMode.CRISIS, minor=True)
        if not card.emergency:
            # Round 3 (re-test r3): the region's emergency numbers lead, then the lines for
            # young people and everyone, as the reply tells a minor to call for help.
            l3 = resolve(
                self._shared.store,
                self._profile.region,
                CrisisLevel.L3,
                mode=CardMode.CRISIS,
                today=now.date(),
                is_minor=False,
            )
            stale = tuple(e.id for e in l3.emergency if e.id in l3.stale_entries)
            card = replace(
                card,
                emergency=l3.emergency,
                stale_entries=tuple(dict.fromkeys((*stale, *card.stale_entries))),
            )
        if self._minor_told:
            lead = [self._pick(render.minor_again)]
        else:
            lead = [self._pick(render.minor), render.minor_trusted_adult]
            self._minor_told = True
        self._pending = None
        return self._resource_reply(card, lead, stage)

    def _third_party_reply(
        self,
        stage: HelpStage,
        now: datetime,
        reported: ReportedRisk | None,
        signals: TurnSignals,
    ) -> _Rendered:
        """The card for someone else's reported risk (问题单第 6 条, 2026-10-26, draft, G-0):
        one serious line that asks the user nothing about their own safety, the region's
        hotlines to pass on (the L3 card, emergency numbers first, when the words carry a
        plan, time or means), and one line about being with the other person (or about a
        secret kept), and the first time in a session one about taking care of oneself.

        The card is urgent (round 3, 2026-10-27) when the words carry plan evidence (a Stage
        1 cue, or the model's own L3 class), a time and a means (``imminent``), or risk the
        rules find in them together with a time, a means or a place ("室友说她明天要去江边，
        不想活了"; "she wants to kill herself and she has pills"); an urgent card keeps the
        emergency numbers for every follow-up of that report.

        ``reported`` is None on a follow-up a few turns later (round 3): the user cannot
        reach the other person ("我联系不上他": an emergency, so the L3 card with what to
        do), asks what to do (urgent: what to do in an emergency; otherwise how to be with
        them) or says it is a secret. Never an ordinary mirror."""
        render = self._engine.data.render
        pool = render.third_party_secret if signals.keep_secret else render.third_party_support
        if reported is not None:
            near = signals.imminent_time or signals.imminent_means or signals.imminent_context
            risky = reported.rule_risk or reported.anchor
            urgent = reported.plan or signals.imminent or (risky and near)
            self._third_party_urgent = urgent or (
                self._third_party_turn is not None and self._third_party_urgent
            )
            lead = [self._pick(render.third_party)]
            tail = [self._pick(pool)]
            if self._third_party_turn is None:
                tail.append(self._pick(render.third_party_self_care))
        else:
            urgent = self._third_party_urgent or signals.third_party_unreachable
            if signals.third_party_unreachable:
                lead = [self._pick(render.third_party_unreachable)]
            elif urgent and not signals.keep_secret:
                lead = [self._pick(render.third_party_urgent_steps)]
            else:
                lead = [self._pick(pool)]
            tail = []
        level = CrisisLevel.L3 if urgent else CrisisLevel.L2
        card = self._resource_card(level, now, mode=CardMode.CRISIS)
        return self._resource_reply(
            card,
            lead,
            stage,
            tail=tail,
            emergency_heading=render.third_party_emergency_heading if urgent else None,
            lines_heading=render.third_party_lines_heading,
        )

    def _hotline_reply(self, stage: HelpStage, now: datetime, signals: TurnSignals) -> _Rendered:
        """The region's resources when the user asks for a hotline (问题单第 7 条, 2026-10-26,
        draft, G-0): the same verified data and entries as ``olivia resources`` (every
        emergency number and line, the minors' lines only after the user said they are
        under 18), led by one line; a question about one's real name or calling from abroad
        adds one true line each, and alone (within two turns of a card) leads the card.

        Round 3 (2026-10-27): the cost, the hours, the languages, whether the numbers are
        real and whether there are more get one fixed, true line each too. A place the user
        says they are in (``hotline_place``) that is not the profile's region gets that
        region's card when it is supported, else the general card (112 where GSM allows,
        findahelpline.com, Befrienders) with a line pointing at ``olivia resources <code>``:
        never the profile region's numbers as if they were local."""
        render = self._engine.data.render
        place = signals.hotline_place
        own = self._profile.region.country_code if self._profile.region is not None else None
        elsewhere = place is not None and place != own
        if elsewhere and place is not None:
            zone = self._profile.region.timezone if self._profile.region is not None else "UTC"
            card = resolve(
                self._shared.store,
                UserRegion(place, zone),
                CrisisLevel.L2,
                mode=CardMode.BROWSING,
                today=now.date(),
                is_minor=self._minor,
            )
            unverified = card.region_used == UNKNOWN_COUNTRY
            head = render.hotline_elsewhere if unverified else render.hotline_other_region
        else:
            card = self._resource_card(CrisisLevel.L2, now, mode=CardMode.BROWSING)
            head = render.hotline_request if signals.hotline_request else ()
        notes = [
            self._pick(pool)
            for flag, pool in (
                (signals.hotline_anonymous, render.hotline_anonymous),
                (signals.hotline_abroad and not elsewhere, render.hotline_abroad),
                (signals.hotline_fee, render.hotline_fee),
                (signals.hotline_hours, render.hotline_hours),
                (signals.hotline_language, render.hotline_language),
                (signals.hotline_real, render.hotline_real),
                (signals.hotline_more, render.hotline_more),
            )
            if flag and pool
        ]
        if head:
            return self._resource_reply(card, [self._pick(head)], stage, tail=notes)
        return self._resource_reply(card, notes, stage)

    def _hotline_note(self, signals: TurnSignals) -> str | None:
        """The first true line for a follow-up about the numbers on screen (round 3), for a
        crisis turn or a turn while a card waits; None when the message asks none."""
        render = self._engine.data.render
        for flag, pool in (
            (signals.hotline_more, render.hotline_more),
            (signals.hotline_hours, render.hotline_hours),
            (signals.hotline_fee, render.hotline_fee),
            (signals.hotline_language, render.hotline_language),
            (signals.hotline_real, render.hotline_real),
            (signals.hotline_anonymous, render.hotline_anonymous),
        ):
            if flag and pool:
                return self._pick(pool)
        return None

    def _lead_with_care(self, rendered: _Rendered, stage: HelpStage, now: datetime) -> bool:
        """One line of care and one line of the region's hotlines before the reply (问题单
        第 11 条, draft, G-0); False when the gate or a taboo topic rules either out."""
        render = self._engine.data.render
        card = self._resource_card(CrisisLevel.L2, now, mode=CardMode.CRISIS, minor=self._minor)
        care = self._plain_line(render.care_watch, stage)
        hotline = self._engine.render_hotline_line(card, stage)
        if care is None or hotline is None or self._has_taboo(care[0], ""):
            return False
        rendered.reply = f"{care[0]}\n{hotline}\n\n{rendered.reply}"
        return True

    def _offer(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        flags: frozenset[str],
        spectrum: str | None,
        mirror_text: str,
        now: datetime,
        *,
        recall: bool = False,
        requested: str | None = None,
        asked: bool = False,
    ) -> _Rendered:
        """Sample and show a card in S_empower, or a stabilization card in S_explore.

        With ``recall``, the most recently shelved action that the solver allows right now
        is shown instead of a sampled one, and it leaves the kit (``/not-now`` puts it
        back). When no shelved action is allowed now, a card is sampled as usual.
        ``requested`` is a practice the user asked for by name ("带我做一下正念", F3): it
        is shown when the solver allows it now, otherwise a card is sampled as usual. The
        card's context line follows the user's local time (working hours or not).
        ``asked``: the turn asks for a method outright; when grief (SIT-06-04) then puts
        it on m0, ``followups.grief_request`` (acute: ``ACUTE_BEREAVEMENT_SHOCK`` active)
        or ``followups.grief_request_prolonged`` (F13) leads the reply (F10).
        """
        tax = self._tax
        shelved = self._state.user_shelved_actions
        deck = self._engine.data.cards.cards
        chosen: str | None = None
        # The turn's spectrum, else the conversation's last known one, else the fallback.
        bucket = spectrum or self._last_spectrum or FALLBACK_SPECTRUM
        allowed = self._allowed(stage, perception, flags, frozenset(shelved))
        if recall:
            unmasked = self._allowed(stage, perception, flags, frozenset())
            kit = [
                a
                for a in reversed([*self._carried_kit, *shelved])
                if a in unmasked.candidates and a in deck
            ]
            if kit:
                chosen = kit[0]
                if chosen in shelved:
                    remaining = [a for a in shelved if a != chosen]
                    self._state = replace(self._state, user_shelved_actions=remaining)
                    allowed = self._allowed(stage, perception, flags, frozenset(remaining))
        renderable = [aid for aid in allowed.candidates if aid in deck]
        if chosen is None and requested in renderable:
            chosen = requested
        if chosen is None and renderable:
            # SDD §6.3: explore only in the regular Grade A pool (never the stabilization
            # whitelist, an L1 stabilization turn or a red flag's closed set).
            chosen = self._sampler.choose(
                renderable,
                bucket,
                perception.arousal,
                self._rng,
                now,
                explore=allowed.explorable,
            )
        plan = build_plan(tax, chosen, allowed)
        primary = plan.primary

        card_text: str | None = None
        if primary.method_id != M0_ACTION_ID:
            self._engine.last_gate = None
            region = self._profile.region
            card_text = self._engine.render_card(
                primary, at_work=at_work(now, region.timezone if region is not None else None)
            )
            if not self._note_gate():
                card_text = None

        if card_text is not None:
            title = self._engine.card_for(primary.method_id).title
            body = card_text
            # A tips card (PSYCHOEDUCATION, plan D-3) is framed as tips (F16b). It is a
            # right-wing action only, so it never comes as an S_explore stabilization card.
            tips = primary.action_type is ActionType.PSYCHOEDUCATION
            if stage is HelpStage.S_EMPOWER:
                rendered = self._with_taboo_filter(
                    lambda: self._compose(
                        stage,
                        perception,
                        spectrum,
                        mirror_text,
                        card_title=title,
                        card=body,
                        light=allowed.battery_gated,
                        tips=tips,
                    ),
                    stage,
                )
            else:
                rendered = self._with_taboo_filter(
                    lambda: self._compose_stabilization(
                        perception, spectrum, mirror_text, title, body
                    ),
                    stage,
                )
            if rendered.kind is ReplyKind.NORMAL:
                rendered.kind = ReplyKind.CARD
                rendered.action_id = primary.method_id
                rendered.pending = _Pending(
                    primary.method_id,
                    bucket,
                    stage,
                    stabilization=(
                        stage is HelpStage.S_EXPLORE
                        or self._stabilization_only
                        or perception.arousal >= self._somatic
                    ),
                )
        elif primary.method_id == M0_ACTION_ID:
            rendered = self._with_taboo_filter(
                lambda: self._compose(HelpStage.S_EXPLORE, perception, spectrum, mirror_text),
                HelpStage.S_EXPLORE,
            )
            if stage is HelpStage.S_EMPOWER:
                rendered.action_id = M0_ACTION_ID
            if asked and _PROLONGED_GRIEF in self._context.situations:
                # The request is heard and the m0 answer explained (F10, 草稿：待 G-0).
                templates = self._engine.data.templates
                acute = BEREAVEMENT_CONTRAINDICATION in self._context.contraindications
                line = templates.grief_request if acute else templates.grief_request_prolonged
                self._add_line(rendered, line, stage, first=True)
        else:  # the gate blocked the card: show nothing rather than a broken card
            rendered = _Rendered(self._engine.gate.fallback, ReplyKind.HAVEN)
        if chosen is not None and chosen in shelved and rendered.action_id != chosen:
            # A recalled card that could not be shown stays in the kit.
            self._state = replace(self._state, user_shelved_actions=list(shelved))
        if rendered.kind is ReplyKind.CARD and rendered.action_id in self._carried_kit:
            # A carried kit card shown again leaves the kit until it is shelved again.
            self._carried_kit.remove(rendered.action_id)

        rendered.candidates = allowed.candidates
        rendered.chosen = chosen
        # The solver requires the referral card with every S_empower plan and with every
        # stabilization card it backs; S_explore companionship relies on the new-flag rule.
        if stage is HelpStage.S_EMPOWER or rendered.action_id is not None:
            rendered.referral_flags = plan.referral_flags
        return rendered

    def _info_choice(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        flags: frozenset[str],
        signals: TurnSignals,
        status: CrisisStatus,
        assessed: CrisisLevel,
        feedback: Feedback | None,
        transition: Transition,
    ) -> tuple[str, str, bool] | None:
        """(method id, card text, lens) for a Grade B/C card to show, or None."""
        if (
            status.in_crisis
            or assessed >= CrisisLevel.L1
            or feedback is not None
            or signals.direct_request
        ):
            return None
        inp = SolverInput(
            stage=stage,
            arousal=perception.arousal,
            battery=transition.state.social_battery,
            active_red_flags=flags,
            active_contraindications=self._context.contraindications,
            situation_codes=self._context.situations,
            shelved_actions=frozenset(),
        )
        asked = signals.therapy_question
        data = self._engine.data
        if asked is not None and asked in data.exercise_info:
            # A Grade A practice asked about by name: its short explainer (F3), never
            # for a red-flag user, who only gets the referral card.
            chosen, lens = (None if flags else asked), False
        elif asked is not None:
            chosen, lens = (asked if info_cards(self._tax, inp, asked) else None), False
        elif (
            stage is HelpStage.S_CLARIFY
            and not self._lens_shown
            and not transition.state.pure_listening_locked
            # Not while the user tells something heavy (F6b): the lens waits for a calmer
            # turn, and its once-per-session use is not spent.
            and not self._heavy(perception)
            # SILENT_ANCHOR only listens (SDD §6.1): no unasked perspective.
            and self._profile.persona_spectrum is not PersonaSpectrum.SILENT_ANCHOR
        ):
            # Only a lens that fits: the active situations' spectra when there are any,
            # so a breakup or a loss never gets a relationship-skills lens (F3); else the
            # spectrum the conversation showed last, and a lens for one topic only when
            # that topic came up (dogfood I4: couples therapy with a partner).
            fit = fitting_spectra(self._context.situations, self._last_spectrum)
            if self._loss_seen:
                # After a bereavement, talk of the person lost reads as attachment or
                # trauma cues (dogfood I4: a couples-therapy card after a father's death):
                # no lens from those spectra for the rest of the session.
                fit = fit - _AFTER_LOSS_NO_LENS
            pool = lens_pool(
                info_cards(self._tax, inp),
                data.situation_lenses,
                self._context.situations,
                [mid for sid in sorted(fit) for mid in data.info_lenses.get(sid, ())],
            )
            pool = [
                mid for mid in pool if mid not in data.lens_requires or mid in self._lens_topics
            ]
            chosen, lens = (self._rng.choice(pool) if pool else None), True
        else:
            return None
        if chosen is None:
            return None
        self._engine.last_gate = None
        text = self._engine.render_info_reply(chosen, lens=lens)
        if not self._note_gate() or self._has_taboo(text, ""):
            return None
        return chosen, text, lens

    def _heavy(self, perception: PerceptionContext) -> bool:
        """Whether this turn tells something heavy (F6b): grief; sadness while a loss is
        on the table (an active situation of the trauma, stress and bereavement spectrum,
        e.g. SIT-06-03 a breakup, SIT-06-04 a bereavement); that spectrum as the turn's
        own; or arousal above ``exploration_allow``. Plain tiredness ("今天上班好累",
        read as sadness) is not heavy. An L1 screen never gets this far
        (``_info_choice`` shows no card at L1 or above)."""
        emotion = perception.fine_grained_emotion
        loss = any(code.startswith(_LOSS_SITUATIONS) for code in self._context.situations)
        return (
            emotion == "grief"
            or (emotion == "sadness" and loss)
            or dominant_spectrum(perception.distress_vector) == _HEAVY_SPECTRUM
            or perception.arousal > self._heavy_arousal
        )

    def _info(
        self,
        info: tuple[str, str, bool],
        stage: HelpStage,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
    ) -> _Rendered:
        """The information card alone, or after the S_clarify reply for a lens."""
        method_id, text, lens = info
        if not lens:
            return _Rendered(text, ReplyKind.INFO, info_id=method_id)
        rendered = self._with_taboo_filter(
            lambda: self._compose(stage, perception, spectrum, mirror_text), stage
        )
        if rendered.kind is ReplyKind.NORMAL:
            rendered.reply = f"{rendered.reply}\n\n{text}"
            rendered.kind = ReplyKind.INFO
            rendered.info_id = method_id
            self._lens_shown = True
        return rendered

    def _allowed(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        flags: frozenset[str],
        shelved: frozenset[str],
    ) -> AllowedSet:
        if self._stabilization_only:
            # An L1 turn (ruling 5): the stabilization pool, with every mask still applied.
            stage, arousal = HelpStage.S_EXPLORE, max(perception.arousal, self._somatic)
        else:
            arousal = perception.arousal
        return allowed_actions(
            self._tax,
            SolverInput(
                stage=stage,
                arousal=arousal,
                active_red_flags=flags,
                active_contraindications=self._context.contraindications,
                situation_codes=self._context.situations,
                shelved_actions=shelved,
                battery=self._state.social_battery,
            ),
        )

    def _active_now(
        self, stage: HelpStage, perception: PerceptionContext, flags: frozenset[str]
    ) -> frozenset[str]:
        """Every contraindication the solver applies this turn, arousal overload included."""
        return active_contraindications(
            self._tax,
            SolverInput(
                stage=stage,
                arousal=perception.arousal,
                active_red_flags=flags,
                active_contraindications=self._context.contraindications,
                situation_codes=self._context.situations,
                shelved_actions=frozenset(),
                battery=self._state.social_battery,
            ),
        )

    def _compose(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
        *,
        card_title: str = "",
        card: str = "",
        light: bool = False,
        tips: bool = False,
        short: bool | None = None,
    ) -> tuple[str, str] | None:
        """One composed reply and the mirror it used (taboo hits inside it are allowed).

        ``short`` asks for the two-paragraph reply to a very short message (F3); None
        decides from ``mirror_text``. ``tips``: the card is a tips card (F16b), framed as
        tips, never as a practice.
        """
        # The engine names the feeling only when there is one (F3): never the rule stub's
        # fallback emotion, and the user's own word first ("好累" -> 疲惫).
        slots = self._engine.build_slots(
            user_name=self._profile.user_name,
            agent_name=self._profile.agent_name,
            user_text=mirror_text,
            emotion_id=perception.fine_grained_emotion,
            yearning_id=perception.deep_yearning,
            spectrum_id=spectrum,
            card_title=card_title,
            situations=self._context.situations,
            utterance=self._utterance,
        )
        if not slots.mirror:
            slots = replace(slots, mirror=FALLBACK_MIRROR)
        self._engine.last_gate = None
        if short is None:
            short = bool(mirror_text) and is_short_input(mirror_text)
        if stage is HelpStage.S_CLARIFY and (short or not self._need_due):
            # Not every S_clarify reply names a need, never one after "嗯" (dogfood I3).
            slots = replace(slots, need="")
        text = self._engine.compose(stage, slots, card=card, light=light, tips=tips, short=short)
        if not self._note_gate():
            return None
        if stage is HelpStage.S_CLARIFY and slots.need and slots.need in text:
            self._need_named = True
        return text, slots.mirror

    def _compose_mirror(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
        schema: str,
    ) -> tuple[str, str] | None:
        """The S_clarify reply with its closing question replaced by the schema mirror.

        The mirror line passes WILLOW and the gate on its own (``_plain_line``), and the
        joined reply passes the gate once more.
        """
        composed = self._compose(stage, perception, spectrum, mirror_text)
        if composed is None:
            return None
        line = self._plain_line(self._mirror.lines(schema), stage)
        if line is None:
            return None
        head = composed[0].rsplit("\n\n", 1)[0]
        result = self._engine.gate.check(
            f"{head}\n\n{line[0]}", kind=ContentKind.NORMAL, stage=stage
        )
        self._engine.last_gate = result
        if not self._note_gate():
            return None
        return result.text, composed[1]

    def _offer_naming(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
    ) -> _Rendered:
        """The S_clarify reply with its closing question replaced by the naming offer (C3)."""
        offers = self._externalize.text.offers
        chosen = [offers[0]]

        def compose() -> tuple[str, str] | None:
            chosen[0] = self._rng.choice(offers)
            return self._compose_swapped(
                stage, perception, spectrum, mirror_text, chosen[0].line, index=-1
            )

        rendered = self._with_taboo_filter(compose, stage)
        if chosen[0].line in rendered.reply:
            self._externalize.mark_offered(chosen[0])
        return rendered

    def _naming_line(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        settled: bool,
        answered: ExternalizeStatus | None,
    ) -> str | None:
        """The acknowledgement on the answer turn, or a line that uses the accepted name
        when the pattern shows up again (C3); None when this reply carries neither."""
        if stage not in (HelpStage.S_EXPLORE, HelpStage.S_CLARIFY) or not settled:
            return None
        ext = self._externalize
        text = ext.text
        if answered is ExternalizeStatus.DECLINED:
            return self._rng.choice(text.declined)
        if ext.name is None:
            return None
        if answered is ExternalizeStatus.ACCEPTED:
            return text.fill(self._rng.choice(text.accepted), ext.name)
        if ext.callback_due(perception.detected_schemas, perception.detected_distortions):
            return text.fill(self._rng.choice(text.callbacks), ext.name)
        return None

    def _compose_swapped(
        self,
        stage: HelpStage,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
        line: str | None,
        *,
        index: int = 1,
    ) -> tuple[str, str] | None:
        """A composed reply with paragraph ``index`` replaced by ``line`` (C3).

        The line passes WILLOW and the gate on its own and the joined reply once more; a
        reply that is not three paragraphs, or a line naming a taboo topic, keeps the
        reply's own text.
        """
        # A line to swap in needs the three-paragraph reply.
        composed = self._compose(
            stage, perception, spectrum, mirror_text, short=False if line is not None else None
        )
        if composed is None or line is None or self._has_taboo(line, ""):
            return composed
        parts = composed[0].split("\n\n")
        if len(parts) != 3:
            return composed
        line = apply_willow(line, ContentKind.NORMAL, self._engine.data.willow)
        self._engine.last_gate = self._engine.gate.check(line, kind=ContentKind.NORMAL, stage=stage)
        if not self._note_gate():
            return None
        parts[index] = line
        result = self._engine.gate.check("\n\n".join(parts), kind=ContentKind.NORMAL, stage=stage)
        self._engine.last_gate = result
        if not self._note_gate():
            return None
        return result.text, composed[1]

    def _compose_stabilization(
        self,
        perception: PerceptionContext,
        spectrum: str | None,
        mirror_text: str,
        title: str,
        card: str,
    ) -> tuple[str, str] | None:
        """S_explore reflection, then the card intro, the card and the feedback prompt.

        Both halves come out of ``compose`` and so passed the gate on their own; the
        S_empower ``bridge`` paragraph is dropped so the framing stays the S_explore one.
        """
        explore = self._compose(HelpStage.S_EXPLORE, perception, spectrum, mirror_text)
        if explore is None:
            return None
        empower = self._compose(
            HelpStage.S_EMPOWER, perception, spectrum, mirror_text, card_title=title, card=card
        )
        if empower is None:
            return None
        reflect = explore[0].split("\n\n", 1)[0]
        tail = empower[0].split("\n\n", 1)[1]
        return f"{reflect}\n\n{tail}", explore[1]

    def _after_card_prompt(self) -> tuple[str, str] | None:
        """The S_empower ``after_card`` line alone, for a card still waiting for feedback."""
        return self._plain_line(self._engine.data.templates.after_card, HelpStage.S_EMPOWER)

    def _followup(self, variants: tuple[str, ...], stage: HelpStage) -> _Rendered:
        """A short follow-up line (roadmap R-7b), through the taboo filter and the gate."""
        return self._with_taboo_filter(lambda: self._plain_line(variants, stage), stage)

    def _after_close(self, now: datetime) -> tuple[str, ...]:
        """The ``after_close`` lines for the user's local hour (F6b): the ones that point at
        the evening ("今晚", "早点休息") only from the end of the working day (18:00) through
        the B7 late-night window, the others at any hour."""
        templates = self._engine.data.templates
        region = self._profile.region
        zone = region.timezone if region is not None else None
        if after_work_hours(now, zone) or self._wellbeing.is_late_night(now):
            return templates.after_close
        return templates.after_close_daytime

    def _closing(
        self, variants: tuple[str, ...], stage: HelpStage, *, window: bool = False
    ) -> _Rendered:
        """A closing ritual (``window``: one that fits the stage's word window) or an
        after-close line, never the text of the last one sent nor of the last reply (I7:
        a goodbye never repeats the turn before it word for word)."""
        avoid = frozenset(t for t in (self._last_closing, self._last_reply) if t is not None)
        rendered = self._with_taboo_filter(
            lambda: self._plain_line(variants, stage, avoid=avoid, window=window), stage
        )
        self._last_closing = rendered.reply
        return rendered

    def _add_line(
        self, rendered: _Rendered, variants: tuple[str, ...], stage: HelpStage, *, first: bool
    ) -> None:
        """Put one name-slot line before (``first``) or after the reply, unless the gate or
        a taboo topic rules it out; the reply itself is kept either way."""
        line = self._plain_line(variants, stage)
        if line is None or self._has_taboo(line[0], ""):
            return
        if first:
            rendered.reply = f"{line[0]}\n\n{rendered.reply}"
        else:
            rendered.reply = f"{rendered.reply}\n\n{line[0]}"

    def _plain_line(
        self,
        variants: tuple[str, ...],
        stage: HelpStage,
        *,
        avoid: frozenset[str] = frozenset(),
        window: bool = False,
    ) -> tuple[str, str] | None:
        """One variant with only the name slots filled, after WILLOW and the output gate.

        ``avoid`` leaves out the variants that render to one of those texts and ``window``
        keeps to the variants that fit the stage's word window, unless that leaves none."""
        values = self._plain_slots().values()
        willow = self._engine.data.willow
        usable = [v for v in variants if all(values[s] for s in slots_of(v))]
        rendered = {
            v: apply_willow(_fill_names(v, values), ContentKind.NORMAL, willow) for v in usable
        }
        pool = [v for v in usable if rendered[v] not in avoid] or usable
        if window:
            pool = [v for v in pool if self._engine.window_penalty(stage, rendered[v]) == 0] or pool
        # The engine skips a line the replies just before already said (F3).
        text = rendered[self._engine.pick_line(pool, values)]
        result = self._engine.gate.check(text, kind=ContentKind.NORMAL, stage=stage)
        self._engine.last_gate = result
        if not self._note_gate():
            return None
        return text, ""

    def _wellbeing_line(self, variant: str, stage: HelpStage) -> str | None:
        """One wellbeing variant with the name slots filled, or None when the gate or a
        taboo topic rules it out (B7)."""
        values = self._plain_slots().values()
        if not all(values[s] for s in slots_of(variant)):
            return None
        text = _fill_names(variant, values)
        text = apply_willow(text, ContentKind.NORMAL, self._engine.data.willow)
        self._engine.last_gate = self._engine.gate.check(text, kind=ContentKind.NORMAL, stage=stage)
        if not self._note_gate() or self._has_taboo(text, ""):
            return None
        return text

    def _with_taboo_filter(self, compose: _Composer, stage: HelpStage) -> _Rendered:
        kind = ReplyKind.HAVEN if stage is HelpStage.S_HAVEN else ReplyKind.NORMAL
        for _ in range(1 + TABOO_RETRIES):
            composed = compose()
            if composed is None:
                return _Rendered(self._engine.gate.fallback, ReplyKind.HAVEN)
            reply, mirrored = composed
            if not self._has_taboo(reply, mirrored):
                return _Rendered(reply, kind)
        self._gate_notes.append("taboo")
        return _Rendered(self._engine.gate.fallback, ReplyKind.HAVEN)

    def _append_referral(self, rendered: _Rendered, flags: frozenset[str]) -> None:
        """Add the referral card for the plan's flags and for flags not yet referred that
        the conversation brought up. A flag known only from the profile comes with a plan
        (a card or m0), never on the first, unrelated turn of every session (dogfood I5)."""
        wanted = set(rendered.referral_flags) | ((flags & self._text_flags) - self._referred)
        if not wanted:
            return
        codes = tuple(code for code in self._tax.red_flags() if code in wanted)
        # The same card on the turn right after: short intro, every destination (F5b).
        turn_no = self._state.global_turn_count
        last = self._last_referral
        again = last is not None and last == (codes, turn_no - 1)
        self._referral_again = self._referral_again + 1 if again else 0
        self._last_referral = (codes, turn_no)
        self._engine.last_gate = None
        region = self._profile.region
        referral = self._engine.render_referral(
            codes,
            region.country_code if region is not None else UNKNOWN_COUNTRY,
            again=self._referral_again,
        )
        self._note_gate()
        self._referred |= wanted
        rendered.reply = f"{rendered.reply}\n\n{referral}"
        rendered.referral_flags = codes
        if rendered.kind is not ReplyKind.CARD:
            rendered.kind = ReplyKind.REFERRAL

    def _hint_haven_exit(self, rendered: _Rendered, stage: HelpStage) -> None:
        """Swap the haven line for the one that also says how to leave (FSM-15), once.

        The first variant in file order that passes the gate, the taboo filter and the
        haven window: no random draw, so the rest of the session reads as it would have."""
        for variant in self._engine.data.templates.haven_exit_hint:
            line = self._wellbeing_line(variant, stage)
            if line is not None and self._engine.window_penalty(stage, line) == 0:
                rendered.reply = line
                self._haven_hinted = True
                return

    def _append_health_hint(self, rendered: _Rendered, stage: HelpStage) -> None:
        """Say once that a disclosure heard in the conversation can be saved (D2)."""
        unsaved = self._contra.unsaved_disclosures()
        if not unsaved or rendered.kind is ReplyKind.HAVEN or stage is HelpStage.S_HAVEN:
            return
        line = self._plain_line(self._engine.data.templates.health_hint, stage)
        if line is None or self._has_taboo(line[0], ""):
            return
        self._contra.mark_hinted(unsaved)
        rendered.reply = f"{rendered.reply}\n\n{line[0]}"

    def _append_cardiac_care(
        self, rendered: _Rendered, signals: TurnSignals, status: CrisisStatus, stage: HelpStage
    ) -> None:
        """End the reply once per session with the line about medical help when a user with
        a heart or breathing condition tells of chest or heart symptoms (dogfood I2)."""
        if (
            self._cardiac_noted
            or not signals.cardiac_symptom
            or _CARDIO not in self._context.contraindications
            or status.in_crisis
        ):
            return
        before = rendered.reply
        self._add_line(rendered, self._notice("cardiac_care"), stage, first=False)
        self._cardiac_noted = rendered.reply != before

    def _notice(self, name: str) -> tuple[str, ...]:
        """``utterances.yaml`` ``notices[name]``: persona-neutral lines (dogfood I1, I2)."""
        return self._engine.data.utterances.notices[name]

    def _observe_topics(
        self, text: str, perception: PerceptionContext, spectrum: str | None
    ) -> None:
        """What the conversation has been about, for the S_clarify lens (dogfood I4): a
        bereavement (grief, or SIT-06-04), and the lens topics of
        ``grade_bc_info.yaml`` ``lens_requires`` that came up (method ids, no user text)."""
        if (
            perception.fine_grained_emotion == _GRIEF_EMOTION
            or _BEREAVEMENT in self._context.situations
        ):
            self._loss_seen = True
        requires = self._engine.data.lens_requires
        if requires:
            folded = normalize(text)
            self._lens_topics |= {
                mid for mid, words in requires.items() if any(w in folded for w in words)
            }

    def _append_plan_suggestion(self, rendered: _Rendered, stage: HelpStage) -> None:
        """End the first S_closing reply with the ``olivia safety-plan`` line (B10), once."""
        if not self._suggest_plan or self._plan_suggested or rendered.kind is ReplyKind.HAVEN:
            return
        line = self._wellbeing_line(load_safety_plan_text().suggestion, stage)
        if line is None:
            return
        self._plan_suggested = True
        rendered.reply = f"{rendered.reply}\n\n{line}"

    # -- feedback -------------------------------------------------------------------------

    def _follow_up(
        self,
        signals: TurnSignals,
        status: CrisisStatus,
        assessed: CrisisLevel,
        pending: _Pending | None,
    ) -> _FollowUp:
        """Read natural-language feedback, answers and kit recall (roadmap R-7b).

        Nothing is read on a crisis turn (the tracker's crisis, or an L2/L3 screen): the
        signals pass through unchanged and the state machine routes to S_crisis. Feedback
        phrases count only while a card waits in the current stage, and a slash command
        wins. A clarification question waits for exactly one turn.
        """
        clarifying, self._clarifying = self._clarifying, False
        if status.in_crisis or assessed >= CrisisLevel.L2:
            return _FollowUp(signals)
        # An L1 screen ("我想消失") may hide distress the rules under-rate, so its everyday
        # phrases are not read as feedback, answers or kit recall; commands still count.
        phrases = assessed < CrisisLevel.L1
        current = self._state.current_stage
        source: FeedbackSource | None = None
        clarify = False
        if pending is not None and pending.stage is current:
            if signals.command is not None:
                source = FeedbackSource.COMMAND
            elif signals.aversion and signals.feedback in (None, Command.UNHELPFUL):
                # Aversion keeps its own route (EMPOWER_AVERSION), with the same feedback.
                source = FeedbackSource.PHRASE
            elif not phrases:
                pass
            elif signals.feedback is not None:
                # Read exactly as the command, so the state machine routes it the same way.
                signals = replace(signals, command=signals.feedback, aversion=False)
                source = FeedbackSource.PHRASE
            elif clarifying and signals.answer is Answer.AFFIRM:
                signals = replace(signals, command=Command.NOT_NOW, aversion=False)
                source = FeedbackSource.CONFIRMED
            elif signals.feedback_unclear and not clarifying:
                clarify = True
        recall = kit_empty = False
        if phrases and signals.kit_recall and source is None and not clarify:
            if self._state.user_shelved_actions or self._carried_kit:
                signals = replace(signals, direct_request=True)
                recall = True
            else:
                kit_empty = True
        declined = False
        if phrases and current is HelpStage.S_CLOSING and signals.command is None:
            if signals.answer is Answer.AFFIRM:
                signals = replace(signals, intent_confirmed=True)
            elif signals.answer is Answer.DECLINE:
                declined = True
        return _FollowUp(signals, source, clarify, recall, kit_empty, declined)

    def _held(self, transition: Transition) -> Transition:
        """The transition of a meta turn: counted as a turn, but the stage stays (unless
        the battery or a crisis moved it, which a meta turn never overrides)."""
        moved = transition.state.current_stage
        previous = transition.previous
        if moved in (previous, HelpStage.S_CRISIS, HelpStage.S_HAVEN):
            return transition
        state = replace(
            transition.state,
            current_stage=previous,
            stage_turn_count=self._state.stage_turn_count + 1,
            stage_entry_arousal=self._state.stage_entry_arousal,
        )
        return Transition(previous, state, Reason.STAY)

    @staticmethod
    def _reopens(
        transition: Transition,
        signals: TurnSignals,
        follow: _FollowUp,
        perception: PerceptionContext,
        spectrum: str | None,
    ) -> bool:
        """New content after the closing ritual: anything still in S_closing that is not a
        yes or no, a command, a feedback phrase or a kit request, and that is not plainly
        positive (a thank-you gets the after-close line instead)."""
        return (
            transition.previous is HelpStage.S_CLOSING
            and transition.state.current_stage is HelpStage.S_CLOSING
            and transition.reason is Reason.STAY
            and signals.command is None
            and signals.answer is None
            and signals.feedback is None
            and not signals.kit_recall
            and not follow.kit_empty
            and not follow.closing_declined
            and (perception.valence <= 0.0 or spectrum is not None)
        )

    @staticmethod
    def _reopen(transition: Transition, perception: PerceptionContext) -> Transition:
        """Back to listening: S_explore, entered on this turn."""
        state = replace(
            transition.state,
            current_stage=HelpStage.S_EXPLORE,
            stage_turn_count=1,
            stage_entry_arousal=perception.arousal,
        )
        return Transition(transition.previous, state, Reason.STAY)

    def _degraded(
        self, assessment: CrisisAssessment, now: datetime, *, asking: bool, error: str
    ) -> TurnResult:
        """The SDD §10.1 fallback reply after a failure past the crisis screen.

        A crisis (this turn's screen at L2/L3, the tracker's crisis, the S_crisis stage, or
        the answer to the D3 question) gets the minimal crisis card with every number of
        the region's card (emergency numbers included after a capped model L3); anything
        else gets the persona's slot-free presence line. ``inspect`` carries the error's
        class name only, never its message.
        """
        state = self._state
        status = self._last_status
        crisis = (
            assessment.level >= CrisisLevel.L2
            or asking
            or state.current_stage is HelpStage.S_CRISIS
            or (status is not None and status.in_crisis)
        )
        card: ResourceCard | None = None
        if crisis:
            entry = status.entry_level if status is not None else None
            level = max(CrisisLevel.L2, assessment.level, entry or CrisisLevel.L0)
            card, _ = self._crisis_card(level, now)
            numbers = [e.number for e in card.emergency] + [ln.number for ln in card.lines]
            minimal = self._shared.language.render.crisis_minimal
            reply = "\n".join([minimal, *(f"· {n}" for n in numbers)])
            kind = ReplyKind.CRISIS
            stage = HelpStage.S_CRISIS
        else:
            level = assessment.level
            reply = self._engine.gate.fallback
            kind = ReplyKind.HAVEN
            stage = state.current_stage
        inspect: dict[str, object] = {
            "turn": state.global_turn_count,
            "level": level.name,
            "assessed_level": assessment.level.name,
            **_uncapped(assessment),
            "in_crisis": crisis,
            "cue_ids": list(assessment.cue_ids),
            "stage": stage.value,
            "previous_stage": state.current_stage.value,
            "reason": DEGRADED,
            "degraded": error,
            "late_night": self._wellbeing.is_late_night(now),
            "hotline_source": self._shared.hotline_source,
            "hotline_reason": self._shared.hotline_reason,
            "risk_model": self._risk.label,
            "risk_model_reason": self._risk.reason,
        }
        return TurnResult(
            reply=reply,
            reply_kind=kind,
            stage=stage,
            crisis_level=level,
            in_crisis=crisis,
            resource_card=card,
            action_id=None,
            referral_flags=(),
            inspect=inspect,
        )

    def _switches(
        self,
        pending: _Pending | None,
        feedback: Feedback | None,
        transition: Transition,
        signals: TurnSignals,
        perception: PerceptionContext,
        flags: frozenset[str],
        status: CrisisStatus,
        assessment: CrisisAssessment,
        rules: CrisisAssessment,
    ) -> bool:
        """The turn asks for another card in place of the one waiting (F16b).

        Only on a calm S_empower turn that would otherwise re-send the ``after_card``
        prompt (the card waits in the stage the turn came from, the state machine stays or
        takes the direct request): outside a crisis, the screen and the rule screen below
        L1, no command, and the request says another one ("再给我一个", "换一个", "有没有
        别的方法") or names a practice other than the waiting one ("带我做一下正念").
        A generic request ("能给我一个练习试试吗", the red-team probe) keeps the waiting
        card. And only when the masks leave another card to show: the replacement comes
        from the whitelist when the waiting card did (``_Pending.stabilization``).
        """
        if (
            pending is None
            or feedback is not None
            or transition.state.current_stage is not HelpStage.S_EMPOWER
            or transition.previous is not pending.stage
            or transition.reason not in (Reason.STAY, Reason.DIRECT_REQUEST)
            or signals.command is not None
            or not signals.direct_request
            or status.in_crisis
            or assessment.level >= CrisisLevel.L1
            or rules.level >= CrisisLevel.L1
        ):
            return False
        requested = signals.therapy_request
        if not signals.another_method and (requested is None or requested == pending.action_id):
            return False
        saved = self._stabilization_only
        self._stabilization_only = saved or pending.stabilization
        try:
            shelved = frozenset([*self._state.user_shelved_actions, pending.action_id])
            allowed = self._allowed(HelpStage.S_EMPOWER, perception, flags, shelved)
        finally:
            self._stabilization_only = saved
        deck = self._engine.data.cards.cards
        return any(a in deck and a != pending.action_id for a in allowed.candidates)

    @staticmethod
    def _feedback_for(
        pending: _Pending | None, transition: Transition, signals: TurnSignals
    ) -> Feedback | None:
        """The feedback this turn gives the waiting card, if any (no side effects)."""
        if pending is None or transition.previous is not pending.stage:
            return None
        if pending.stage is HelpStage.S_EMPOWER:
            reason = transition.reason
            if reason not in _EMPOWER_EXITS:
                return None
            if reason is Reason.EMPOWER_TO_CLOSING:
                return Feedback.NOT_NOW if signals.command is Command.NOT_NOW else Feedback.HELPFUL
            return Feedback.UNHELPFUL
        # The answer still counts when the same turn moves on (S_explore -> S_clarify),
        # but never inside a crisis.
        if transition.state.current_stage is HelpStage.S_CRISIS:
            return None
        if signals.command is not None:
            return _COMMAND_FEEDBACK[signals.command]
        return Feedback.UNHELPFUL if signals.aversion else None

    def _apply_feedback(self, pending: _Pending, feedback: Feedback, now: datetime) -> None:
        if feedback is Feedback.NOT_NOW:
            shelved = self._state.user_shelved_actions
            if pending.action_id not in shelved:
                self._state = replace(
                    self._state, user_shelved_actions=[*shelved, pending.action_id]
                )
                self._shelved_at[pending.action_id] = now
            if pending.action_id in self._carried_kit:
                self._carried_kit.remove(pending.action_id)
        self._sampler.update(pending.action_id, pending.spectrum, feedback, now)

    # -- helpers --------------------------------------------------------------------------

    def _plain_slots(self) -> Slots:
        return Slots(user_name=self._profile.user_name, agent_name=self._profile.agent_name)

    def _has_taboo(self, reply: str, mirrored: str) -> bool:
        topics = [t.casefold() for t in self._profile.taboo_topics if t.strip()]
        if not topics:
            return False
        own = reply.replace(mirrored, "") if mirrored else reply
        folded = own.casefold()
        return any(topic in folded for topic in topics)

    def _note_gate(self) -> bool:
        """Record the last gate verdict's check names; True when it passed."""
        result = self._engine.last_gate
        if result is None or result.ok:
            return True
        self._gate_notes.extend(reason.split(":", 1)[0] for reason in result.reasons)
        return False


# Round 3 (re-test r3): the chat's help commands, as folded by ``normalize`` (NFKC maps
# the full-width ／ and ？ to these).
_HELP_COMMANDS: Final = frozenset({"/help", "/帮助", "/?"})
# Round 3: a question ("12356收费吗", "能不能讲普通话", "is it free?").
_QUESTION_END: Final = re.compile(r"(?:吗|呢|么|嘛|吧|\?|？)[\s.。!！~…]*$")
_QUESTION_WORDS: Final = (
    "能不能", "可不可以", "是不是", "有没有", "会不会", "要不要", "有冇", "系唔系", "多少", "几点",
    "什么时候", "怎么", "is it", "is there", "are there", "can i", "do they", "does it",
)  # fmt: skip


def _asks(text: str) -> bool:
    """The message asks something (a question mark or particle, or a question word)."""
    folded = text.strip().casefold()
    return _QUESTION_END.search(folded) is not None or any(w in folded for w in _QUESTION_WORDS)


def _hotline_followup(signals: TurnSignals) -> bool:
    """The message asks about the numbers: a real name, abroad, cost, hours, language,
    whether they are real, more of them, or a place the user is in (round 3)."""
    return (
        signals.hotline_anonymous
        or signals.hotline_abroad
        or signals.hotline_fee
        or signals.hotline_hours
        or signals.hotline_language
        or signals.hotline_real
        or signals.hotline_more
        or signals.hotline_place is not None
    )


# Round 3: a message says something new while a card waits only with this many characters
# left once leading acknowledgements are dropped ("嗯，我看看" is about the card).
_NEW_WORDS_MIN: Final = 5
_LEAD_ACK: Final = re.compile(
    r"^(?:[嗯恩哦噢喔呃额诶哎啊好行对]|好的|好吧|知道了|ok|okay)+[\s,.!?~，。！？、…]*"
)
_WORD_CHAR: Final = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


def _has_words(text: str) -> bool:
    """New words, not only an acknowledgement of the card ("嗯，我看看", "好的")."""
    body = text.strip()
    while True:
        match = _LEAD_ACK.match(body)
        if match is None or not match.group(0):
            break
        body = body[match.end() :]
    return len(_WORD_CHAR.findall(body)) >= _NEW_WORDS_MIN


def _fill_names(template: str, values: Mapping[str, str]) -> str:
    # A Latin name next to a Chinese character gets a space ("Olivia 都在"; dogfood P8).
    return spaced_fill(template, values)


def _uncapped(assessment: CrisisAssessment) -> dict[str, object]:
    """``inspect["uncapped_level"]``, only on a turn the F10 denial cap lowered (display:
    ``--inspect`` shows both levels; in a crisis the tracker reads the uncapped one)."""
    level = assessment.uncapped_level
    return {} if level is None else {"uncapped_level": level.name}


def _asks_to_forget(text: str) -> bool:
    """A short message asking OLIVIA to wipe its memory ("清空所有记忆")."""
    folded = normalize(text)
    return len(folded) <= _FORGET_MAX_CHARS and _FORGET_RE.search(folded) is not None
