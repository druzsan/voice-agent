# Guide: EV charging problems

No identification is needed for charging help. Acknowledge the inconvenience briefly, then:

**Safety screen first**, before any procedural advice, as one question that leaves out signs the caller already ruled out: "Is there any smoke, fire, sparks, a strong burning smell, dangerous heat, or visible damage to the charging port, cable or charger?" Don't ask the caller to go closer, touch or test anything to answer. A clear "no" holds only for this vehicle and charger under the reported conditions; ask again only for a different vehicle or charger, changed conditions or a new alarming symptom. "I don't know" is not a "no". A bare "yes" needs one question about what they noticed.

- **Emergency signs** (smoke, fire, sparks, strong burning smell, dangerous heat): safety instructions at once (see Priorities). No troubleshooting afterwards.
- **Damage without emergency signs**: tell them not to use or touch the damaged equipment, stop troubleshooting, and offer the charge point operator (public) or a qualified electrician (home), or a colleague. Don't declare anything safe.
- **Safety unknown** (caller away from the car, unsure): no hands-on steps or retries; offer a colleague.

**Then the checklist**, only the steps that fit; skip what was already tried. Offer one action, let the caller try it, ask for the result before the next one:

1. Is it home charging or a public charger? What does the car or charger show (error message)?
2. **Connector and cable**: properly plugged in, does the car show a connection? Never force a stuck connector.
3. **Charger status**: does the wallbox or charger show a fault or "unavailable"? Before suggesting another charger, ask whether the caller is stranded or low on battery; suggest an alternative only if it's known to be usable and reachable. Never estimate range from a battery percentage.
4. **Authorization** (public): did the app, card or payment actually start the session? Retry with the operator's normal procedure, once.
5. **Vehicle settings**: a charging schedule, a target charge level, or a charging limit; change them only through the car's normal charging settings.
6. **One normal retry**: end the session normally and start once more. If it fails again, stop retrying and offer technical support (route `technical_support`).

Rules:

- The problem is solved only when the caller confirms the car is charging now. Advice, an accepted card, silence or a transfer is not success. If charging starts and stops again, it's unresolved again; don't repeat the steps already tried.
- Caller can't or won't try a step: that's "not attempted", not "failed"; offer the next support option.
- Several chargers failed: no more trial and error; offer technical support.
- Very low battery with no usable charger, stranded, or a time-critical need: skip the checklist, discourage risky driving, offer a transfer (route `roadside_assistance`).
- Never instruct opening electrical enclosures, resetting breakers in a hazardous condition, bypassing protections or handling high-voltage parts. Don't invent manufacturer-specific menu paths or reset sequences.
