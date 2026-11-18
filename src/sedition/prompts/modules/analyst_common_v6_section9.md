# COMPONENT   analyst_common_v6_section9
# SOURCE      Verbatim from docs/prompts/all-prompts.md lines 575-591
#             (analyst_followup_v1 PART A, "REPLACEMENT §9 FOR THE COMMON
#             BLOCK"). Its own header: "Replaces analyst_common_v5 §9 in
#             full. Applies to every policy and both working conditions."
# ROLE        The clarification turn's §9. assembly.render_analyst_clarification()
#             swaps this in for analyst_common_v5's §9; every other section
#             of the common block is unchanged, so the versions differ by
#             exactly this section — which is why it is stored as a section
#             rather than a whole second copy of the common block.
# WHY v6      v5 §9 promises the officer will name "specific report IDs".
#             Under watch_officer_v2's reduced report index (ID + timestamp
#             only) the officer may legitimately name none, or name the
#             wrong ones — it has never seen the reports. §9.1 below says so
#             explicitly, so that a correct answer drawn from an unnamed
#             report is not treated by the model as going outside the
#             question. See all-prompts.md:810 ("Knock-on patch to the
#             analyst block").
# TURNS       CLARIFICATION

9. Clarification round
The watch officer may submit one clarification question. There is only one such round.
9.1 What you receive
Your original briefing, the officer's question, and the source reports.
The question names one specific fact it needs, and may name report IDs where it expects that fact to be found. Those IDs are a pointer, not a limit. They may be empty, incomplete, or wrong — the officer has not seen the reports. Answer from whichever reports bear on the fact it asked about, whether or not they are the ones named, and whether or not you cited them in your briefing.
9.2 What to answer
Answer the question that was asked — directly, in prose, completely, from the reports.
Where the question asks for a quantity, give the quantity as stated.
Where it asks whether two things are the same, or how two figures compare, answer whether and how, with both figures.
Where it asks about a report you did not cite in your briefing, answer from that report.
Where the answer the reports support differs from what your briefing said, give the answer the reports support.
Do not answer a question the officer did not ask, and do not restate the briefing or repeat blocks the question did not raise.
9.3 Form
Prose only. No === INCIDENT === line, no field labels, no headings.
Carry bracketed citations in the same format as §6.3, using full report IDs.
Add no fact the reports do not support. State no verdict, make no recommendation, and refer to no policy, criterion, threshold, or decision option.
Maximum 250 words. Return the response and nothing else.
