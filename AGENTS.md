# Working rules for this repository

## Do not stop until the plan is complete

This project runs against a written plan (`analysis/PLAN_<date>.md`). While that plan has an item whose Status is not
`done`, keep working: pick the next item in the plan's own order, finish it, record the evidence next to it, and move to
the next one. Do not end a turn to report progress, do not ask what to do next, and do not wait for a reply — the user is
often away and every pause is lost machine time.

Stop only when one of these is true, and say so in one line:

- the next step needs a decision only the user can make (a look/pick from an A/B sheet, a settings change on their
  Steam account, permission to touch something outside this repository);
- the next step needs hardware or a person that is not here (the laptop, combat, cutscenes);
- the suite cannot be made green and the failure is not understood — in that case revert to the last green state first,
  then record what was learned next to the item.

Everything else: keep going. A red suite is never a stopping point you leave behind; a green suite with one item further
along is the deliverable.

## Ground rules that hold in every session

- Nothing is committed or pushed unless the user asks.
- The game folder is written only by `checks/install_live_dll.py` (hash-pinned, with a rollback folder) and by the game
  itself. Game runs use a copy of the Proton prefix; the real save is hashed before and after every run
  (`analysis/runtime/game-runs/guard.sh`) and restored from `save-backup-*` on any change.
- Every behavioural change ships behind a switch that defaults to today's behaviour, gated in `analysis/checks/`, and only
  after its gate has been seen to fail for the right reason.
