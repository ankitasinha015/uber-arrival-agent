# User Personas — Trip Concierge

Five travelers, one agent. The concierge watches a whole trip from the booking
email and responds **in proportion** — the same engine hand-holds a nervous
first-timer and stays silent for the road warrior. Each persona is a real trip
profile mapped to how the agent actually behaves: which moments fire, how loud,
and what its memory has learned.

Each traveler lands in a **different city** — Chicago, New York, Los Angeles,
San Francisco, and **Berlin (international)** — so the location engine (live
geocode + real nearby restaurants + local currency) is exercised end to end. The
dinner set is always real places near *that* hotel, ranked by *that* traveler's
Uber Eats taste.

**The intensity dial** — how much the agent acts:
- **HIGH** — full action list, every step approved
- **LOW** — one optional offer, then quiet
- **NONE** — silent; nothing worth interrupting for

---

## 01 · Priya Nair — The First-Time Flyer  `TRIP·NEW`  ·  intensity **HIGH**

26 · first solo work trip · EWR → ORD · lands Chicago
Trips/yr 1–2 · Eats: Thai, Ramen · Arrival: late, unfamiliar city

- **Job:** "Don't let me miss anything. Tell me what to do and *when*." She's
  never navigated a big airport alone and is terrified of both missing the
  flight and landing somewhere strange at 1 a.m.
- **Agent:** Full intensity — every moment fires, nothing assumed. A
  leave-30-min-early nudge when security reads 45 min, a hold-my-room ask before
  it touches the hotel, and on arrival a welcome, a realistic time-to-exit, and
  dinner to the room. She approves each step.
  `departure nudge` · `ask-first hotel` · `exit-time` · `dinner`
- **Quote:** *"I didn't even know I could ask the hotel to hold my room. It
  just… offered, and waited for me to say yes."*

## 02 · Marcus Boyd — The Road Warrior  `TRIP·PRO`  ·  intensity **LOW** (memory-trimmed)

44 · management consultant · SFO → JFK · lands New York · 45+ flights/yr
Trips/yr 45+ · Eats: Burger, American · Arrival: routine, self-managed

- **Job:** "Don't nag me. Surface *only* what I'd actually miss." He already
  calls his own hotels and knows every gate — a chatty assistant is worse than
  none.
- **Agent:** The **behavior memory** earns its keep: it has watched him dismiss
  "notify hotel" every trip, so it stops offering. What's left is a security
  heads-up only when the line is genuinely long, and a one-tap reorder of his
  usual. Trust is won by subtraction.
  `behavior memory` · `drops routine to-dos` · `one-tap reorder`
- **Quote:** *"It learned to stop asking about the hotel. That's the exact
  moment I started trusting it."*

## 03 · Olivia Chen — The On-Time Optimist  `TRIP·CALM`  ·  intensity **NONE→LOW**

33 · product marketer · JFK → LAX · lands Los Angeles 9:40 p.m., on schedule
Trips/yr 8 · Eats: Mexican, Pizza · Arrival: on time, early evening

- **Job:** "If everything's fine, leave me alone — but *be there* if it isn't."
  A smooth trip shouldn't generate notifications just to look busy.
- **Agent:** The dial does its quietest work here. Security's short and the data's
  fresh, so no leave-early nudge. She gets a warm "you're in early, everything's
  on track," one optional dinner offer, and then silence. The restraint *is* the
  product.
  `intensity: NONE` · `no false nudge` · `single optional offer`
- **Quote:** *"It told me I was in early and on track, made one small offer, and
  then got out of my way. Perfect."*

## 04 · Dev Patel — The Red-Eye Arriver  `TRIP·CHANGE`  ·  intensity **HIGH** (recovery)

38 · engineer · EWR → SFO · lands San Francisco · **airline rebooked him** (UA 517 → UA 892), now 2:40 a.m.
Trips/yr 15 · Eats: Ramen, Mexican · Arrival: changed, past midnight

- **Job:** "It's late and my flight got changed — *make the landing soft*."
  Check-in is about to close and he has nothing left to problem-solve with.
- **Agent:** The flight-change flow at full tilt. It detects the airline moved
  him off UA 517 onto UA 892, re-estimates arrival to 2:40 a.m., and offers to
  **update the hotel** — a change-aware note ("my flight was changed, now on
  UA 892…") he approves or edits. On arrival: welcome, an honest time-to-exit,
  and his most-ordered ramen to the room so food beats him upstairs.
  `detect flight change` · `update hotel (new flight + time)` · `re-estimate arrival` · `dinner to room`
- **Quote:** *"I landed at 1 a.m. to a held room and ramen already on its way
  up. I nearly cried."*

## 05 · Lena Kowalski — The Creature of Habit  `TRIP·TASTE`  ·  intensity **LOW** (taste-led)

29 · designer · JFK → BER · lands Berlin (international, €) · orders the same cuisines relentlessly
Trips/yr 12 · Eats: 80% Mexican · Arrival: decision-fatigued

- **Job:** "Don't make me choose. You already *know* what I want." After a
  travel day the last thing she wants is to scroll a food app.
- **Agent:** This is the moat. It ranks what's actually open near the hotel by
  *her real Uber Eats order history* — Mexican first, badged "matches what you
  order." One tap surfaces her most-ordered Carnitas Burrito, ordered to the
  room. A standalone app has no first-party order history to do this; at Uber
  it's a byproduct.
  `taste ranking` · `first-party order history` · `most-ordered dish`
- **Quote:** *"It ranked the whole city by the food I actually eat. No other app
  has that data on me."*

---

Each persona is selectable from the demo's **traveler login screen**, or deep-linked
directly — `?mode=priya`, `?mode=marcus`, `?mode=olivia`, `?mode=dev`, `?mode=lena`.
The through-line: **one engine, proportionate response.** Same agent, five very
different traveler needs — different cities, tastes, and trip states — met by acting
more or less rather than always the same.
