"""Pure business rules from specs/schemas.md.

Nothing in this package touches the database, the network or the clock:
every input (including "today" and the holiday set) is passed in explicitly,
which keeps the rules deterministic and unit-testable.
"""
