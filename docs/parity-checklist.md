# apple-events → macos-apps-mcp parity checklist (#5)

**Gate:** when every row passes (the cockpit `/today` briefing renders the same off macos-apps-mcp as it
did off apple-events), the **cockpit** drops `apple-events` from its MCP config and updates
`meta/SETUP.md`. That edit happens in the cockpit repo, not here.

Parity = what the briefing consumes, **not** feature-parity with apple-events (tags, recurrence,
subtasks, alarms, geofences are v1 non-goals — see the spec §9).

| Briefing need | macos-apps-mcp tool | Pass? |
|---|---|---|
| Reminders due today (+ overdue) | `reminders(due="today")` | ☐ |
| Overdue reminders | `reminders(due="overdue")` | ☐ |
| This week's reminders | `reminders(due="this-week")` | ☐ |
| Reminders in a named list | `reminders(due="<List Name>")` | ☐ |
| Today's events | `events(when="today")` | ☐ |
| This week's events | `events(when="week")` | ☐ |
| Events on a specific day | `events(when="YYYY-MM-DD")` | ☐ |
| Each item is a citable Pointer (id + summary + deeplink) | all reads | ☐ |
| Deeplinks open the item / its day on this Mac | manual check | ☐ |

## How to run it
With macos-apps-mcp configured in the cockpit's MCP config, regenerate `/today` and confirm each row
matches the apple-events output it replaces. Verify deeplinks by opening a couple by hand.
